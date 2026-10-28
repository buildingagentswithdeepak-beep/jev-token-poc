"""§12 report renderer (rich tables) with FR-13 mock watermarking.

Mock-mode savings AND cost figures carry the "(mock-routed)" suffix everywhere
they appear; the quality-gate verdict is suffixed "(mock — apparatus check only)"
in mock mode (§13); the watermark text is exactly the FR-13 wording; the footer
prints pricing constants with their as-of dates (§10).
"""
from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from .config import (
    GENERATION_PRICING_AS_OF,
    JEV_PRICING_AS_OF,
    JEV_PRICE_PER_MTOK_INPUT,
    JEV_PRICE_PER_MTOK_OUTPUT,
)
from .metrics import Comparison
from .models import ChoiceR, NoulR, RunSummary, ScoreR, TicketResult

MOCK_WATERMARK = (
    "JEV=MOCK — token MEASUREMENTS valid; token TOTALS/SAVINGS depend on mock routing "
    "and are NOT representative of live Jev; decision quality NOT representative of Jev"
)

BASELINE_DESIGN_NOTE = (
    "Baseline design: V1 uses ONE combined triage call (strongest sane model-only "
    "design); savings are measured against it, not a strawman (SPEC §5)."
)


def _pricing_footer() -> str:
    return (
        f"Pricing: jev ${JEV_PRICE_PER_MTOK_INPUT}/1M in, ${JEV_PRICE_PER_MTOK_OUTPUT}/1M out "
        f"({JEV_PRICING_AS_OF}); generation: {GENERATION_PRICING_AS_OF}"
    )


def render_comparison(
    comparison: Comparison,
    baseline_summary: RunSummary,
    optimized_summary: RunSummary,
    console: Console | None = None,
) -> None:
    console = console or Console()
    mock = comparison.jev_mode == "mock"
    sfx = " (mock-routed)" if mock else ""
    b, o = comparison.baseline, comparison.optimized

    console.print(
        f"\n[bold]TOKEN CONSUMPTION COMPARISON[/bold]   run: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%MZ')}"
        f"   provider: {baseline_summary.model_provider}   requested model: {baseline_summary.model_id}"
    )
    console.print(
        f"  dataset: {baseline_summary.dataset_file} ({comparison.effective_n} effective)"
        f"        jev: {'MOCK*' if mock else 'LIVE'}        effective model(s): "
        f"{', '.join(baseline_summary.effective_model_ids) or 'none'}"
    )
    if comparison.excluded_ticket_ids:
        console.print(
            f"  [yellow]excluded (ERROR union, FR-14): {', '.join(comparison.excluded_ticket_ids)}[/yellow]"
        )
    console.print("=" * 72)

    t = Table(show_header=True, header_style="bold")
    t.add_column("", min_width=38)
    t.add_column("Copilot Model Only", justify="right")
    t.add_column("Jev + Copilot Model", justify="right")
    t.add_row("Requests Processed", str(b.requests), str(o.requests))
    t.add_row("Copilot model calls", str(b.model_calls), str(o.model_calls))
    t.add_row("  └─ triage calls", str(b.triage_calls), str(o.triage_calls))
    t.add_row("  └─ reply-generation calls", str(b.reply_calls), str(o.reply_calls))
    t.add_row("  └─ JSON-repair retries", str(b.repair_retries), str(o.repair_retries))
    t.add_row("Jev Calls (1/ticket)", str(b.jev_calls), str(o.jev_calls))
    t.add_row("Jev Decisions (4/call)", str(b.jev_decisions), str(o.jev_decisions))
    t.add_row(
        "Fallback firings (intent/strategy/esc)",
        "—",
        f"{o.fallback_intent}/{o.fallback_strategy}/{o.fallback_escalate}",
    )
    t.add_row("", "", "")
    t.add_row("Copilot model input tokens", f"{b.input_tokens:,}", f"{o.input_tokens:,}")
    t.add_row("Copilot model output tokens", f"{b.output_tokens:,}", f"{o.output_tokens:,}")
    t.add_row(
        "[bold]Total Copilot model tokens[/bold]",
        f"[bold]{b.total_tokens:,}[/bold]",
        f"[bold]{o.total_tokens:,}[/bold]",
    )
    console.print(t)

    # Signed savings — sign as measured, may be negative (AC-10)
    console.print(f"\nTokens Saved: {comparison.tokens_saved:,}{sfx}")
    console.print(
        f"Token Reduction: {comparison.reduction_pct:.2f}%{sfx}   (sign as measured — may be negative)"
    )

    # COST section (§10/§12: measured Jev usage × configured rates; separate lines)
    c = Table(show_header=True, header_style="bold", title="COST (measured; pricing as-of in footer)")
    c.add_column("", min_width=38)
    c.add_column("Copilot Model Only", justify="right")
    c.add_column("Jev + Copilot Model", justify="right")
    c.add_row("Jev Tokens (in/out)", "—", f"{o.jev_input_tokens:,} / {o.jev_output_tokens:,}")
    c.add_row("Jev Cost", "—", f"${o.jev_cost:.4f}")
    c.add_row("Copilot generation cost", "N/A (subscription)", "N/A (subscription)")
    c.add_row("Total dollar cost", "N/A", "N/A")
    console.print(c)
    console.print("Net Cost Delta: N/A — Copilot is subscription/prompt-accounted, not token-priced")

    q = Table(show_header=True, header_style="bold", title="QUALITY GUARDRAIL")
    q.add_column("", min_width=38)
    q.add_column("Copilot Model Only", justify="right")
    q.add_column("Jev + Copilot Model", justify="right")
    acc = comparison.accuracy
    q.add_row("Category accuracy (vs gold)", f"{acc['V1']['category']:.1f}%", f"{acc['V2']['category']:.1f}%")
    q.add_row("Priority accuracy", f"{acc['V1']['priority']:.1f}%", f"{acc['V2']['priority']:.1f}%")
    q.add_row("Escalation accuracy †", f"{acc['V1']['escalate']:.1f}%", f"{acc['V2']['escalate']:.1f}%")
    q.add_row("Strategy accuracy †", f"{acc['V1']['strategy']:.1f}%", f"{acc['V2']['strategy']:.1f}%")
    q.add_row("Task completion", f"{comparison.completion['V1']:.1f}%", f"{comparison.completion['V2']:.1f}%")
    console.print(q)
    console.print(
        f"Strategy agreement V1↔V2: {comparison.agreement_pct:.1f}% "
        f"({len(comparison.disagreements)} disagreements)"
    )
    for d in comparison.disagreements:
        console.print(
            f"  [yellow]DISAGREEMENT[/yellow] {d['ticket_id']}: "
            f"V1={d['v1_strategy']} V2={d['v2_strategy']} gold={d['gold_strategy']}"
        )

    gate = comparison.quality_gate
    style = "green" if gate["passed"] else "red bold"
    verdict = "PASS" if gate["passed"] else "FAIL"
    # §13: mock-mode verdict validates the gate's WIRING, not Jev's quality
    gate_sfx = " (mock — apparatus check only)" if mock else ""
    console.print(f"\nQuality gate (§13): [{style}]{verdict}{gate_sfx}[/{style}] — {gate['verdict']}")
    console.print(
        f"  strategy-accuracy delta: {gate['strategy_acc_delta_pts']:.1f} pts "
        f"(threshold {gate['threshold_pts']:g}) | V2 completion: {gate['v2_completion_pct']:.1f}%"
    )

    console.print("=" * 72)
    console.print(_pricing_footer())
    console.print(
        "† In V2, escalation (Noul) and strategy (Choice) are answered in the SAME "
        "Jev call against the same state — correlated, not independent evidence."
    )
    console.print(BASELINE_DESIGN_NOTE)
    # Footer: active assumptions on every output (§14)
    console.print(
        f"Active config: jev={comparison.jev_mode}; gates intent="
        f"{optimized_summary.gate_intent} strategy={optimized_summary.gate_strategy} "
        f"escalate-band={optimized_summary.gate_escalate_band}; "
        f"temperature={baseline_summary.temperature if baseline_summary.temperature is not None else 'N/A (Copilot SDK)'}"
    )
    if mock:
        console.print(f"[red bold]* {MOCK_WATERMARK} — cost lines likewise mock-routed[/red bold]")


def _fmt_jev_line(result: TicketResult) -> list[str]:
    """§12 verbose format: per-question typed answers from the single Jev call."""
    if not result.jev_calls:
        return []
    j = result.jev_calls[0]
    parts = []
    a = j.answers
    if "q_intent" in a and isinstance(a["q_intent"], ChoiceR):
        parts.append(f"intent={a['q_intent'].choice} (conf {a['q_intent'].confidence:.2f})")
    if "q_priority" in a and isinstance(a["q_priority"], ScoreR):
        parts.append(f"priority score {a['q_priority'].score:.1f}→{result.priority}")
    if "q_escalate" in a and isinstance(a["q_escalate"], NoulR):
        parts.append(f"noul(escalate)={a['q_escalate'].noul:.2f}")
    if "q_strategy" in a and isinstance(a["q_strategy"], ChoiceR):
        parts.append(f"strategy={a['q_strategy'].choice} (conf {a['q_strategy'].confidence:.2f})")
    line1 = "  Jev: " + " · ".join(parts)
    line2 = f"       [1 call, {j.decision_count} decisions, jev tokens: {j.input_tokens}/{j.output_tokens}]"
    if j.gates_fired:
        line2 += f"  gates fired: {','.join(j.gates_fired)}"
    return [line1, line2]


def render_verbose_request(result: TicketResult, console: Console | None = None) -> None:
    """§12 per-request verbose log (FR-11)."""
    console = console or Console()
    if result.status == "ERROR":
        console.print(f"Request {result.ticket_id}\n  [red]ERROR: {result.error}[/red]\n")
        return
    console.print(f"Request {result.ticket_id}")
    if result.jev_calls:
        for line in _fmt_jev_line(result):
            console.print(line)
        if result.fallback:
            console.print("       → FALLBACK CUSTOM_REPLY (low confidence)")
    else:
        esc = f"escalate→{result.queue}" if result.escalate else "no-escalation"
        console.print(f"  Decisions: {result.category} / {result.priority} / {esc} / {result.strategy}")
    console.print(f"  Handled by: {result.handled_by}")
    if result.model_calls:
        console.print(
            f"  Copilot model invoked: Yes  Input: {result.model_input_tokens}   "
            f"Output: {result.model_output_tokens}"
        )
    else:
        console.print("  Copilot model invoked: No   model tokens: 0")
    console.print("")


def render_run_summary(summary: RunSummary, console: Console | None = None) -> None:
    console = console or Console()
    mock = summary.jev_mode == "mock"
    t = Table(title=f"Run {summary.run_id} ({summary.version})", show_header=False)
    t.add_column("field")
    t.add_column("value", justify="right")
    t.add_row("provider", summary.model_provider)
    t.add_row("requested model", summary.model_id)
    t.add_row("effective model(s)", ", ".join(summary.effective_model_ids) or "none")
    t.add_row("dataset", f"{summary.dataset_file} [{summary.dataset_hash}]")
    t.add_row("requests processed", str(summary.requests_processed))
    t.add_row("errors", str(len(summary.error_ticket_ids)))
    t.add_row("Copilot model calls", str(summary.model_calls))
    t.add_row("  triage / reply / repair", f"{summary.triage_calls} / {summary.reply_calls} / {summary.repair_retries}")
    t.add_row("Jev Calls (1/ticket)", str(summary.jev_calls))
    t.add_row("Jev Decisions (4/call)", str(summary.jev_decisions))
    t.add_row(
        "fallbacks (intent/strategy/esc)",
        f"{summary.fallback_intent} / {summary.fallback_strategy} / {summary.fallback_escalate}",
    )
    t.add_row("Jev tokens (in/out)", f"{summary.jev_input_tokens:,} / {summary.jev_output_tokens:,}")
    t.add_row("Copilot model input tokens", f"{summary.model_input_tokens:,}")
    t.add_row("Copilot model output tokens", f"{summary.model_output_tokens:,}")
    t.add_row("Total Copilot model tokens", f"{summary.model_total_tokens:,}")
    console.print(t)
    console.print(_pricing_footer())
    if mock:
        console.print(f"[red bold]{MOCK_WATERMARK}[/red bold]")
