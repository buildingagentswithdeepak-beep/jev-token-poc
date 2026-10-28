"""V1 pipeline — Copilot model-only baseline (SPEC §5, §8).

One combined triage call (strongest sane baseline — §5 design note) + conditional
reply generation. Malformed triage JSON gets exactly 1 repair retry whose tokens
ARE counted (§8).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from .config import REPLY_MAX_TOKENS, TRIAGE_MAX_TOKENS
from .models import ModelCallRecord, ModelClient, Ticket, TicketResult, TriageDecision
from .prompts_loader import load_prompt
from .routing import OrderStore, build_reply_user_prompt, fill_template


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_json(text: str) -> dict:
    """Parse strict JSON; tolerate accidental markdown fences, nothing more."""
    stripped = text.strip()
    m = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not m:
        raise ValueError("no JSON object in response")
    return json.loads(m.group(0))


def _ticket_user_prompt(ticket: Ticket) -> str:
    return (
        f"Ticket {ticket.id}\n"
        f"Subject: {ticket.subject}\n"
        f"Body: {ticket.body}\n"
        f"Customer: tier={ticket.customer.tier}, account_age_days={ticket.customer.account_age_days}, "
        f"prior_tickets={ticket.customer.prior_tickets}"
    )


def process_ticket_v1(
    ticket: Ticket, client: ModelClient, store: OrderStore, run_id: str
) -> TicketResult:
    result = TicketResult(ticket_id=ticket.id, version="V1", status="OK")
    try:
        decision = _triage(ticket, client, run_id, result)
        if decision.strategy == "CUSTOM_REPLY":
            reply = _generate_reply(ticket, decision, client, store, run_id, result)
            result.handled_by = "Copilot model triage → Copilot model"
        else:
            reply = fill_template(ticket, decision, store)
            result.handled_by = "Copilot model triage → " + (
                "template engine" if decision.strategy == "TEMPLATE_REPLY" else "auto-resolve"
            )
        result.category = decision.category
        result.priority = decision.priority
        result.escalate = decision.escalate
        result.queue = decision.queue
        result.strategy = decision.strategy
        result.reply = reply
    except Exception as exc:  # ticket-level isolation: one failure never kills the run
        result.status = "ERROR"
        result.error = f"{type(exc).__name__}: {exc}"
    return result


def _triage(
    ticket: Ticket, client: ModelClient, run_id: str, result: TicketResult
) -> TriageDecision:
    system = load_prompt("triage_system")
    user = _ticket_user_prompt(ticket)
    resp = client.complete(system=system, user=user, max_tokens=TRIAGE_MAX_TOKENS)
    result.model_calls.append(_record(run_id, ticket.id, "TRIAGE", resp))
    try:
        return TriageDecision.model_validate(_extract_json(resp.text))
    except (ValueError, ValidationError):
        # 1 repair retry; its tokens are counted (§8)
        result.repair_retries += 1
        repair_system = load_prompt("repair_system") + "\n\n" + system
        resp2 = client.complete(system=repair_system, user=user, max_tokens=TRIAGE_MAX_TOKENS)
        result.model_calls.append(_record(run_id, ticket.id, "REPAIR", resp2))
        return TriageDecision.model_validate(_extract_json(resp2.text))


def _generate_reply(
    ticket: Ticket,
    decision: TriageDecision,
    client: ModelClient,
    store: OrderStore,
    run_id: str,
    result: TicketResult,
) -> str:
    resp = client.complete(
        system=load_prompt("reply_system"),
        user=build_reply_user_prompt(ticket, decision, store),
        max_tokens=REPLY_MAX_TOKENS,
    )
    result.model_calls.append(_record(run_id, ticket.id, "REPLY", resp))
    if not resp.text.strip():
        raise ValueError("empty generated reply")
    return resp.text.strip()


def _record(run_id: str, ticket_id: str, role: str, resp) -> ModelCallRecord:
    return ModelCallRecord(
        run_id=run_id,
        version="V1",
        ticket_id=ticket_id,
        call_role=role,
        provider=getattr(resp, "provider", "unknown-legacy-provider"),
        model_id=resp.model_id,
        input_tokens=resp.input_tokens,
        output_tokens=resp.output_tokens,
        latency_ms=resp.latency_ms,
        timestamp=_now(),
    )
