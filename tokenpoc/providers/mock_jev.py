"""Watermark-enforced mock DecisionProvider (SPEC §16, FR-13).

Implements the same `evaluate(state, questions)` contract as the live adapter
(SPEC §6: "the MockDecisionProvider implements the same evaluate contract,
including fake usage figures clearly zeroed") so the harness is identical in
both modes. Deterministic keyword/rule scoring; injectable noise rate (seeded)
for fallback testing. Mock routing drives V2's frontier-model totals — every artifact
produced with provider == "mock" is watermarked by the report layer.
"""
from __future__ import annotations

import random
import re
import time
from typing import Union

from ..models import (
    ChoiceQ,
    ChoiceR,
    JevQuestion,
    JevResponse,
    JevUsage,
    NoulQ,
    NoulR,
    QUEUE_BY_CATEGORY,
    ScoreQ,
    ScoreR,
    derived_confidence,
)

_KEYWORDS: dict[str, list[str]] = {
    "PASSWORD_RESET": ["password", "log in", "login", "locked out", "reset", "2fa", "credentials", "sign in"],
    "ORDER_STATUS": ["order", "tracking", "shipment", "delivery", "shipped", "package", "arrive"],
    "BILLING_DISPUTE": ["charge", "charged", "invoice", "refund", "billing", "payment", "overcharged", "double"],
    "BUG_REPORT": ["bug", "crash", "error", "broken", "doesn't work", "fails", "freezes", "glitch"],
    "CANCELLATION": ["cancel", "cancellation", "unsubscribe", "close my account", "terminate"],
    "GENERAL_INQUIRY": ["how do i", "how to", "question", "wondering", "can you tell", "info"],
}

_URGENT_MARKERS = ["urgent", "immediately", "asap", "right now", "production down", "security"]
_PRIORITY_LEVELS = ["LOW", "MEDIUM", "HIGH", "URGENT"]


def _state_text(state: Union[str, dict]) -> str:
    if isinstance(state, str):
        return state.lower()
    return f"{state.get('subject', '')} {state.get('body', '')}".lower()


def _state_tier(state: Union[str, dict]) -> str:
    return state.get("tier", "FREE") if isinstance(state, dict) else "FREE"


def _score_categories(text_l: str, options: list[str]) -> dict[str, float]:
    raw = {}
    for label in options:
        kws = _KEYWORDS.get(label, [])
        raw[label] = float(sum(len(re.findall(re.escape(k), text_l)) for k in kws))
    smoothed = {k: v + 0.25 for k, v in raw.items()}  # never exactly 0/1
    total = sum(smoothed.values())
    return {k: v / total for k, v in smoothed.items()}


class MockDecisionProvider:
    """Deterministic; `noise_rate` (seeded) occasionally flattens probabilities to
    exercise the per-question fallback gates. Usage tokens are ZEROED — clearly
    fake per SPEC §6; mock cost lines are therefore $0 and watermarked."""

    provider_name = "mock"

    def __init__(self, noise_rate: float = 0.0, seed: int = 1337):
        self._noise_rate = noise_rate
        self._rng = random.Random(seed)

    def evaluate(
        self, state: Union[str, dict], questions: dict[str, JevQuestion]
    ) -> JevResponse:
        start = time.perf_counter()
        text = _state_text(state)
        tier = _state_tier(state)
        answers = {}
        # intent is answered first so dependent questions can use it (the real
        # API evaluates in parallel against the same state; the mock emulates
        # outcomes, not mechanics)
        intent = None
        if "q_intent" in questions:
            probs = self._maybe_flatten(_score_categories(text, list(questions["q_intent"].criteria)))
            intent = max(probs, key=probs.get)
            answers["q_intent"] = ChoiceR(
                choice=intent, probabilities=probs, confidence=derived_confidence(probs)
            )
        for name, q in questions.items():
            if name == "q_intent":
                continue
            if isinstance(q, ScoreQ):
                answers[name] = self._priority(text, tier, intent, q)
            elif isinstance(q, NoulQ):
                answers[name] = self._escalate(text, tier, intent)
            elif isinstance(q, ChoiceQ):
                answers[name] = self._strategy(intent, answers, q)
            else:
                raise ValueError(f"Unknown question type for {name}")
        return JevResponse(
            answers=answers,
            usage=JevUsage(input_tokens=0, output_tokens=0),  # clearly zeroed (mock)
            latency_ms=(time.perf_counter() - start) * 1000.0,
            provider=self.provider_name,
            model="mock-jev",
        )

    # -- per-question implementations over the state --

    def _priority(self, text, tier, intent, q: ScoreQ) -> ScoreR:
        urgent_hits = sum(1 for m in _URGENT_MARKERS if m in text)
        if urgent_hits and (tier == "ENTERPRISE" or intent in ("BILLING_DISPUTE", "BUG_REPORT")):
            top = "URGENT"
        elif intent in ("BILLING_DISPUTE", "CANCELLATION") or (tier == "ENTERPRISE" and intent == "BUG_REPORT"):
            top = "HIGH"
        elif intent in ("BUG_REPORT", "ORDER_STATUS"):
            top = "MEDIUM"
        else:
            top = "LOW"
        probs = self._maybe_flatten(self._peaked(q.criteria, top, 0.85))
        # score = probability-weighted position on the spectrum (documented float)
        score = sum(q.criteria.index(k) * v for k, v in probs.items())
        legend = {str(i): level for i, level in enumerate(q.criteria)}
        return ScoreR(score=score, probabilities=probs,
                      confidence=derived_confidence(probs), legend=legend)

    def _escalate(self, text, tier, intent) -> NoulR:
        urgent_hits = sum(1 for m in _URGENT_MARKERS if m in text)
        if intent in ("BILLING_DISPUTE", "CANCELLATION"):
            p = 0.93
        elif intent == "BUG_REPORT" and tier == "ENTERPRISE":
            p = 0.84
        elif urgent_hits:
            p = 0.76
        else:
            p = 0.07
        if self._noise_rate > 0 and self._rng.random() < self._noise_rate:
            p = 0.5 + (p - 0.5) * 0.2  # pull into the unsure band
        return NoulR(noul=p)

    def _strategy(self, intent, answers, q: ChoiceQ) -> ChoiceR:
        intent_conf = answers["q_intent"].confidence if "q_intent" in answers else 1.0
        options = list(q.criteria)
        if intent == "ORDER_STATUS":
            top, conf = "AUTO_RESOLVE", 0.90
        elif intent in ("PASSWORD_RESET", "GENERAL_INQUIRY"):
            top, conf = "TEMPLATE_REPLY", 0.88
        elif intent == "BUG_REPORT":
            top, conf = "TEMPLATE_REPLY", 0.75
        else:  # BILLING_DISPUTE, CANCELLATION
            top, conf = "CUSTOM_REPLY", 0.92
        conf = conf * (0.55 + 0.45 * max(0.0, min(intent_conf, 1.0)))
        probs = self._maybe_flatten(self._peaked(options, top, conf))
        choice = max(probs, key=probs.get)
        return ChoiceR(choice=choice, probabilities=probs, confidence=derived_confidence(probs))

    def _maybe_flatten(self, probs: dict[str, float]) -> dict[str, float]:
        if self._noise_rate > 0 and self._rng.random() < self._noise_rate:
            n = len(probs)
            probs = {k: 0.35 * v + 0.65 / n for k, v in probs.items()}
        total = sum(probs.values()) or 1.0
        return {k: v / total for k, v in probs.items()}

    @staticmethod
    def _peaked(labels: list[str], top: str, confidence: float) -> dict[str, float]:
        rest = (1.0 - confidence) / (len(labels) - 1)
        return {k: (confidence if k == top else rest) for k in labels}


def escalation_for(category: str, priority: str, tier: str) -> tuple[bool, str]:
    """Deterministic escalation policy shared by rule overrides (SPEC §6 O3).

    Hard business rules belong in code: BILLING_DISPUTE and CANCELLATION always
    escalate; URGENT always escalates; ENTERPRISE bug reports escalate.
    """
    escalate = (
        category in ("BILLING_DISPUTE", "CANCELLATION")
        or priority == "URGENT"
        or (category == "BUG_REPORT" and tier == "ENTERPRISE")
    )
    return (escalate, QUEUE_BY_CATEGORY[category] if escalate else "")
