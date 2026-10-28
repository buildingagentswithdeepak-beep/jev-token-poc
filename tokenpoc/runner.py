"""Run orchestration + artifact persistence (SPEC §8, §10, §11).

Sequential, synchronous execution (determinism and rate-limit friendliness, §4).
Writes results/<run_id>/{requests.jsonl, summary.json}.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .config import DATASET_FILE, RESULTS_DIR, TEMPERATURE
from .metrics import aggregate
from .models import RunSummary, Ticket, TicketResult
from .prompts_loader import all_prompt_hashes, file_hash, prompt_hash


def load_tickets(path: Path = DATASET_FILE, limit: Optional[int] = None) -> list[Ticket]:
    tickets = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tickets.append(Ticket.model_validate_json(line))
    return tickets[:limit] if limit else tickets


def make_run_id(version: str, jev_mode: Optional[str] = None) -> str:
    """run_id embeds timestamp + prompt hash (§14: any prompt edit invalidates runs)."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{jev_mode}" if jev_mode else ""
    return f"{version.lower()}{suffix}-{ts}-p{prompt_hash('reply_system')[:8]}"


def execute_run(
    version: str,
    tickets: list[Ticket],
    process_fn: Callable[[Ticket, str], TicketResult],
    *,
    model_id: str,
    model_provider: str = "unknown-legacy-provider",
    dataset_path: Path = DATASET_FILE,
    limit: Optional[int] = None,
    jev_mode: Optional[str] = None,
    gate_intent: Optional[float] = None,
    gate_strategy: Optional[float] = None,
    gate_escalate_band: Optional[float] = None,
    verbose_fn: Optional[Callable[[TicketResult], None]] = None,
) -> tuple[list[TicketResult], RunSummary, Path]:
    run_id = make_run_id(version, jev_mode)
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[TicketResult] = []
    with open(run_dir / "requests.jsonl", "w", encoding="utf-8") as f:
        for ticket in tickets:  # identical order, sequential (FR-1)
            result = process_fn(ticket, run_id)
            results.append(result)
            f.write(result.model_dump_json() + "\n")
            if verbose_fn:
                verbose_fn(result)

    agg = aggregate(results)  # own-run aggregates; comparison recomputes per FR-14
    effective_model_ids = sorted(
        {call.model_id for result in results for call in result.model_calls}
    )
    summary = RunSummary(
        run_id=run_id,
        version=version,  # type: ignore[arg-type]
        timestamp=datetime.now(timezone.utc).isoformat(),
        model_provider=model_provider,
        model_id=model_id,
        effective_model_ids=effective_model_ids,
        temperature=TEMPERATURE,
        dataset_file=str(dataset_path.name),
        dataset_hash=file_hash(dataset_path),
        prompt_hashes=all_prompt_hashes(),
        ticket_ids=[t.id for t in tickets],
        limit=limit,
        jev_mode=jev_mode,
        gate_intent=gate_intent,
        gate_strategy=gate_strategy,
        gate_escalate_band=gate_escalate_band,
        requests_processed=len(results),
        error_ticket_ids=[r.ticket_id for r in results if r.status == "ERROR"],
        model_calls=agg.model_calls,
        triage_calls=agg.triage_calls,
        reply_calls=agg.reply_calls,
        repair_retries=agg.repair_retries,
        jev_calls=agg.jev_calls,
        jev_decisions=agg.jev_decisions,
        fallback_intent=agg.fallback_intent,
        fallback_strategy=agg.fallback_strategy,
        fallback_escalate=agg.fallback_escalate,
        jev_input_tokens=agg.jev_input_tokens,
        jev_output_tokens=agg.jev_output_tokens,
        model_input_tokens=agg.input_tokens,
        model_output_tokens=agg.output_tokens,
        model_total_tokens=agg.total_tokens,
    )
    (run_dir / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return results, summary, run_dir


def load_run(run_id: str) -> tuple[list[TicketResult], RunSummary]:
    run_dir = RESULTS_DIR / run_id
    summary = RunSummary.model_validate_json((run_dir / "summary.json").read_text(encoding="utf-8"))
    results = [
        TicketResult.model_validate_json(line)
        for line in (run_dir / "requests.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return results, summary
