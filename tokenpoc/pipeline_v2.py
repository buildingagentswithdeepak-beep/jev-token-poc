"""V2 pipeline — Jev + Copilot model (SPEC §6, §8).

ONE Jev call per ticket (`evaluate(state, {q_intent, q_priority, q_escalate,
q_strategy})`), Jev usage tokens captured, rule overrides in code, then the
per-question gates:
  - q_intent (Choice):   derived confidence < gate_intent   ⇒ CUSTOM_REPLY
  - q_strategy (Choice): derived confidence < gate_strategy ⇒ CUSTOM_REPLY
  - q_escalate (Noul):   |noul − 0.5| < gate_escalate_band  ⇒ escalate = true
  - q_priority (Score):  NO gate (deliberate asymmetry, §6)
The queue Choice is never sent: the intent→queue policy table (deterministic
code) always decides it, as §6 permits. The Copilot model is invoked only for CUSTOM_REPLY,
with the SAME reply prompt as V1 (§14).
"""
from __future__ import annotations

from datetime import datetime, timezone

from .config import (
    DEFAULT_GATE_ESCALATE_BAND,
    DEFAULT_GATE_INTENT,
    DEFAULT_GATE_STRATEGY,
    PRIORITY_SCORE_CUTPOINTS,
    REPLY_MAX_TOKENS,
)
from .models import (
    ModelCallRecord,
    ModelClient,
    DecisionProvider,
    JevCallRecord,
    PRIORITIES,
    Ticket,
    TicketResult,
    TriageDecision,
)
from .prompts_loader import load_jev_questions, load_prompt
from .routing import OrderStore, apply_rule_overrides, build_reply_user_prompt, fill_template


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def score_to_priority(score: float) -> str:
    """Map the Score float to the four levels by fixed, versioned cut-points (§6 O2)."""
    for i, cut in enumerate(PRIORITY_SCORE_CUTPOINTS):
        if score < cut:
            return PRIORITIES[i]
    return PRIORITIES[-1]


def process_ticket_v2(
    ticket: Ticket,
    provider: DecisionProvider,
    client: ModelClient | None,
    store: OrderStore,
    run_id: str,
    gate_intent: float = DEFAULT_GATE_INTENT,
    gate_strategy: float = DEFAULT_GATE_STRATEGY,
    gate_escalate_band: float = DEFAULT_GATE_ESCALATE_BAND,
) -> TicketResult:
    result = TicketResult(ticket_id=ticket.id, version="V2", status="OK")
    try:
        state = {
            "subject": ticket.subject,
            "body": ticket.body,
            "tier": ticket.customer.tier,
            "account_age_days": ticket.customer.account_age_days,
            "prior_tickets": ticket.customer.prior_tickets,
        }
        # ONE Jev call, four questions evaluated in parallel (§6)
        questions = load_jev_questions()
        resp = provider.evaluate(state, questions)

        intent_a = resp.answers["q_intent"]
        priority_a = resp.answers["q_priority"]
        escalate_a = resp.answers["q_escalate"]
        strategy_a = resp.answers["q_strategy"]

        category = intent_a.choice
        priority = score_to_priority(priority_a.score)
        strategy = strategy_a.choice
        escalate = escalate_a.noul >= 0.5

        # Per-question gates (§6 table), each naming its exact quantity
        gates_fired: list[str] = []
        if intent_a.confidence < gate_intent:
            gates_fired.append("intent")
        if strategy_a.confidence < gate_strategy:
            gates_fired.append("strategy")
        if abs(escalate_a.noul - 0.5) < gate_escalate_band:
            gates_fired.append("escalate")
            escalate = True  # conservative: unsure ⇒ escalate (§6)
        if "intent" in gates_fired or "strategy" in gates_fired:
            strategy = "CUSTOM_REPLY"
            result.fallback = True
        result.gates_fired = gates_fired

        result.jev_calls.append(
            JevCallRecord(
                run_id=run_id,
                ticket_id=ticket.id,
                answers=resp.answers,
                gates_fired=gates_fired,
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                latency_ms=resp.latency_ms,
                provider=resp.provider,
                model=resp.model,
            )
        )

        decision = TriageDecision(
            category=category,
            priority=priority,
            escalate=escalate,
            queue="",  # queue is decided by the deterministic policy table below
            strategy=strategy,
        )
        decision = apply_rule_overrides(decision, ticket)

        if decision.strategy == "CUSTOM_REPLY":
            if client is None:
                raise RuntimeError("CUSTOM_REPLY routed but no Copilot model client configured")
            cresp = client.complete(
                system=load_prompt("reply_system"),
                user=build_reply_user_prompt(ticket, decision, store),
                max_tokens=REPLY_MAX_TOKENS,
            )
            result.model_calls.append(
                ModelCallRecord(
                    run_id=run_id,
                    version="V2",
                    ticket_id=ticket.id,
                    call_role="REPLY",
                    provider=getattr(cresp, "provider", "unknown-legacy-provider"),
                    model_id=cresp.model_id,
                    input_tokens=cresp.input_tokens,
                    output_tokens=cresp.output_tokens,
                    latency_ms=cresp.latency_ms,
                    timestamp=_now(),
                )
            )
            reply = cresp.text.strip()
            if not reply:
                raise ValueError("empty generated reply")
            result.handled_by = (
                "Jev (low confidence) → Copilot model"
                if result.fallback
                else "Jev → Copilot model"
            )
        else:
            reply = fill_template(ticket, decision, store)
            result.handled_by = "Jev → " + (
                "template engine" if decision.strategy == "TEMPLATE_REPLY" else "auto-resolve"
            )

        result.category = decision.category
        result.priority = decision.priority
        result.escalate = decision.escalate
        result.queue = decision.queue
        result.strategy = decision.strategy
        result.reply = reply
    except Exception as exc:
        result.status = "ERROR"
        result.error = f"{type(exc).__name__}: {exc}"
    return result
