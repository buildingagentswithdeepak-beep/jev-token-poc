"""Integration: full run over the frozen dataset with BOTH AI providers mocked
(SPEC §16 testing row), artifact round-trip, and comparison end-to-end."""
from __future__ import annotations

import json
from collections import Counter

import pytest

from tests.conftest import FakeModelClient
from tokenpoc.config import DATASET_FILE
from tokenpoc.metrics import compare
from tokenpoc.pipeline_v1 import process_ticket_v1
from tokenpoc.pipeline_v2 import process_ticket_v2
from tokenpoc.providers.mock_jev import MockDecisionProvider
from tokenpoc.routing import OrderStore
from tokenpoc.runner import execute_run, load_run, load_tickets


@pytest.fixture(scope="module")
def tickets():
    return load_tickets(limit=20)


@pytest.fixture(scope="module")
def store():
    return OrderStore()


class TestDataset:
    def test_frozen_dataset_validates_and_matches_composition(self):
        all_tickets = load_tickets()
        assert len(all_tickets) == 100
        strat = Counter(t.gold.strategy for t in all_tickets)
        # §9 composition: 30 template + 20 auto-resolve + (25+15+10 custom-ish)=50
        assert strat["TEMPLATE_REPLY"] == 30
        assert strat["AUTO_RESOLVE"] == 20
        assert strat["CUSTOM_REPLY"] == 50
        assert len({t.id for t in all_tickets}) == 100  # unique ids
        for t in all_tickets:
            if t.gold.escalate:
                assert t.gold.queue  # gold-label completeness

    def test_order_fixture_covers_all_auto_resolve_tickets(self, store):
        for t in load_tickets():
            if t.gold.strategy == "AUTO_RESOLVE":
                assert store.lookup(t.id) is not None


class TestEndToEnd:
    def test_full_mock_comparison_round_trip(self, tickets, store, tmp_path, monkeypatch):
        import tokenpoc.runner as runner_mod

        monkeypatch.setattr(runner_mod, "RESULTS_DIR", tmp_path)
        client = FakeModelClient()
        provider = MockDecisionProvider()

        v1_results, v1_summary, v1_dir = execute_run(
            "V1", tickets, lambda t, rid: process_ticket_v1(t, client, store, rid),
            model_id="test-model-1", limit=20)
        v2_results, v2_summary, v2_dir = execute_run(
            "V2", tickets,
            lambda t, rid: process_ticket_v2(t, provider, client, store, rid),
            model_id="test-model-1", limit=20, jev_mode="mock",
            gate_intent=0.50, gate_strategy=0.60, gate_escalate_band=0.15)

        # artifacts exist and round-trip (AC-2 raw per-call logs verifiable)
        for d in (v1_dir, v2_dir):
            assert (d / "requests.jsonl").exists()
            assert (d / "summary.json").exists()
        loaded_results, loaded_summary = load_run(v1_summary.run_id)
        assert len(loaded_results) == 20
        assert loaded_summary.model_total_tokens == v1_summary.model_total_tokens
        # FR-15 fields and provider-neutral telemetry names persisted in summary.json
        raw = json.loads((v1_dir / "summary.json").read_text(encoding="utf-8"))
        for field in ("dataset_hash", "model_id", "prompt_hashes", "ticket_ids"):
            assert field in raw
        for field in ("model_calls", "model_input_tokens", "model_output_tokens", "model_total_tokens"):
            assert field in raw
        assert not any(key.startswith("claude_") for key in raw)
        first_request = json.loads(
            (v1_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        assert "model_calls" in first_request
        assert "claude_calls" not in first_request

        # Existing pre-migration artifacts remain readable through input-only aliases;
        # re-serialization always emits the provider-neutral schema.
        legacy_summary = dict(raw)
        legacy_summary["claude_calls"] = legacy_summary.pop("model_calls")
        legacy_summary["claude_input_tokens"] = legacy_summary.pop("model_input_tokens")
        legacy_summary["claude_output_tokens"] = legacy_summary.pop("model_output_tokens")
        legacy_summary["claude_total_tokens"] = legacy_summary.pop("model_total_tokens")
        from tokenpoc.models import RunSummary, TicketResult

        migrated_summary = RunSummary.model_validate(legacy_summary)
        migrated_summary_raw = migrated_summary.model_dump()
        assert migrated_summary_raw["model_total_tokens"] == v1_summary.model_total_tokens
        assert "claude_total_tokens" not in migrated_summary_raw

        legacy_request = dict(first_request)
        legacy_request["claude_calls"] = legacy_request.pop("model_calls")
        migrated_request = TicketResult.model_validate(legacy_request)
        assert migrated_request.model_calls
        assert "claude_calls" not in migrated_request.model_dump()

        # V1: every ticket gets a triage call (AC-5 totals computed per version)
        assert v1_summary.triage_calls == 20
        assert v1_summary.model_total_tokens > 0
        # V2: ONE Jev call per ticket, 4 logical decisions per call (§6/§10)
        assert v2_summary.jev_calls == 20
        assert v2_summary.jev_decisions == 80
        assert v2_summary.triage_calls == 0
        assert v2_summary.reply_calls < 20  # some tickets resolved with 0 Copilot model tokens

        gold_by_id = {t.id: t.gold.model_dump() for t in tickets}
        c = compare(v1_results, v2_results, gold_by_id, "mock")
        assert c.effective_n == 20
        assert c.baseline.total_tokens == v1_summary.model_total_tokens
        # signed savings — direction not asserted (AC-10); only arithmetic is
        assert c.tokens_saved == c.baseline.total_tokens - c.optimized.total_tokens
        if c.baseline.total_tokens:
            assert c.reduction_pct == pytest.approx(
                100.0 * c.tokens_saved / c.baseline.total_tokens)
        # quality fields all present
        for v in ("V1", "V2"):
            for op in ("category", "priority", "escalate", "strategy"):
                assert 0.0 <= c.accuracy[v][op] <= 100.0
        assert 0.0 <= c.agreement_pct <= 100.0
