"""Metrics tests — savings math (incl. NEGATIVE savings), FR-14 error-union
reconciliation over mismatched error sets, FR-15 compatibility-guard aborts,
accuracy/agreement/completion scoring, quality gate. SPEC §10/§13/FR-14/FR-15."""
from __future__ import annotations

import pytest

from tokenpoc.metrics import (
    CompatibilityError,
    aggregate,
    check_compatibility,
    compare,
    completion_rate,
    quality_gate,
    reconcile_error_union,
    score_accuracy,
    strategy_agreement,
)
from tokenpoc.models import ModelCallRecord, RunSummary, TicketResult


def _call(version, tid, role, inp, out):
    return ModelCallRecord(
        run_id="r",
        version=version,
        ticket_id=tid,
        call_role=role,
        model_id="m",
        input_tokens=inp,
        output_tokens=out,
        latency_ms=1.0,
        timestamp="2026-10-14T00:00:00Z",
    )


def _result(version, tid, status="OK", calls=(), strategy="TEMPLATE_REPLY", category="PASSWORD_RESET",
            priority="LOW", escalate=False, queue="", reply="hi there", fallback=False, repair=0,
            gates_fired=(), jev_calls=()):
    return TicketResult(
        ticket_id=tid, version=version, status=status,
        category=None if status == "ERROR" else category,
        priority=None if status == "ERROR" else priority,
        escalate=None if status == "ERROR" else escalate,
        queue=None if status == "ERROR" else queue,
        strategy=None if status == "ERROR" else strategy,
        reply=None if status == "ERROR" else reply,
        fallback=fallback, gates_fired=list(gates_fired), repair_retries=repair,
        model_calls=list(calls), jev_calls=list(jev_calls),
    )


GOLD = {
    "T-1": {"category": "PASSWORD_RESET", "priority": "LOW", "escalate": False, "queue": "", "strategy": "TEMPLATE_REPLY"},
    "T-2": {"category": "BILLING_DISPUTE", "priority": "HIGH", "escalate": True, "queue": "billing-agents", "strategy": "CUSTOM_REPLY"},
    "T-3": {"category": "ORDER_STATUS", "priority": "MEDIUM", "escalate": False, "queue": "", "strategy": "AUTO_RESOLVE"},
}


class TestAggregation:
    def test_token_sums_and_call_roles(self):
        results = [
            _result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 100, 20)]),
            _result("V1", "T-2", strategy="CUSTOM_REPLY",
                    calls=[_call("V1", "T-2", "TRIAGE", 110, 25), _call("V1", "T-2", "REPLY", 200, 150)]),
            _result("V1", "T-3", repair=1,
                    calls=[_call("V1", "T-3", "TRIAGE", 100, 30), _call("V1", "T-3", "REPAIR", 120, 30)]),
        ]
        agg = aggregate(results)
        assert agg.model_calls == 5
        assert agg.triage_calls == 3
        assert agg.reply_calls == 1
        assert agg.repair_retries == 1
        assert agg.input_tokens == 100 + 110 + 200 + 100 + 120
        assert agg.output_tokens == 20 + 25 + 150 + 30 + 30
        assert agg.total_tokens == agg.input_tokens + agg.output_tokens

    def test_include_ids_restricts_aggregation(self):
        results = [
            _result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 100, 20)]),
            _result("V1", "T-2", calls=[_call("V1", "T-2", "TRIAGE", 999, 999)]),
        ]
        agg = aggregate(results, include_ids={"T-1"})
        assert agg.requests == 1
        assert agg.total_tokens == 120


class TestSavingsMath:
    def test_positive_savings(self):
        v1 = [_result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 500, 50)])]
        v2 = [_result("V2", "T-1")]  # zero Copilot model tokens
        c = compare(v1, v2, GOLD, "mock")
        assert c.tokens_saved == 550
        assert c.reduction_pct == pytest.approx(100.0)

    def test_negative_savings_reported_signed(self):
        """AC-10: no floor at zero, no directional assumption."""
        v1 = [_result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 100, 10)])]
        v2 = [_result("V2", "T-1", strategy="CUSTOM_REPLY", fallback=True,
                      calls=[_call("V2", "T-1", "REPLY", 400, 300)])]
        c = compare(v1, v2, GOLD, "mock")
        assert c.tokens_saved == 110 - 700
        assert c.tokens_saved < 0
        assert c.reduction_pct < 0

    def test_zero_baseline_no_division_error(self):
        v1 = [_result("V1", "T-1")]
        v2 = [_result("V2", "T-1")]
        c = compare(v1, v2, GOLD, "mock")
        assert c.tokens_saved == 0
        assert c.reduction_pct == 0.0


class TestFR14ErrorUnionReconciliation:
    def test_union_of_mismatched_error_sets_excluded(self):
        """V1 errors on T-2, V2 errors on T-3 → both excluded from BOTH sides."""
        v1 = [
            _result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 100, 10)]),
            _result("V1", "T-2", status="ERROR"),
            _result("V1", "T-3", calls=[_call("V1", "T-3", "TRIAGE", 100, 10)]),
        ]
        v2 = [
            _result("V2", "T-1"),
            _result("V2", "T-2", strategy="CUSTOM_REPLY", calls=[_call("V2", "T-2", "REPLY", 500, 400)]),
            _result("V2", "T-3", status="ERROR"),
        ]
        include, excluded = reconcile_error_union(v1, v2)
        assert excluded == ["T-2", "T-3"]
        assert include == {"T-1"}
        c = compare(v1, v2, GOLD, "mock")
        assert c.effective_n == 1
        assert c.excluded_ticket_ids == ["T-2", "T-3"]
        # V2's T-2 tokens (900) must NOT appear: aggregates over intersection only
        assert c.optimized.input_tokens == 0
        assert c.baseline.total_tokens == 110

    def test_no_errors_means_full_set(self):
        v1 = [_result("V1", "T-1"), _result("V1", "T-2", strategy="CUSTOM_REPLY")]
        v2 = [_result("V2", "T-1"), _result("V2", "T-2", strategy="CUSTOM_REPLY")]
        include, excluded = reconcile_error_union(v1, v2)
        assert excluded == []
        assert include == {"T-1", "T-2"}


def _summary(**overrides):
    base = dict(
        run_id="r1", version="V1", timestamp="t", model_id="test-model-1",
        temperature=0.0, dataset_file="tickets.jsonl", dataset_hash="abc123",
        prompt_hashes={"triage_system": "h1", "reply_system": "h2", "repair_system": "h3"},
        ticket_ids=["T-1", "T-2"], requests_processed=2, error_ticket_ids=[],
        model_calls=0, triage_calls=0, reply_calls=0, repair_retries=0,
        jev_calls=0, jev_decisions=0,
        fallback_intent=0, fallback_strategy=0, fallback_escalate=0,
        jev_input_tokens=0, jev_output_tokens=0,
        model_input_tokens=0, model_output_tokens=0, model_total_tokens=0,
    )
    base.update(overrides)
    return RunSummary(**base)


class TestFR15CompatibilityGuard:
    def test_matching_artifacts_pass(self):
        check_compatibility(_summary(), _summary(run_id="r2", version="V2"))

    @pytest.mark.parametrize(
        "field,value",
        [
            ("dataset_hash", "zzz999"),
            ("model_id", "other-test-model"),
            ("prompt_hashes", {"reply_system": "DIFFERENT"}),
            ("ticket_ids", ["T-1"]),
        ],
    )
    def test_any_mismatch_aborts(self, field, value):
        with pytest.raises(CompatibilityError) as exc:
            check_compatibility(_summary(), _summary(version="V2", **{field: value}))
        assert exc.value.mismatches  # differing fields are reported

    def test_missing_reply_prompt_hash_is_a_mismatch(self):
        with pytest.raises(CompatibilityError):
            check_compatibility(_summary(prompt_hashes={}), _summary(version="V2", prompt_hashes={}))


class TestQualityScoring:
    def test_accuracy_per_operation(self):
        results = [
            _result("V1", "T-1"),  # all correct vs GOLD["T-1"]
            _result("V1", "T-2", category="GENERAL_INQUIRY", priority="HIGH",
                    escalate=True, queue="billing-agents", strategy="CUSTOM_REPLY"),  # category wrong
        ]
        acc = score_accuracy(results, GOLD, {"T-1", "T-2"})
        assert acc["category"] == 50.0
        assert acc["priority"] == 100.0
        assert acc["strategy"] == 100.0

    def test_agreement_and_disagreement_listing(self):
        v1 = [_result("V1", "T-1"), _result("V1", "T-2", strategy="CUSTOM_REPLY")]
        v2 = [_result("V2", "T-1"), _result("V2", "T-2", strategy="TEMPLATE_REPLY")]
        pct, disagreements = strategy_agreement(v1, v2, GOLD, {"T-1", "T-2"})
        assert pct == 50.0
        assert disagreements == [
            {"ticket_id": "T-2", "v1_strategy": "CUSTOM_REPLY",
             "v2_strategy": "TEMPLATE_REPLY", "gold_strategy": "CUSTOM_REPLY"}
        ]

    def test_completion_fails_on_unresolved_placeholder(self):
        ok = _result("V1", "T-1")
        bad = _result("V1", "T-2", reply="Hi {name}, your order {order_id} ...")
        assert completion_rate([ok], {"T-1"}) == 100.0
        assert completion_rate([ok, bad], {"T-1", "T-2"}) == 50.0

    def test_completion_fails_on_error_or_empty_reply(self):
        err = _result("V1", "T-1", status="ERROR")
        empty = _result("V1", "T-2", reply="   ")
        assert completion_rate([err, empty], {"T-1", "T-2"}) == 0.0


class TestJevUsageAndCost:
    """SPEC §10 / AC-11: Jev usage measured per call, priced at configured rates;
    net cost delta is signed; pricing changes cost lines, never token lines."""

    def _jev_call(self, tid, inp, out, answers=None, gates=()):
        from tokenpoc.models import ChoiceR, JevCallRecord

        return JevCallRecord(
            run_id="r", ticket_id=tid,
            answers=answers or {"q_intent": ChoiceR(choice="PASSWORD_RESET",
                                                    probabilities={"PASSWORD_RESET": 1.0},
                                                    confidence=1.0)},
            gates_fired=list(gates), input_tokens=inp, output_tokens=out,
            latency_ms=1.0, provider="mock",
        )

    def test_jev_calls_vs_decisions_terminology(self):
        """§10: Jev Calls = API invocations (1/ticket); Jev Decisions = 4 × N."""
        from tokenpoc.models import ChoiceR, NoulR, ScoreR

        answers = {
            "q_intent": ChoiceR(choice="A", probabilities={"A": 1.0}, confidence=1.0),
            "q_priority": ScoreR(score=0.5, probabilities={"LOW": 1.0}, confidence=1.0),
            "q_escalate": NoulR(noul=0.1),
            "q_strategy": ChoiceR(choice="TEMPLATE_REPLY",
                                  probabilities={"TEMPLATE_REPLY": 1.0}, confidence=1.0),
        }
        results = [
            _result("V2", f"T-{i}", jev_calls=[self._jev_call(f"T-{i}", 120, 4, answers)])
            for i in range(3)
        ]
        agg = aggregate(results)
        assert agg.jev_calls == 3
        assert agg.jev_decisions == 12  # 4 per call
        assert agg.jev_input_tokens == 360
        assert agg.jev_output_tokens == 12

    def test_jev_cost_at_published_rates(self):
        # 1M input tokens at $0.042/1M, output free
        results = [_result("V2", "T-1", jev_calls=[self._jev_call("T-1", 1_000_000, 50_000)])]
        agg = aggregate(results)
        assert agg.jev_cost == pytest.approx(0.042)

    def test_net_cost_delta_unavailable_for_copilot_subscription(self):
        """Copilot is subscription/prompt-accounted, so token-based USD delta is N/A."""
        v1 = [_result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 1_000_000, 0)])]
        v2 = [_result("V2", "T-1", strategy="CUSTOM_REPLY",
                      calls=[_call("V2", "T-1", "REPLY", 2_000_000, 0)],
                      jev_calls=[self._jev_call("T-1", 1_000_000, 0)])]
        c = compare(v1, v2, GOLD, "mock")
        assert c.net_cost_delta is None
        assert c.optimized.jev_cost == pytest.approx(0.042)

    def test_per_gate_fallback_counts(self):
        results = [
            _result("V2", "T-1", gates_fired=["intent"]),
            _result("V2", "T-2", gates_fired=["strategy", "escalate"]),
            _result("V2", "T-3", gates_fired=["escalate"]),
        ]
        agg = aggregate(results)
        assert agg.fallback_intent == 1
        assert agg.fallback_strategy == 1
        assert agg.fallback_escalate == 2
        assert agg.fallback_count == 2  # routing gates only (intent+strategy)


class TestQualityGate:
    def test_passes_within_threshold_and_full_completion(self):
        g = quality_gate(90.0, 86.0, 100.0)
        assert g["passed"] is True
        assert "acceptable quality" in g["verdict"]

    def test_fails_beyond_5_points(self):
        g = quality_gate(90.0, 84.0, 100.0)
        assert g["passed"] is False
        assert "REGRESSION" in g["verdict"]

    def test_fails_on_incomplete_tasks(self):
        g = quality_gate(90.0, 90.0, 99.0)
        assert g["passed"] is False

    def test_v2_better_than_v1_passes(self):
        g = quality_gate(80.0, 95.0, 100.0)
        assert g["passed"] is True
