"""Typer CLI — `python -m tokenpoc <command>` (SPEC §11).

Commands: run baseline | run optimized | run comparison, report, validate-dataset.
Exit codes: 0 success, 1 run error, 2 config/comparison-compatibility error.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from . import config
from .config import (
    DATASET_FILE,
    DEFAULT_GATE_ESCALATE_BAND,
    DEFAULT_GATE_INTENT,
    DEFAULT_GATE_STRATEGY,
    EXIT_CONFIG_OR_COMPAT,
    EXIT_RUN_ERROR,
    RESULTS_DIR,
    Settings,
)
from .metrics import CompatibilityError, compare, confusion_matrix, reconcile_error_union
from .models import Ticket
from .pipeline_v1 import process_ticket_v1
from .pipeline_v2 import process_ticket_v2
from .providers.jev import JevError, JevProvider
from .providers.mock_jev import MockDecisionProvider
from .report import render_comparison, render_run_summary, render_verbose_request
from .routing import OrderStore
from .runner import execute_run, load_run, load_tickets

app = typer.Typer(no_args_is_help=True, add_completion=False)
run_app = typer.Typer(no_args_is_help=True)
app.add_typer(run_app, name="run")
console = Console()


def _model_client(settings: Settings):
    if settings.model_provider != "github-copilot":
        console.print(
            f"[red]Unsupported MODEL_PROVIDER {settings.model_provider!r}; "
            "expected 'github-copilot'.[/red]"
        )
        raise typer.Exit(EXIT_CONFIG_OR_COMPAT)
    from .providers.copilot import CopilotModelClient, CopilotModelError

    try:
        client = CopilotModelClient(settings.model_id)
    except CopilotModelError as exc:
        console.print(f"[red]Copilot initialization failed: {exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_OR_COMPAT)
    console.print(
        f"[green]GitHub Copilot ready[/green] — requested model: {settings.model_id}; "
        f"available: {', '.join(sorted(client.available_model_ids))}"
    )
    return client


def _decision_provider(settings: Settings, jev_mode: str):
    if jev_mode == "live":
        try:
            provider = JevProvider(settings.jev_api_key)
            # Free preflight (GET /v1/systemone): validates the key and shows
            # remaining credits BEFORE any ticket spends an evaluation.
            info = provider.check_key()
            if "preflight" in info:
                console.print(
                    "[yellow]Jev preflight unavailable on this endpoint; "
                    f"the API key has not been validated: {provider.endpoint}. "
                    "The first evaluation will validate it.[/yellow]"
                )
            else:
                credits_info = info.get("credits", info.get("remaining", "?"))
                credits = (
                    credits_info.get("remaining", credits_info.get("balance", "?"))
                    if isinstance(credits_info, dict)
                    else credits_info
                )
                console.print(
                    f"[green]Jev key OK[/green] — endpoint: {provider.endpoint}; credits: {credits}"
                )
            return provider, "live"
        except JevError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(EXIT_CONFIG_OR_COMPAT)
    return MockDecisionProvider(), "mock"


@run_app.command("baseline")
def run_baseline(
    limit: Optional[int] = typer.Option(None, "--limit"),
    verbose: bool = typer.Option(False, "--verbose"),
):
    """Execute V1 (Copilot frontier-model only) over the dataset."""
    settings = Settings.load()
    client = _model_client(settings)
    tickets = load_tickets(limit=limit)
    store = OrderStore()
    results, summary, run_dir = execute_run(
        "V1",
        tickets,
        lambda t, rid: process_ticket_v1(t, client, store, rid),
        model_id=settings.model_id,
        model_provider=settings.model_provider,
        limit=limit,
        verbose_fn=(lambda r: render_verbose_request(r, console)) if verbose else None,
    )
    client.close()
    render_run_summary(summary, console)
    console.print(f"artifacts: {run_dir}")
    if summary.error_ticket_ids:
        raise typer.Exit(EXIT_RUN_ERROR)


@run_app.command("optimized")
def run_optimized(
    limit: Optional[int] = typer.Option(None, "--limit"),
    verbose: bool = typer.Option(False, "--verbose"),
    jev_mode: str = typer.Option(None, "--jev-mode", help="live|mock"),
    gate_intent: float = typer.Option(DEFAULT_GATE_INTENT, "--gate-intent",
                                      help="q_intent Choice derived-confidence gate"),
    gate_strategy: float = typer.Option(DEFAULT_GATE_STRATEGY, "--gate-strategy",
                                        help="q_strategy Choice derived-confidence gate"),
    gate_escalate_band: float = typer.Option(DEFAULT_GATE_ESCALATE_BAND, "--gate-escalate-band",
                                             help="q_escalate Noul |p-0.5| unsure band"),
):
    """Execute V2 (Jev + Copilot frontier model) over the dataset."""
    settings = Settings.load()
    mode = jev_mode or settings.jev_mode
    if mode not in ("live", "mock"):
        console.print(f"[red]Invalid --jev-mode {mode!r}; expected live|mock.[/red]")
        raise typer.Exit(EXIT_CONFIG_OR_COMPAT)
    provider, mode = _decision_provider(settings, mode)
    client = _model_client(settings)
    tickets = load_tickets(limit=limit)
    store = OrderStore()
    results, summary, run_dir = execute_run(
        "V2",
        tickets,
        lambda t, rid: process_ticket_v2(
            t, provider, client, store, rid, gate_intent, gate_strategy, gate_escalate_band
        ),
        model_id=settings.model_id,
        model_provider=settings.model_provider,
        limit=limit,
        jev_mode=mode,
        gate_intent=gate_intent,
        gate_strategy=gate_strategy,
        gate_escalate_band=gate_escalate_band,
        verbose_fn=(lambda r: render_verbose_request(r, console)) if verbose else None,
    )
    client.close()
    render_run_summary(summary, console)
    console.print(f"artifacts: {run_dir}")
    if summary.error_ticket_ids:
        raise typer.Exit(EXIT_RUN_ERROR)


@run_app.command("comparison")
def run_comparison(
    baseline: Optional[str] = typer.Option(None, "--baseline", help="prior V1 run_id"),
    optimized: Optional[str] = typer.Option(None, "--optimized", help="prior V2 run_id"),
    limit: Optional[int] = typer.Option(None, "--limit"),
    jev_mode: str = typer.Option(None, "--jev-mode"),
    gate_intent: float = typer.Option(DEFAULT_GATE_INTENT, "--gate-intent"),
    gate_strategy: float = typer.Option(DEFAULT_GATE_STRATEGY, "--gate-strategy"),
    gate_escalate_band: float = typer.Option(DEFAULT_GATE_ESCALATE_BAND, "--gate-escalate-band"),
):
    """Default: execute both fresh, then compare; or compare two prior artifacts.
    Enforces FR-15 compatibility guard and FR-14 error-union reconciliation."""
    settings = Settings.load()
    if (baseline is None) != (optimized is None):
        console.print("[red]Provide both --baseline and --optimized, or neither.[/red]")
        raise typer.Exit(EXIT_CONFIG_OR_COMPAT)

    if baseline and optimized:
        v1_results, v1_summary = load_run(baseline)
        v2_results, v2_summary = load_run(optimized)
    else:
        client = _model_client(settings)
        mode = jev_mode or settings.jev_mode
        provider, mode = _decision_provider(settings, mode)
        tickets = load_tickets(limit=limit)
        store = OrderStore()
        v1_results, v1_summary, _ = execute_run(
            "V1",
            tickets,
            lambda t, rid: process_ticket_v1(t, client, store, rid),
            model_id=settings.model_id,
            model_provider=settings.model_provider,
            limit=limit,
        )
        v2_results, v2_summary, _ = execute_run(
            "V2",
            tickets,
            lambda t, rid: process_ticket_v2(
                t, provider, client, store, rid, gate_intent, gate_strategy, gate_escalate_band
            ),
            model_id=settings.model_id,
            model_provider=settings.model_provider,
            limit=limit,
            jev_mode=mode,
            gate_intent=gate_intent,
            gate_strategy=gate_strategy,
            gate_escalate_band=gate_escalate_band,
        )
        client.close()

    # FR-15 guard BEFORE any math; abort exit 2 printing differing fields
    from .metrics import check_compatibility

    try:
        check_compatibility(v1_summary, v2_summary)
    except CompatibilityError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_CONFIG_OR_COMPAT)

    tickets_all = load_tickets()
    gold_by_id = {t.id: t.gold.model_dump() for t in tickets_all}
    comparison = compare(v1_results, v2_results, gold_by_id, v2_summary.jev_mode or "-")
    render_comparison(comparison, v1_summary, v2_summary, console)

    include_ids, _ = reconcile_error_union(v1_results, v2_results)
    comparison_path = RESULTS_DIR / f"comparison-{v1_summary.run_id}-vs-{v2_summary.run_id}.json"
    comparison_path.write_text(
        json.dumps(
            {
                "baseline_run": v1_summary.run_id,
                "optimized_run": v2_summary.run_id,
                "jev_mode": comparison.jev_mode,
                "effective_n": comparison.effective_n,
                "excluded_ticket_ids": comparison.excluded_ticket_ids,
                "baseline": vars(comparison.baseline),
                "optimized": vars(comparison.optimized),
                "tokens_saved": comparison.tokens_saved,
                "reduction_pct": comparison.reduction_pct,
                "jev_tokens": {
                    "input": comparison.optimized.jev_input_tokens,
                    "output": comparison.optimized.jev_output_tokens,
                },
                "cost": {
                    "jev_cost": comparison.optimized.jev_cost,
                    "copilot_generation_cost_v1": None,
                    "copilot_generation_cost_v2": None,
                    "net_cost_delta": comparison.net_cost_delta,
                    "note": "Copilot subscription/prompt-accounted; token-based USD cost N/A",
                },
                "accuracy": comparison.accuracy,
                "agreement_pct": comparison.agreement_pct,
                "disagreements": comparison.disagreements,
                "completion": comparison.completion,
                "quality_gate": comparison.quality_gate,
                "confusion_matrices": {
                    version: {
                        op: confusion_matrix(res, gold_by_id, op, include_ids)
                        for op in ("category", "priority", "escalate", "strategy")
                    }
                    for version, res in (("V1", v1_results), ("V2", v2_results))
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"comparison artifact: {comparison_path}")


@app.command("report")
def report(run_id: str):
    """Re-print a stored run's summary."""
    try:
        _, summary = load_run(run_id)
    except FileNotFoundError:
        console.print(f"[red]No run artifacts found for {run_id!r} under {RESULTS_DIR}[/red]")
        raise typer.Exit(EXIT_RUN_ERROR)
    render_run_summary(summary, console)


@app.command("validate-dataset")
def validate_dataset(path: Path = typer.Option(DATASET_FILE, "--path")):
    """Schema-check tickets.jsonl + gold-label completeness (SPEC §11)."""
    errors = []
    tickets = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                tickets.append(Ticket.model_validate_json(line))
            except Exception as exc:
                errors.append(f"line {i}: {exc}")
    ids = [t.id for t in tickets]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        errors.append(f"duplicate ticket ids: {sorted(dupes)}")
    if errors:
        console.print(f"[red]Dataset INVALID ({len(errors)} problems):[/red]")
        for e in errors:
            console.print(f"  {e}")
        raise typer.Exit(EXIT_RUN_ERROR)
    from collections import Counter

    strat = Counter(t.gold.strategy for t in tickets)
    cat = Counter(t.gold.category for t in tickets)
    console.print(f"[green]Dataset VALID[/green]: {len(tickets)} tickets, all gold labels complete.")
    console.print(f"  strategy mix: {dict(strat)}")
    console.print(f"  category mix: {dict(cat)}")


if __name__ == "__main__":
    app()
