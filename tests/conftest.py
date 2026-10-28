"""Shared test fixtures — both AI providers mocked; everything runs offline."""
from __future__ import annotations

import json

import pytest

from tokenpoc.models import ModelResponse, Customer, GoldLabels, Ticket


class FakeModelClient:
    """Deterministic offline frontier-model stand-in implementing the ModelClient seam.

    Behavior is script-driven: `triage_responses` maps ticket markers to raw
    response texts (to exercise malformed-JSON repair); default is valid JSON.
    """

    def __init__(self, triage_json=None, reply_text="Dear customer, we resolved it.\nThe Helio Support Team", malformed_first_n=0, fail_always=False):
        self.calls = []
        self._triage_json = triage_json or {
            "category": "BILLING_DISPUTE",
            "priority": "HIGH",
            "escalate": True,
            "queue": "billing-agents",
            "strategy": "CUSTOM_REPLY",
        }
        self._reply_text = reply_text
        self._malformed_remaining = malformed_first_n
        self._fail_always = fail_always
        self.model_id = "test-model-1"

    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse:
        if self._fail_always:
            raise RuntimeError("simulated API failure")
        self.calls.append({"system": system, "user": user, "max_tokens": max_tokens})
        is_reply = max_tokens == 500
        if is_reply:
            text = self._reply_text
        elif self._malformed_remaining > 0:
            self._malformed_remaining -= 1
            text = "category: BILLING_DISPUTE (not json, oops"
        else:
            text = json.dumps(self._triage_json)
        return ModelResponse(
            text=text,
            input_tokens=len(system.split()) + len(user.split()),  # deterministic, NOT estimation of real usage — this IS the fake API's metadata
            output_tokens=len(text.split()),
            model_id=self.model_id,
            latency_ms=1.0,
        )


def make_ticket(
    tid="T-001",
    subject="Charged twice for March invoice",
    body="My card shows two charges for the same invoice. Refund one immediately.",
    tier="PRO",
    gold_category="BILLING_DISPUTE",
    gold_priority="HIGH",
    gold_escalate=True,
    gold_queue="billing-agents",
    gold_strategy="CUSTOM_REPLY",
):
    return Ticket(
        id=tid,
        subject=subject,
        body=body,
        customer=Customer(tier=tier, account_age_days=400, prior_tickets=3),
        gold=GoldLabels(
            category=gold_category,
            priority=gold_priority,
            escalate=gold_escalate,
            queue=gold_queue,
            strategy=gold_strategy,
        ),
    )


@pytest.fixture
def fake_model():
    return FakeModelClient()
