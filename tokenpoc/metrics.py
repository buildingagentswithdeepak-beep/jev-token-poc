"""Aggregation, savings & cost math, FR-14/FR-15 guards, quality scoring
(SPEC §10, §13, FR-14/15).

Token math is the experiment — every figure is computed from measured records,
signed, with no floor at zero and no directional assumption (AC-10). Jev usage
is measured per call and priced at configured rates (AC-11); pricing constants
carry as-of dates and change cost lines, never token lines.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import (
    GENERATION_PRICE_PER_MTOK_INPUT,
    GENERATION_PRICE_PER_MTOK_OUTPUT,
    JEV_PRICE_PER_MTOK_INPUT,
    JEV_PRICE_PER_MTOK_OUTPUT,
)
from .models import RunSummary, TicketResult

OPERATIONS = ("category", "priority", "escalate", "strategy")


class CompatibilityError(Exception):
    """FR-15: raised when two run artifacts are not comparable. CLI maps to exit 2."""

    def __init__(self, mismatches: dict[str, tuple]):
        self.mismatches = mismatches
        lines = "\n".join(f"  {k}: baseline={a!r} optimized={b!r}" for k, (a, b) in mismatches.items())
        super().__init__(f"Run artifacts are not comparable (FR-15):\n{lines}")


def check_compatibility(baseline: RunSummary, optimized: RunSummary) -> None:
    """Assert dataset hash, model id, shared prompt hashes (at minimum the O5
    reply prompt), and ticket-id set all match. Any mismatch aborts (FR-15)."""
    mismatches: dict[str, tuple] = {}
    if baseline.dataset_hash != optimized.dataset_hash:
        mismatches["dataset_hash"] = (baseline.dataset_hash, optimized.dataset_hash)
    if baseline.model_id != optimized.model_id:
        mismatches["model_id"] = (baseline.model_id, optimized.model_id)
    if baseline.model_provider != optimized.model_provider:
        mismatches["model_provider"] = (baseline.model_provider, optimized.model_provider)
    # With `auto`, compare observed effective models when both runs actually made
    # model calls. A zero-call optimized run has no effective model to observe.
    if (
        baseline.effective_model_ids
        and optimized.effective_model_ids
        and set(baseline.effective_model_ids) != set(optimized.effective_model_ids)
    ):
        mismatches["effective_model_ids"] = (
            sorted(baseline.effective_model_ids), sorted(optimized.effective_model_ids)
        )
    b_reply = baseline.prompt_hashes.get("reply_system")
    o_reply = optimized.prompt_hashes.get("reply_system")
    if b_reply != o_reply or b_reply is None:
        mismatches["prompt_hash:reply_system"] = (b_reply, o_reply)
    if set(baseline.ticket_ids) != set(optimized.ticket_ids):
        mismatches["ticket_id_set"] = (sorted(baseline.ticket_ids), sorted(optimized.ticket_ids))
    if mismatches:
        raise CompatibilityError(mismatches)


@dataclass
class VersionAggregate:
    requests: int = 0
    model_calls: int = 0
    triage_calls: int = 0
    reply_calls: int = 0
    repair_retries: int = 0
    jev_calls: int = 0  # API invocations (1 per ticket in V2)
    jev_decisions: int = 0  # logical question results (4 per call)
    fallback_intent: int = 0
    fallback_strategy: int = 0
    fallback_escalate: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    jev_input_tokens: int = 0
    jev_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def jev_total_tokens(self) -> int:
        return self.jev_input_tokens + self.jev_output_tokens

    @property
    def fallback_count(self) -> int:
        """Routing fallbacks (intent + strategy gates); the escalate gate changes
        escalation, not routing, and is reported in its own column."""
        return self.fallback_intent + self.fallback_strategy

    # --- cost lines (§10: measured tokens × configured rates) ---

    @property
    def jev_cost(self) -> float:
        return (
            self.jev_input_tokens * JEV_PRICE_PER_MTOK_INPUT
            + self.jev_output_tokens * JEV_PRICE_PER_MTOK_OUTPUT
        ) / 1_000_000.0

    @property
    def generation_cost(self) -> float | None:
        if (
            GENERATION_PRICE_PER_MTOK_INPUT is None
            or GENERATION_PRICE_PER_MTOK_OUTPUT is None
        ):
            return None
        return (
            self.input_tokens * GENERATION_PRICE_PER_MTOK_INPUT
            + self.output_tokens * GENERATION_PRICE_PER_MTOK_OUTPUT
        ) / 1_000_000.0

    @property
    def total_cost(self) -> float | None:
        generation = self.generation_cost
        return None if generation is None else generation + self.jev_cost


def aggregate(results: list[TicketResult], include_ids: set[str] | None = None) -> VersionAggregate:
    """Compute run-level aggregates (§10) over results, optionally restricted to
    `include_ids` (the FR-14 intersection of successful tickets)."""
    agg = VersionAggregate()
    for r in results:
        if include_ids is not None and r.ticket_id not in include_ids:
            continue
        agg.requests += 1
        agg.fallback_intent += 1 if "intent" in r.gates_fired else 0
        agg.fallback_strategy += 1 if "strategy" in r.gates_fired else 0
        agg.fallback_escalate += 1 if "escalate" in r.gates_fired else 0
        agg.repair_retries += r.repair_retries
        for j in r.jev_calls:
            agg.jev_calls += 1
            agg.jev_decisions += j.decision_count
            agg.jev_input_tokens += j.input_tokens
            agg.jev_output_tokens += j.output_tokens
        for c in r.model_calls:
            agg.model_calls += 1
            agg.input_tokens += c.input_tokens
            agg.output_tokens += c.output_tokens
            if c.call_role == "TRIAGE":
                agg.triage_calls += 1
            elif c.call_role == "REPLY":
                agg.reply_calls += 1
            # REPAIR calls counted in model_calls + repair_retries field
    return agg


@dataclass
class Comparison:
    baseline: VersionAggregate
    optimized: VersionAggregate
    excluded_ticket_ids: list[str]
    effective_n: int
    tokens_saved: int  # SIGNED — may be negative (AC-6, AC-10)
    reduction_pct: float  # SIGNED (AC-7)
    net_cost_delta: float | None  # N/A for Copilot subscription accounting
    accuracy: dict  # {version: {operation: pct}}
    agreement_pct: float
    disagreements: list[dict]
    completion: dict  # {version: pct}
    quality_gate: dict  # verdict + inputs
    jev_mode: str  # "live" | "mock" | "-"


def reconcile_error_union(
    v1_results: list[TicketResult], v2_results: list[TicketResult]
) -> tuple[set[str], list[str]]:
    """FR-14: excluded set = UNION of ERROR ticket_ids from both runs;
    aggregates are recomputed over the INTERSECTION of successful tickets."""
    v1_err = {r.ticket_id for r in v1_results if r.status == "ERROR"}
    v2_err = {r.ticket_id for r in v2_results if r.status == "ERROR"}
    excluded = sorted(v1_err | v2_err)
    all_ids = {r.ticket_id for r in v1_results} | {r.ticket_id for r in v2_results}
    include = {tid for tid in all_ids if tid not in set(excluded)}
    return include, excluded


def score_accuracy(
    results: list[TicketResult], gold_by_id: dict[str, dict], include_ids: set[str]
) -> dict[str, float]:
    """Per-operation accuracy vs gold labels (SPEC §13.1), over effective N."""
    counts = {op: 0 for op in OPERATIONS}
    n = 0
    for r in results:
        if r.ticket_id not in include_ids or r.status != "OK":
            continue
        gold = gold_by_id[r.ticket_id]
        n += 1
        for op in OPERATIONS:
            if getattr(r, op) == gold[op]:
                counts[op] += 1
    if n == 0:
        return {op: 0.0 for op in OPERATIONS}
    return {op: 100.0 * counts[op] / n for op in OPERATIONS}


def confusion_matrix(
    results: list[TicketResult], gold_by_id: dict[str, dict], op: str, include_ids: set[str]
) -> dict[str, dict[str, int]]:
    matrix: dict[str, dict[str, int]] = {}
    for r in results:
        if r.ticket_id not in include_ids or r.status != "OK":
            continue
        gold = str(gold_by_id[r.ticket_id][op])
        pred = str(getattr(r, op))
        matrix.setdefault(gold, {})
        matrix[gold][pred] = matrix[gold].get(pred, 0) + 1
    return matrix


def strategy_agreement(
    v1_results: list[TicketResult],
    v2_results: list[TicketResult],
    gold_by_id: dict[str, dict],
    include_ids: set[str],
) -> tuple[float, list[dict]]:
    """FR-10/§13.2: % same strategy + every disagreement with both choices and gold."""
    v1_by_id = {r.ticket_id: r for r in v1_results}
    v2_by_id = {r.ticket_id: r for r in v2_results}
    agree = 0
    n = 0
    disagreements: list[dict] = []
    for tid in sorted(include_ids):
        r1, r2 = v1_by_id.get(tid), v2_by_id.get(tid)
        if not r1 or not r2 or r1.status != "OK" or r2.status != "OK":
            continue
        n += 1
        if r1.strategy == r2.strategy:
            agree += 1
        else:
            disagreements.append(
                {
                    "ticket_id": tid,
                    "v1_strategy": r1.strategy,
                    "v2_strategy": r2.strategy,
                    "gold_strategy": gold_by_id[tid]["strategy"],
                }
            )
    return (100.0 * agree / n if n else 0.0), disagreements


def completion_rate(results: list[TicketResult], include_ids: set[str]) -> float:
    """§13.3 objective completion: valid routing record + non-empty reply with all
    template variables resolved (no unresolved {placeholders})."""
    n = 0
    ok = 0
    for r in results:
        if r.ticket_id not in include_ids:
            continue
        n += 1
        complete = (
            r.status == "OK"
            and r.reply is not None
            and r.reply.strip() != ""
            and "{" not in r.reply.replace("{}", "")
            and all(getattr(r, op) is not None for op in OPERATIONS)
        )
        ok += 1 if complete else 0
    return 100.0 * ok / n if n else 0.0


QUALITY_GATE_THRESHOLD_PTS = 5.0  # §13 pre-registered, adjustable BEFORE runs only


def quality_gate(
    v1_strategy_acc: float, v2_strategy_acc: float, v2_completion: float
) -> dict:
    """§13 pre-registered gate: V2 strategy accuracy within 5 pts of V1 AND
    completion == 100%, else the report leads with the quality regression."""
    within = (v1_strategy_acc - v2_strategy_acc) <= QUALITY_GATE_THRESHOLD_PTS
    complete = v2_completion >= 100.0
    return {
        "passed": within and complete,
        "strategy_acc_delta_pts": v1_strategy_acc - v2_strategy_acc,
        "threshold_pts": QUALITY_GATE_THRESHOLD_PTS,
        "v2_completion_pct": v2_completion,
        "verdict": (
            "achieved at acceptable quality"
            if within and complete
            else "QUALITY REGRESSION — token figures must not be quoted without this caveat"
        ),
    }


def compare(
    v1_results: list[TicketResult],
    v2_results: list[TicketResult],
    gold_by_id: dict[str, dict],
    jev_mode: str,
) -> Comparison:
    """Full FR-8/FR-14 comparison from measured artifacts only."""
    include_ids, excluded = reconcile_error_union(v1_results, v2_results)
    base = aggregate(v1_results, include_ids)
    opt = aggregate(v2_results, include_ids)
    saved = base.total_tokens - opt.total_tokens  # signed
    pct = (100.0 * saved / base.total_tokens) if base.total_tokens else 0.0
    net_cost_delta = (
        None
        if base.total_cost is None or opt.total_cost is None
        else base.total_cost - opt.total_cost
    )
    acc_v1 = score_accuracy(v1_results, gold_by_id, include_ids)
    acc_v2 = score_accuracy(v2_results, gold_by_id, include_ids)
    agreement, disagreements = strategy_agreement(v1_results, v2_results, gold_by_id, include_ids)
    comp_v1 = completion_rate(v1_results, include_ids)
    comp_v2 = completion_rate(v2_results, include_ids)
    return Comparison(
        baseline=base,
        optimized=opt,
        excluded_ticket_ids=excluded,
        effective_n=len(include_ids),
        tokens_saved=saved,
        reduction_pct=pct,
        net_cost_delta=net_cost_delta,
        accuracy={"V1": acc_v1, "V2": acc_v2},
        agreement_pct=agreement,
        disagreements=disagreements,
        completion={"V1": comp_v1, "V2": comp_v2},
        quality_gate=quality_gate(acc_v1["strategy"], acc_v2["strategy"], comp_v2),
        jev_mode=jev_mode,
    )
