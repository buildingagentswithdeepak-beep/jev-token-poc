"""Pipeline + routing + provider tests — both AI providers mocked (SPEC §16 testing row).

Covers: V1 triage/repair/token counting, V2 single Jev call + per-question gates,
Score→priority cut-points, Noul unsure band, derived-confidence math, zero-token
templates, rule overrides, template engine, mock provider determinism, live
adapter parsing, and mock watermarking in the report output.
"""
from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from tests.conftest import FakeModelClient, make_ticket
from tokenpoc.models import (
    ChoiceR,
    JevResponse,
    JevUsage,
    NoulR,
    ScoreR,
    TriageDecision,
    derived_confidence,
)
from tokenpoc.pipeline_v1 import process_ticket_v1
from tokenpoc.pipeline_v2 import process_ticket_v2, score_to_priority
from tokenpoc.prompts_loader import load_jev_questions
from tokenpoc.providers.mock_jev import MockDecisionProvider, escalation_for
from tokenpoc.report import MOCK_WATERMARK, render_comparison, render_verbose_request
from tokenpoc.routing import OrderStore, apply_rule_overrides, fill_template


@pytest.fixture
def store(tmp_path):
    orders = {"T-001": {"order_id": "ORD-1", "status": "IN_TRANSIT", "carrier": "FastShip", "eta": "2026-10-20"}}
    p = tmp_path / "orders.json"
    p.write_text(json.dumps(orders), encoding="utf-8")
    return OrderStore(p)


class ScriptedProvider:
    """Returns a fixed JevResponse — for exercising exact gate conditions."""

    def __init__(self, answers, usage=None, provider="mock"):
        self._resp = JevResponse(
            answers=answers,
            usage=usage or JevUsage(input_tokens=100, output_tokens=4),
            latency_ms=1.0,
            provider=provider,
        )
        self.calls = 0

    def evaluate(self, state, questions):
        self.calls += 1
        return self._resp


def confident_answers(
    intent="BILLING_DISPUTE",
    strategy="CUSTOM_REPLY",
    noul=0.93,
    score=2.1,
    intent_conf=0.9,
    strategy_conf=0.9,
):
    return {
        "q_intent": ChoiceR(choice=intent, probabilities={intent: 0.95}, confidence=intent_conf),
        "q_priority": ScoreR(score=score, probabilities={"HIGH": 0.9}, confidence=0.9),
        "q_escalate": NoulR(noul=noul),
        "q_strategy": ChoiceR(choice=strategy, probabilities={strategy: 0.95}, confidence=strategy_conf),
    }


class TestV1Pipeline:
    def test_custom_reply_ticket_makes_two_calls_with_measured_usage(self, store):
        client = FakeModelClient()
        r = process_ticket_v1(make_ticket(), client, store, "run1")
        assert r.status == "OK"
        assert [c.call_role for c in r.model_calls] == ["TRIAGE", "REPLY"]
        assert all(c.version == "V1" for c in r.model_calls)  # AC-3 tagging
        assert r.model_input_tokens > 0 and r.model_output_tokens > 0
        assert r.strategy == "CUSTOM_REPLY"
        assert "Helio Support Team" in r.reply

    def test_template_ticket_makes_one_call_and_deterministic_reply(self, store):
        client = FakeModelClient(triage_json={
            "category": "PASSWORD_RESET", "priority": "LOW",
            "escalate": False, "queue": "", "strategy": "TEMPLATE_REPLY"})
        r = process_ticket_v1(make_ticket(subject="Can't log in"), client, store, "run1")
        assert [c.call_role for c in r.model_calls] == ["TRIAGE"]
        assert "reset" in r.reply.lower()
        assert "{" not in r.reply  # all template variables resolved

    def test_malformed_json_triggers_one_counted_repair_retry(self, store):
        client = FakeModelClient(malformed_first_n=1)
        r = process_ticket_v1(make_ticket(), client, store, "run1")
        assert r.status == "OK"
        assert r.repair_retries == 1
        roles = [c.call_role for c in r.model_calls]
        assert roles[:2] == ["TRIAGE", "REPAIR"]
        # repair tokens ARE counted (§8)
        assert r.model_input_tokens == sum(c.input_tokens for c in r.model_calls)

    def test_persistent_malformed_json_marks_error(self, store):
        client = FakeModelClient(malformed_first_n=5)
        r = process_ticket_v1(make_ticket(), client, store, "run1")
        assert r.status == "ERROR"
        assert r.repair_retries == 1  # exactly ONE repair retry, then fail

    def test_api_failure_marks_error_not_crash(self, store):
        client = FakeModelClient(fail_always=True)
        r = process_ticket_v1(make_ticket(), client, store, "run1")
        assert r.status == "ERROR"
        assert "simulated" in r.error


class TestDerivedConfidenceAndScoreMapping:
    def test_derived_confidence_formula(self):
        """SPEC §6: confidence = (n·p_max − 1)/(n − 1), NOT the top probability."""
        probs6 = {c: (0.70 if c == "A" else 0.06) for c in "ABCDEF"}
        assert derived_confidence(probs6) == pytest.approx((6 * 0.70 - 1) / 5)  # 0.64
        probs3 = {"X": 0.70, "Y": 0.15, "Z": 0.15}
        assert derived_confidence(probs3) == pytest.approx((3 * 0.70 - 1) / 2)  # 0.55
        assert derived_confidence({"A": 1.0, "B": 0.0}) == pytest.approx(1.0)
        uniform = {c: 1 / 6 for c in "ABCDEF"}
        assert derived_confidence(uniform) == pytest.approx(0.0)

    @pytest.mark.parametrize(
        "score,expected",
        [(0.0, "LOW"), (0.49, "LOW"), (0.5, "MEDIUM"), (1.49, "MEDIUM"),
         (1.86, "HIGH"), (2.49, "HIGH"), (2.5, "URGENT"), (3.0, "URGENT")],
    )
    def test_score_to_priority_cutpoints(self, score, expected):
        assert score_to_priority(score) == expected


class TestV2Pipeline:
    def test_template_ticket_zero_model_tokens_one_jev_call(self, store):
        """Call-elimination (§3.1) + single-call convention (§6): one Jev call,
        four decisions, zero Copilot model tokens."""
        answers = confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY",
                                    noul=0.07, score=0.3)
        provider = ScriptedProvider(answers)
        t = make_ticket(gold_category="PASSWORD_RESET", gold_priority="LOW",
                        gold_escalate=False, gold_queue="", gold_strategy="TEMPLATE_REPLY")
        r = process_ticket_v2(t, provider, None, store, "run2")  # client=None proves no model client
        assert r.status == "OK"
        assert provider.calls == 1  # ONE Jev call per ticket
        assert len(r.jev_calls) == 1
        assert r.jev_calls[0].decision_count == 4  # 4 logical decisions per call
        assert r.jev_calls[0].input_tokens == 100  # Jev usage captured (FR-6)
        assert r.model_calls == []
        assert r.model_input_tokens == 0
        assert r.priority == "LOW"  # score 0.3 → LOW
        assert r.handled_by == "Jev → template engine"

    def test_billing_dispute_routes_to_model(self, store):
        provider = ScriptedProvider(confident_answers())
        client = FakeModelClient()
        r = process_ticket_v2(make_ticket(), provider, client, store, "run2")
        assert r.status == "OK"
        assert r.strategy == "CUSTOM_REPLY"
        assert [c.call_role for c in r.model_calls] == ["REPLY"]
        assert all(c.version == "V2" for c in r.model_calls)
        assert r.escalate is True and r.queue == "billing-agents"
        assert r.handled_by == "Jev → Copilot model"

    def test_intent_gate_fires_below_050(self, store):
        answers = confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY",
                                    noul=0.07, intent_conf=0.45)
        r = process_ticket_v2(make_ticket(), ScriptedProvider(answers),
                              FakeModelClient(), store, "run2")
        assert r.fallback is True
        assert r.gates_fired == ["intent"]
        assert r.strategy == "CUSTOM_REPLY"
        assert r.handled_by == "Jev (low confidence) → Copilot model"

    def test_strategy_gate_fires_below_060(self, store):
        answers = confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY",
                                    noul=0.07, strategy_conf=0.55)
        r = process_ticket_v2(make_ticket(), ScriptedProvider(answers),
                              FakeModelClient(), store, "run2")
        assert r.gates_fired == ["strategy"]
        assert r.strategy == "CUSTOM_REPLY"

    def test_escalate_unsure_band_forces_escalation_not_routing(self, store):
        """Noul in 0.35–0.65 ⇒ escalate=true (conservative), but routing unchanged."""
        answers = confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY",
                                    noul=0.45, score=0.3)
        r = process_ticket_v2(make_ticket(gold_category="PASSWORD_RESET"),
                              ScriptedProvider(answers), None, store, "run2")
        assert r.gates_fired == ["escalate"]
        assert r.escalate is True
        assert r.fallback is False  # escalate gate is NOT a routing fallback
        assert r.strategy == "TEMPLATE_REPLY"  # still zero Copilot model tokens
        assert r.model_calls == []

    def test_priority_has_no_gate(self, store):
        """SPEC §6 deliberate asymmetry: low Score confidence must NOT trigger anything."""
        answers = confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY", noul=0.07)
        answers["q_priority"] = ScoreR(score=0.4, probabilities={k: 0.25 for k in
                                       ("LOW", "MEDIUM", "HIGH", "URGENT")}, confidence=0.0)
        r = process_ticket_v2(make_ticket(gold_category="PASSWORD_RESET"),
                              ScriptedProvider(answers), None, store, "run2")
        assert r.gates_fired == []
        assert r.fallback is False
        assert r.strategy == "TEMPLATE_REPLY"

    def test_order_status_auto_resolve_uses_data_store(self, store):
        answers = confident_answers(intent="ORDER_STATUS", strategy="AUTO_RESOLVE",
                                    noul=0.07, score=1.0)
        t = make_ticket(tid="T-001", gold_category="ORDER_STATUS", gold_priority="MEDIUM",
                        gold_escalate=False, gold_queue="", gold_strategy="AUTO_RESOLVE")
        r = process_ticket_v2(t, ScriptedProvider(answers), None, store, "run2")
        assert r.strategy == "AUTO_RESOLVE"
        assert "ORD-1" in r.reply and "IN_TRANSIT" in r.reply
        assert r.model_calls == []

    def test_custom_reply_without_client_is_error(self, store):
        r = process_ticket_v2(make_ticket(), ScriptedProvider(confident_answers()),
                              None, store, "run2")
        assert r.status == "ERROR"


class TestRulesAndRouting:
    def test_enterprise_urgent_always_escalates(self):
        d = TriageDecision(category="BUG_REPORT", priority="URGENT",
                           escalate=False, queue="", strategy="TEMPLATE_REPLY")
        t = make_ticket(tier="ENTERPRISE", gold_category="BUG_REPORT")
        out = apply_rule_overrides(d, t)
        assert out.escalate is True
        assert out.queue == "bug-triage"

    def test_billing_dispute_always_escalates(self):
        assert escalation_for("BILLING_DISPUTE", "LOW", "FREE") == (True, "billing-agents")

    def test_routine_ticket_not_escalated(self):
        assert escalation_for("PASSWORD_RESET", "LOW", "FREE") == (False, "")

    def test_template_fill_resolves_all_variables(self, store):
        for cat in ("PASSWORD_RESET", "GENERAL_INQUIRY", "BUG_REPORT"):
            d = TriageDecision(category=cat, priority="LOW", escalate=False,
                               queue="", strategy="TEMPLATE_REPLY")
            reply = fill_template(make_ticket(tid="T-001"), d, store)
            assert reply and "{" not in reply

    def test_auto_resolve_missing_order_uses_fallback_text(self, store):
        d = TriageDecision(category="ORDER_STATUS", priority="MEDIUM",
                           escalate=False, queue="", strategy="AUTO_RESOLVE")
        reply = fill_template(make_ticket(tid="T-999"), d, store)
        assert "could not locate an order" in reply


class TestMockProvider:
    def _state(self, subject, body, tier="PRO"):
        return {"subject": subject, "body": body, "tier": tier,
                "account_age_days": 100, "prior_tickets": 1}

    def test_evaluate_answers_all_four_questions(self):
        p = MockDecisionProvider()
        resp = p.evaluate(self._state("Charged twice", "double charge refund billing"),
                          load_jev_questions())
        assert set(resp.answers) == {"q_intent", "q_priority", "q_escalate", "q_strategy"}
        assert isinstance(resp.answers["q_intent"], ChoiceR)
        assert isinstance(resp.answers["q_priority"], ScoreR)
        assert isinstance(resp.answers["q_escalate"], NoulR)
        assert isinstance(resp.answers["q_strategy"], ChoiceR)
        assert resp.provider == "mock"
        # SPEC §6: mock usage figures clearly zeroed
        assert resp.usage.input_tokens == 0 and resp.usage.output_tokens == 0

    def test_deterministic_same_input_same_output(self):
        qs = load_jev_questions()
        state = self._state("Charged twice", "double charge refund billing")
        r1 = MockDecisionProvider().evaluate(state, qs)
        r2 = MockDecisionProvider().evaluate(state, qs)
        assert r1.answers["q_intent"].choice == r2.answers["q_intent"].choice == "BILLING_DISPUTE"
        assert r1.answers["q_intent"].probabilities == r2.answers["q_intent"].probabilities
        assert r1.answers["q_strategy"].choice == r2.answers["q_strategy"].choice == "CUSTOM_REPLY"

    def test_probabilities_sum_to_one_and_confidence_is_derived(self):
        resp = MockDecisionProvider().evaluate(
            self._state("Charged twice", "refund billing"), load_jev_questions())
        a = resp.answers["q_intent"]
        assert sum(a.probabilities.values()) == pytest.approx(1.0)
        assert a.confidence == pytest.approx(derived_confidence(a.probabilities))

    def test_noise_rate_flattens_confidence(self):
        qs = load_jev_questions()
        state = self._state("hi", "question", "FREE")
        clean = MockDecisionProvider(noise_rate=0.0).evaluate(state, qs)
        noisy = MockDecisionProvider(noise_rate=1.0, seed=7).evaluate(state, qs)
        assert noisy.answers["q_intent"].confidence < clean.answers["q_intent"].confidence


class TestCopilotModelAdapter:
    def test_module_imports_cleanly(self):
        from tokenpoc.providers.copilot import (  # noqa: F401
            CopilotModelClient,
            CopilotModelError,
            CopilotUsageMissing,
        )

    @staticmethod
    def _client_with_fake_session(*, usages, content="hello", model_id="auto"):
        from types import SimpleNamespace

        from tokenpoc.providers.copilot import CopilotModelClient

        class FakeSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def send_and_wait(self, user, timeout):
                return SimpleNamespace(data=SimpleNamespace(content=content))

        class FakeSdkClient:
            async def create_session(self, **kwargs):
                for usage in usages:
                    kwargs["on_event"](SimpleNamespace(data=usage))
                return FakeSession()

        client = CopilotModelClient.__new__(CopilotModelClient)
        client.model_id = model_id
        client.timeout_seconds = 5.0
        client._client = FakeSdkClient()
        client._closed = False
        return client

    def test_maps_usage_and_effective_model(self):
        import asyncio

        from copilot.session_events import AssistantUsageData

        client = self._client_with_fake_session(
            usages=[AssistantUsageData(model="gpt-6-luna", input_tokens=11, output_tokens=7)]
        )
        resp = asyncio.run(client._complete_async(system="sys", user="usr", max_tokens=256))
        assert resp.input_tokens == 11 and resp.output_tokens == 7
        assert resp.text == "hello"
        assert resp.model_id == "gpt-6-luna"
        assert resp.provider == "github-copilot"

    def test_missing_usage_fails_instead_of_estimating(self):
        import asyncio

        from tokenpoc.providers.copilot import CopilotUsageMissing

        client = self._client_with_fake_session(usages=[])
        with pytest.raises(CopilotUsageMissing):
            asyncio.run(client._complete_async(system="s", user="u", max_tokens=10))

    def test_explicit_model_substitution_fails_closed(self):
        import asyncio

        from copilot.session_events import AssistantUsageData
        from tokenpoc.providers.copilot import CopilotModelError

        client = self._client_with_fake_session(
            usages=[AssistantUsageData(model="gpt-6-luna", input_tokens=1, output_tokens=1)],
            model_id="copilot-test-model",
        )
        with pytest.raises(CopilotModelError, match="silently substituted"):
            asyncio.run(client._complete_async(system="s", user="u", max_tokens=10))


class TestLiveJevAdapter:
    def test_parses_documented_response_shape(self, monkeypatch):
        """Adapter maps the documented house envelope {code,message,data} →
        typed answers + usage + model version (Stage 6 contract, jevstation.com/docs)."""
        from tokenpoc.providers import jev as jev_mod

        body = {
            "code": 0,
            "message": "ok",
            "data": {
                "model": "jev-1.12",
                "answers": {
                    "q_intent": {"type": "choice", "choice": "BILLING_DISPUTE",
                                 "probabilities": {"BILLING_DISPUTE": 0.9, "GENERAL_INQUIRY": 0.1},
                                 "confidence": 0.88},
                    "q_priority": {"type": "score", "score": 2.1,
                                   "legend": {"0": "LOW", "1": "MEDIUM", "2": "HIGH", "3": "URGENT"},
                                   "probabilities": {"HIGH": 0.8, "URGENT": 0.2},
                                   "confidence": 0.75},
                    "q_escalate": {"type": "noul", "noul": 0.91},
                    "q_strategy": {"type": "choice", "choice": "CUSTOM_REPLY",
                                   "probabilities": {"CUSTOM_REPLY": 0.85, "TEMPLATE_REPLY": 0.15},
                                   "confidence": 0.78},
                },
                "usage": {"input_tokens": 212, "output_tokens": 9},
                "credits": {"charged": 1, "remaining": 4996},
                "latency_ms": 180,
            },
        }

        class FakeHTTPResponse:
            def read(self):
                return json.dumps(body).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(jev_mod.urllib.request, "urlopen",
                            lambda req, timeout: FakeHTTPResponse())
        provider = jev_mod.JevProvider(api_key="test-key")
        resp = provider.evaluate({"subject": "s", "body": "b"}, load_jev_questions())
        assert resp.provider == "jev"
        assert resp.model == "jev-1.12"  # docs: log the model version per decision
        assert resp.answers["q_intent"].choice == "BILLING_DISPUTE"
        assert resp.answers["q_priority"].score == 2.1
        assert resp.answers["q_priority"].legend["3"] == "URGENT"
        assert resp.answers["q_escalate"].noul == 0.91
        assert resp.usage.input_tokens == 212 and resp.usage.output_tokens == 9

    def test_request_payload_matches_documented_shape(self, monkeypatch):
        """Serialized questions carry type + instructions (+ criteria for choice/score)."""
        from tokenpoc.providers import jev as jev_mod

        captured = {}

        def fake_urlopen(req, timeout):
            captured["payload"] = json.loads(req.data.decode("utf-8"))
            captured["auth"] = req.headers.get("Authorization")
            raise urllib_error_for_test()

        import urllib.error

        def urllib_error_for_test():
            return urllib.error.HTTPError("u", 400, "bad", {}, None)

        monkeypatch.setattr(jev_mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(jev_mod.JevError, match="400"):
            jev_mod.JevProvider(api_key="k").evaluate("some state", load_jev_questions())
        p = captured["payload"]
        assert captured["auth"] == "Bearer k"
        assert p["state"] == "some state"
        qi = p["questions"]["q_intent"]
        assert qi["type"] == "choice" and qi["instructions"] and isinstance(qi["criteria"], dict)
        qp = p["questions"]["q_priority"]
        assert qp["type"] == "score" and qp["criteria"] == ["LOW", "MEDIUM", "HIGH", "URGENT"]
        qe = p["questions"]["q_escalate"]
        assert qe["type"] == "noul" and "criteria" not in qe

    def test_error_envelope_raises(self, monkeypatch):
        from tokenpoc.providers import jev as jev_mod

        class FakeHTTPResponse:
            def read(self):
                return json.dumps({"code": -1, "message": "evaluation failed"}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(jev_mod.urllib.request, "urlopen",
                            lambda req, timeout: FakeHTTPResponse())
        with pytest.raises(jev_mod.JevError, match="evaluation failed"):
            jev_mod.JevProvider(api_key="k").evaluate("s", load_jev_questions())

    def test_non_retryable_402_fails_fast(self, monkeypatch):
        import urllib.error

        from tokenpoc.providers import jev as jev_mod

        calls = {"n": 0}

        def fake_urlopen(req, timeout):
            calls["n"] += 1
            raise urllib.error.HTTPError("u", 402, "payment required", {}, None)

        monkeypatch.setattr(jev_mod.urllib.request, "urlopen", fake_urlopen)
        with pytest.raises(jev_mod.JevError, match="credits"):
            jev_mod.JevProvider(api_key="k").evaluate("s", load_jev_questions())
        assert calls["n"] == 1  # no retries on 402

    def test_client_side_limit_validation(self):
        from tokenpoc.models import ChoiceQ
        from tokenpoc.providers.jev import JevError, JevProvider

        p = JevProvider(api_key="k")
        with pytest.raises(JevError, match="state too large"):
            p.evaluate("x" * 24_001, load_jev_questions())
        with pytest.raises(JevError, match="2–12 options"):
            p.evaluate("s", {"q": ChoiceQ(instructions="pick", criteria={"only": "one"})})

    def test_missing_usage_raises(self, monkeypatch):
        from tokenpoc.providers import jev as jev_mod

        class FakeHTTPResponse:
            def read(self):
                return json.dumps({"code": 0, "data": {"answers": {}}}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False

        monkeypatch.setattr(jev_mod.urllib.request, "urlopen",
                            lambda req, timeout: FakeHTTPResponse())
        with pytest.raises(jev_mod.JevError, match="usage"):
            jev_mod.JevProvider(api_key="k").evaluate("state", load_jev_questions())

    def test_empty_api_key_rejected(self):
        from tokenpoc.providers.jev import JevError, JevProvider

        with pytest.raises(JevError):
            JevProvider(api_key="")

    def test_cli_does_not_claim_key_ok_when_preflight_is_unsupported(self, monkeypatch):
        """HTTP 405 means the endpoint cannot validate keys; it is not proof that
        the configured key is valid."""
        from tokenpoc import cli as cli_mod
        from tokenpoc.config import Settings

        class FakeProvider:
            endpoint = "https://api.typesafe.ai/v1/systemone"

            def __init__(self, api_key):
                assert api_key == "test-key"

            def check_key(self):
                return {"preflight": "unsupported on this endpoint"}

        messages = []

        class FakeConsole:
            def print(self, message):
                messages.append(str(message))

        monkeypatch.setattr(cli_mod, "JevProvider", FakeProvider)
        monkeypatch.setattr(cli_mod, "console", FakeConsole())

        provider, mode = cli_mod._decision_provider(
            Settings(jev_api_key="test-key"), "live"
        )

        assert isinstance(provider, FakeProvider)
        assert mode == "live"
        output = "\n".join(messages)
        assert "preflight unavailable" in output.lower()
        assert "key OK" not in output


class TestReportWatermark:
    def _comparison(self, jev_mode):
        from tokenpoc.metrics import compare
        from tests.test_metrics import GOLD, _call, _result

        v1 = [_result("V1", "T-1", calls=[_call("V1", "T-1", "TRIAGE", 500, 50)])]
        v2 = [_result("V2", "T-1")]
        return compare(v1, v2, GOLD, jev_mode)

    def _summaries(self, jev_mode):
        from tests.test_metrics import _summary

        return _summary(), _summary(run_id="r2", version="V2", jev_mode=jev_mode,
                                    gate_intent=0.50, gate_strategy=0.60,
                                    gate_escalate_band=0.15)

    def _render(self, jev_mode):
        buf = io.StringIO()
        console = Console(file=buf, width=130, no_color=True)
        b, o = self._summaries(jev_mode)
        render_comparison(self._comparison(jev_mode), b, o, console)
        return buf.getvalue()

    def test_mock_mode_watermark_and_mock_routed_suffix(self):
        out = self._render("mock")
        flat = " ".join(out.split())  # rich wraps lines; compare whitespace-normalized
        assert "token MEASUREMENTS valid" in flat
        assert "NOT representative of live Jev" in flat
        # suffix on measured Tokens Saved and Token Reduction; Copilot USD cost is N/A.
        assert out.count("(mock-routed)") >= 2
        assert "Net Cost Delta: N/A" in out
        assert "jev: MOCK*" in out
        # §13: gate verdict watermarked in mock mode
        assert "(mock — apparatus check only)" in flat

    def test_live_mode_has_no_watermark(self):
        out = self._render("live")
        assert "mock-routed" not in out
        assert MOCK_WATERMARK not in out
        assert "jev: LIVE" in out
        assert "apparatus check only" not in out

    def test_report_prints_cost_section_and_pricing_footer(self):
        out = self._render("mock")
        flat = " ".join(out.split())
        assert "Jev Cost" in flat
        assert "Net Cost Delta" in flat
        assert "$0.042/1M in" in flat  # pricing as-of footer (§10)
        assert "jev-1.12, 2026-09" in flat

    def test_report_prints_jev_calls_and_decisions_rows(self):
        out = self._render("mock")
        assert "Jev Calls (1/ticket)" in out
        assert "Jev Decisions (4/call)" in out
        assert "Fallback firings" in out

    def test_report_prints_signed_values_and_fr14_fields(self):
        out = self._render("mock")
        assert "may be negative" in out
        assert "Tokens Saved: 550" in out
        assert "effective" in out  # effective N printed

    def test_verbose_log_formats(self):
        from tests.test_metrics import _call, _result
        from tokenpoc.models import JevCallRecord

        jev_call = JevCallRecord(
            run_id="r", ticket_id="T-018",
            answers=confident_answers(intent="PASSWORD_RESET", strategy="TEMPLATE_REPLY",
                                      noul=0.08, score=0.9),
            gates_fired=[], input_tokens=120, output_tokens=4,
            latency_ms=1.0, provider="mock")
        buf = io.StringIO()
        console = Console(file=buf, width=130, no_color=True)
        render_verbose_request(
            _result("V2", "T-018", priority="LOW", jev_calls=[jev_call]), console)
        render_verbose_request(
            _result("V2", "T-019", strategy="CUSTOM_REPLY",
                    calls=[_call("V2", "T-019", "REPLY", 300, 200)]), console)
        out = buf.getvalue()
        # §12 verbose template: typed answers from the single Jev call
        assert "intent=PASSWORD_RESET" in out
        assert "noul(escalate)=0.08" in out
        assert "priority score 0.9→LOW" in out
        assert "1 call, 4 decisions, jev tokens: 120/4" in out
        assert "Copilot model invoked: No" in out and "model tokens: 0" in out
        assert "Copilot model invoked: Yes" in out and "Input: 300" in out and "Output: 200" in out
