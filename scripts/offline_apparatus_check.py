"""Offline apparatus verification (SPEC §18 Stage 5 shape, frontier-model seam faked).

Runs the FULL 100-ticket dataset through both pipelines with MockDecisionProvider
and a deterministic FakeModelClient, then renders the real §12 report.
Token figures here verify the APPARATUS only — they are fake-client numbers,
not experimental results (and are watermarked mock-routed by the renderer).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.conftest import FakeModelClient
from tokenpoc.metrics import compare
from tokenpoc.pipeline_v1 import process_ticket_v1
from tokenpoc.pipeline_v2 import process_ticket_v2
from tokenpoc.providers.mock_jev import MockDecisionProvider
from tokenpoc.report import render_comparison, render_verbose_request
from tokenpoc.routing import OrderStore
from tokenpoc.runner import execute_run, load_tickets

tickets = load_tickets()
store = OrderStore()
client = FakeModelClient()
provider = MockDecisionProvider()

v1_results, v1_summary, v1_dir = execute_run(
    "V1", tickets, lambda t, rid: process_ticket_v1(t, client, store, rid),
    model_id="test-model-1")
v2_results, v2_summary, v2_dir = execute_run(
    "V2", tickets, lambda t, rid: process_ticket_v2(t, provider, client, store, rid),
    model_id="test-model-1", jev_mode="mock",
    gate_intent=0.50, gate_strategy=0.60, gate_escalate_band=0.15)

gold_by_id = {t.id: t.gold.model_dump() for t in tickets}
comparison = compare(v1_results, v2_results, gold_by_id, "mock")
render_comparison(comparison, v1_summary, v2_summary)

print("\n--- sample verbose logs (FR-11) ---")
for r in v2_results[:2] + [next(r for r in v2_results if r.strategy == "CUSTOM_REPLY")]:
    render_verbose_request(r)
print(f"artifacts: {v1_dir}\n           {v2_dir}")
