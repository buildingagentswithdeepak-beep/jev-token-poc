"""Data models and contracts (SPEC §6, §9, §10).

All ticket/result/record shapes are pydantic models so dataset validation
(`validate-dataset`, §11) and artifact serialization are schema-checked.
The Jev contract mirrors the documented `POST /v1/systemone` surface
(Choice/Score/Noul primitives, per-response usage metadata) — SPEC §6.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Protocol, Union

from pydantic import AliasChoices, BaseModel, Field

# Closed outcome sets (SPEC §2, O1-O4)
CATEGORIES = [
    "PASSWORD_RESET",
    "ORDER_STATUS",
    "BILLING_DISPUTE",
    "BUG_REPORT",
    "CANCELLATION",
    "GENERAL_INQUIRY",
]
PRIORITIES = ["LOW", "MEDIUM", "HIGH", "URGENT"]
STRATEGIES = ["TEMPLATE_REPLY", "AUTO_RESOLVE", "CUSTOM_REPLY"]

Category = Literal[
    "PASSWORD_RESET",
    "ORDER_STATUS",
    "BILLING_DISPUTE",
    "BUG_REPORT",
    "CANCELLATION",
    "GENERAL_INQUIRY",
]
Priority = Literal["LOW", "MEDIUM", "HIGH", "URGENT"]
Strategy = Literal["TEMPLATE_REPLY", "AUTO_RESOLVE", "CUSTOM_REPLY"]
Tier = Literal["FREE", "PRO", "ENTERPRISE"]

# Deterministic queue mapping used by rule overrides and the intent→queue policy
# table (§6: queue Choice is asked only where this table doesn't decide it;
# here it always decides, so the queue question is never sent).
QUEUE_BY_CATEGORY = {
    "PASSWORD_RESET": "account-agents",
    "ORDER_STATUS": "order-agents",
    "BILLING_DISPUTE": "billing-agents",
    "BUG_REPORT": "bug-triage",
    "CANCELLATION": "retention-agents",
    "GENERAL_INQUIRY": "support-agents",
}
NO_QUEUE = ""


class Customer(BaseModel):
    tier: Tier
    account_age_days: int = Field(ge=0)
    prior_tickets: int = Field(ge=0)


class GoldLabels(BaseModel):
    category: Category
    priority: Priority
    escalate: bool
    queue: str
    strategy: Strategy


class Ticket(BaseModel):
    id: str
    subject: str
    body: str
    customer: Customer
    gold: GoldLabels


class TriageDecision(BaseModel):
    """Output of the V1 model triage call or V2 Jev answers + overrides (FR-2)."""

    category: Category
    priority: Priority
    escalate: bool
    queue: str
    strategy: Strategy


# --- Jev question primitives (SPEC §6 — grounded in documented /v1/systemone) ---


@dataclass
class ChoiceQ:
    """Unordered option set (2–12 options); criteria = option → description map.
    Descriptions materially affect accuracy and are versioned with prompts (§14)."""

    instructions: str
    criteria: dict[str, str]
    type: str = "choice"


@dataclass
class ScoreQ:
    """Ordinal position on an ordered rubric of 2–10 levels (Choice is for
    unordered sets). criteria = ordered level array per the documented contract."""

    instructions: str
    criteria: list[str]  # ordered levels, e.g. LOW → URGENT
    type: str = "score"


@dataclass
class NoulQ:
    """Yes/no; returns `noul` = P(yes). NO confidence field — gate on |p − 0.5|."""

    instructions: str
    type: str = "noul"


JevQuestion = Union[ChoiceQ, ScoreQ, NoulQ]


def derived_confidence(probabilities: dict[str, float]) -> float:
    """Jev's documented derived confidence for Choice/Score: (n·p_max − 1)/(n − 1).
    NOT the top probability — a 0.70 confidence on 6 options is a far higher bar
    than p_max = 0.70 (SPEC §6)."""
    n = len(probabilities)
    if n <= 1:
        return 1.0
    p_max = max(probabilities.values())
    return (n * p_max - 1.0) / (n - 1.0)


class ChoiceR(BaseModel):
    kind: Literal["choice"] = "choice"
    choice: str
    probabilities: dict[str, float]  # sums to 1
    confidence: float  # derived: (n·p_max − 1)/(n − 1)


class ScoreR(BaseModel):
    kind: Literal["score"] = "score"
    score: float  # position on spectrum (e.g. 1.86)
    probabilities: dict[str, float]  # per-level
    confidence: float
    legend: Optional[dict[str, str]] = None  # index → level description (documented)


class NoulR(BaseModel):
    kind: Literal["noul"] = "noul"
    noul: float  # P(yes); no confidence field


JevAnswer = Union[ChoiceR, ScoreR, NoulR]


class JevUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class JevResponse:
    answers: dict[str, JevAnswer]
    usage: JevUsage  # Jev's OWN usage metadata, captured per call (FR-6)
    latency_ms: float
    provider: str  # "jev" | "mock"
    model: str = ""  # decision-model version reported by the API (log per decision)


class DecisionProvider(Protocol):
    def evaluate(
        self, state: Union[str, dict], questions: dict[str, JevQuestion]
    ) -> JevResponse: ...


# --- Instrumentation records (SPEC §10) ---


class ModelCallRecord(BaseModel):
    run_id: str
    version: Literal["V1", "V2"]
    ticket_id: str
    call_role: Literal["TRIAGE", "REPLY", "REPAIR"]
    provider: str = "unknown-legacy-provider"
    model_id: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    timestamp: str


class JevCallRecord(BaseModel):
    """One per Jev API invocation (= one per ticket). Carries every logical
    question's typed answer + probabilities + derived confidence where the
    primitive provides one (AC-4), gate outcomes, and Jev's own usage tokens."""

    run_id: str
    ticket_id: str
    answers: dict[str, JevAnswer]  # q_intent / q_priority / q_escalate / q_strategy
    gates_fired: list[str]  # subset of {"intent", "strategy", "escalate"}
    input_tokens: int  # Jev usage.input_tokens (FR-6)
    output_tokens: int  # Jev usage.output_tokens
    latency_ms: float
    provider: str  # "jev" | "mock"
    model: str = ""  # Jev model version from the response (docs: log it per decision)

    @property
    def decision_count(self) -> int:
        return len(self.answers)


class TicketResult(BaseModel):
    ticket_id: str
    version: Literal["V1", "V2"]
    status: Literal["OK", "ERROR"]
    error: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    escalate: Optional[bool] = None
    queue: Optional[str] = None
    strategy: Optional[str] = None
    reply: Optional[str] = None
    handled_by: Optional[str] = None  # per-ticket handler attribution (§10)
    fallback: bool = False  # any routing gate fired (intent/strategy)
    gates_fired: list[str] = Field(default_factory=list)  # per-gate attribution
    repair_retries: int = 0  # V1 JSON-repair retries
    model_calls: list[ModelCallRecord] = Field(
        default_factory=list,
        validation_alias=AliasChoices("model_calls", "claude_calls"),
    )
    jev_calls: list[JevCallRecord] = Field(default_factory=list)

    @property
    def model_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.model_calls)

    @property
    def model_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.model_calls)

    @property
    def jev_input_tokens(self) -> int:
        return sum(j.input_tokens for j in self.jev_calls)

    @property
    def jev_output_tokens(self) -> int:
        return sum(j.output_tokens for j in self.jev_calls)


class RunSummary(BaseModel):
    """Persisted per run; carries every FR-15 compatibility field."""

    run_id: str
    version: Literal["V1", "V2"]
    timestamp: str
    model_provider: str = "unknown-legacy-provider"
    model_id: str
    effective_model_ids: list[str] = Field(default_factory=list)
    temperature: Optional[float]
    dataset_file: str
    dataset_hash: str
    prompt_hashes: dict[str, str]  # name -> sha256 (incl. O5 reply prompt + jev criteria)
    ticket_ids: list[str]
    limit: Optional[int] = None
    jev_mode: Optional[str] = None  # "live" | "mock" (V2 only)
    # per-question fallback gates (§6; replace the old single threshold)
    gate_intent: Optional[float] = None
    gate_strategy: Optional[float] = None
    gate_escalate_band: Optional[float] = None
    # measured aggregates (computed, never hand-entered — §10)
    requests_processed: int
    error_ticket_ids: list[str]
    model_calls: int = Field(validation_alias=AliasChoices("model_calls", "claude_calls"))
    triage_calls: int
    reply_calls: int
    repair_retries: int
    jev_calls: int  # API invocations: 1 per ticket (§10 terminology)
    jev_decisions: int  # logical question results: 4 × N
    fallback_intent: int
    fallback_strategy: int
    fallback_escalate: int
    jev_input_tokens: int
    jev_output_tokens: int
    model_input_tokens: int = Field(
        validation_alias=AliasChoices("model_input_tokens", "claude_input_tokens")
    )
    model_output_tokens: int = Field(
        validation_alias=AliasChoices("model_output_tokens", "claude_output_tokens")
    )
    model_total_tokens: int = Field(
        validation_alias=AliasChoices("model_total_tokens", "claude_total_tokens")
    )


# --- Frontier-model client seam (so pipelines/tests run offline) ---


@dataclass
class ModelResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model_id: str
    latency_ms: float
    provider: str = "unknown-legacy-provider"


class ModelClient(Protocol):
    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse: ...
