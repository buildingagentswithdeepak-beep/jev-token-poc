"""Configuration via env/.env (SPEC §11) + pricing constants with as-of dates (§10)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PACKAGE_DIR.parent
DATASET_FILE = PROJECT_DIR / "dataset" / "tickets.jsonl"
ORDERS_FILE = PROJECT_DIR / "dataset" / "orders.json"
PROMPTS_DIR = PACKAGE_DIR / "prompts"
RESULTS_DIR = PROJECT_DIR / "results"

DEFAULT_MODEL = "auto"  # Only model exposed by this Copilot Enterprise policy
MODEL_PROVIDER = "github-copilot"
# Copilot SDK does not expose a sampling-temperature control. Retained in
# artifact compatibility metadata as None rather than falsely claiming zero.
TEMPERATURE = None
TRIAGE_MAX_TOKENS = 256  # SPEC §5 Call A
REPLY_MAX_TOKENS = 500  # SPEC §5 Call B
MAX_RETRIES = 3  # 429/5xx (frontier model) and 429/529 (Jev) exponential backoff

# Per-question fallback gates (SPEC §6 table — each names its exact quantity):
#   intent (Choice):   derived confidence (n·p_max−1)/(n−1)        < 0.50 ⇒ CUSTOM_REPLY
#   strategy (Choice): derived confidence                           < 0.60 ⇒ CUSTOM_REPLY
#   escalate (Noul):   |noul − 0.5| (unsure band 0.35–0.65)         < 0.15 ⇒ escalate=true
#   priority (Score):  NO gate (deliberate asymmetry, §6)
DEFAULT_GATE_INTENT = 0.50
DEFAULT_GATE_STRATEGY = 0.60
DEFAULT_GATE_ESCALATE_BAND = 0.15

# Score → priority level cut-points (fixed, versioned — §6 O2). Score is a float
# position on the LOW..URGENT spectrum indexed 0..3; nearest-level by band.
PRIORITY_SCORE_CUTPOINTS = [0.5, 1.5, 2.5]  # <0.5 LOW, <1.5 MEDIUM, <2.5 HIGH, else URGENT

# Pricing constants (SPEC §10/§12 footer: as-of dates print in the report;
# stale pricing changes cost lines, never token lines).
JEV_PRICE_PER_MTOK_INPUT = 0.042  # USD / 1M input tokens
JEV_PRICE_PER_MTOK_OUTPUT = 0.00  # USD / 1M output tokens
JEV_PRICING_AS_OF = "jev-1.12, 2026-09"
# Copilot subscription usage is prompt/allowance-accounted, not billed at the
# direct Anthropic per-token list price. Token reduction remains measurable;
# direct USD generation cost is intentionally reported as N/A.
GENERATION_PRICE_PER_MTOK_INPUT = None
GENERATION_PRICE_PER_MTOK_OUTPUT = None
GENERATION_PRICING_AS_OF = "GitHub Copilot subscription; token-based USD price N/A"
COPILOT_RUNTIME_DIR = PROJECT_DIR / ".copilot-runtime"

# JevStation is the safe default for user-created JEVSTATION/JEV API keys and
# supports the free GET preflight. Override only when using a TypeSafe direct key.
JEV_ENDPOINT = os.environ.get("JEV_ENDPOINT", "https://jevstation.com/api/v1/systemone")

# Exit codes (SPEC §11)
EXIT_OK = 0
EXIT_RUN_ERROR = 1
EXIT_CONFIG_OR_COMPAT = 2


@dataclass
class Settings:
    jev_api_key: str = ""
    model_provider: str = MODEL_PROVIDER
    model_id: str = DEFAULT_MODEL
    jev_mode: str = "mock"

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv(PROJECT_DIR / ".env")
        return cls(
            # JEV_API_KEY preferred; JEVSTATION_API_KEY accepted (docs' env name)
            jev_api_key=os.environ.get("JEV_API_KEY", "")
            or os.environ.get("JEVSTATION_API_KEY", ""),
            model_provider=os.environ.get("MODEL_PROVIDER", MODEL_PROVIDER),
            model_id=os.environ.get("COPILOT_MODEL", DEFAULT_MODEL),
            jev_mode=os.environ.get("JEV_MODE", "mock"),
        )
