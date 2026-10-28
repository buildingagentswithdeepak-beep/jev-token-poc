"""Deterministic routing: rule overrides, templates, mock data-store lookup (SPEC §6, §7).

Identical in both versions so it cannot confound the comparison (§6 table).
Zero AI, zero Copilot model tokens.
"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ORDERS_FILE
from .models import Ticket, TriageDecision
from .providers.mock_jev import escalation_for

TEMPLATES: dict[str, str] = {
    "PASSWORD_RESET": (
        "Hi {name},\n\nWe received your request about account access. You can reset your "
        "password at https://helio.example/reset — the link in the email is valid for 60 "
        "minutes. If the reset email does not arrive, check your spam folder or reply here "
        "and we will trigger it manually.\n\nThe Helio Support Team"
    ),
    "BUG_REPORT": (
        "Hi {name},\n\nThanks for reporting this issue. Our engineering team has logged it "
        "under your ticket {ticket_id} and will investigate. We will update you within 2 "
        "business days with findings or a fix timeline.\n\nThe Helio Support Team"
    ),
    "GENERAL_INQUIRY": (
        "Hi {name},\n\nThanks for reaching out. Our help center at https://helio.example/help "
        "covers this topic in detail. If that does not answer your question, reply here and a "
        "support specialist will follow up within 1 business day.\n\nThe Helio Support Team"
    ),
    "CANCELLATION": (
        "Hi {name},\n\nWe received your cancellation request for ticket {ticket_id}. A "
        "retention specialist will confirm the details and process it within 1 business "
        "day.\n\nThe Helio Support Team"
    ),
    "BILLING_DISPUTE": (
        "Hi {name},\n\nWe received your billing question for ticket {ticket_id}. Our billing "
        "team is reviewing the charge and will respond within 1 business day.\n\nThe Helio "
        "Support Team"
    ),
    "ORDER_STATUS": (
        "Hi {name},\n\nWe checked on your order and will follow up with tracking details "
        "shortly for ticket {ticket_id}.\n\nThe Helio Support Team"
    ),
}

AUTO_RESOLVE_TEMPLATE = (
    "Hi {name},\n\nHere is the latest on your order {order_id}: status {status}, carrier "
    "{carrier}, expected delivery {eta}. You can track it anytime at "
    "https://helio.example/track/{order_id}.\n\nThe Helio Support Team"
)

AUTO_RESOLVE_FALLBACK = (
    "Hi {name},\n\nWe could not locate an order linked to this ticket. Please reply with "
    "your order number and we will check immediately.\n\nThe Helio Support Team"
)


class OrderStore:
    """In-repo JSON fixture for deterministic AUTO_RESOLVE lookups (SPEC §16)."""

    def __init__(self, path: Path = ORDERS_FILE):
        self._orders: dict[str, dict] = json.loads(Path(path).read_text(encoding="utf-8"))

    def lookup(self, ticket_id: str) -> dict | None:
        return self._orders.get(ticket_id)


def fill_template(ticket: Ticket, decision: TriageDecision, store: OrderStore) -> str:
    """Deterministic reply for TEMPLATE_REPLY / AUTO_RESOLVE. All variables resolved
    (completion criterion §13.3 — no unresolved {placeholders})."""
    name = "there"
    if decision.strategy == "AUTO_RESOLVE":
        order = store.lookup(ticket.id)
        if order is None:
            return AUTO_RESOLVE_FALLBACK.format(name=name)
        return AUTO_RESOLVE_TEMPLATE.format(
            name=name,
            order_id=order["order_id"],
            status=order["status"],
            carrier=order["carrier"],
            eta=order["eta"],
        )
    template = TEMPLATES[decision.category]
    return template.format(name=name, ticket_id=ticket.id)


def apply_rule_overrides(decision: TriageDecision, ticket: Ticket) -> TriageDecision:
    """Deterministic policy overrides on top of Jev decisions (SPEC §6 O3), e.g.
    tier=ENTERPRISE ∧ URGENT ⇒ always escalate. Hard business rules live in code."""
    escalate, queue = decision.escalate, decision.queue
    forced, forced_queue = escalation_for(decision.category, decision.priority, ticket.customer.tier)
    if forced and not escalate:
        escalate, queue = True, forced_queue
    if escalate and not queue:
        queue = forced_queue or decision.queue
    return decision.model_copy(update={"escalate": escalate, "queue": queue})


def build_reply_user_prompt(ticket: Ticket, decision: TriageDecision, store: OrderStore) -> str:
    """O5 user prompt — identical shape in V1 and V2 (SPEC §14 'same generation prompt')."""
    order = store.lookup(ticket.id)
    facts = (
        f"order_id={order['order_id']}, status={order['status']}, carrier={order['carrier']}, eta={order['eta']}"
        if order
        else "no order on file"
    )
    return (
        f"Ticket {ticket.id}\n"
        f"Subject: {ticket.subject}\n"
        f"Body: {ticket.body}\n"
        f"Customer tier: {ticket.customer.tier} | account age: {ticket.customer.account_age_days} days | "
        f"prior tickets: {ticket.customer.prior_tickets}\n"
        f"Triage: category={decision.category}, priority={decision.priority}, "
        f"escalated={'yes -> ' + decision.queue if decision.escalate else 'no'}\n"
        f"Account facts: {facts}\n\n"
        f"Write the customer-facing reply."
    )
