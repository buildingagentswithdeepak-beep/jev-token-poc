"""Prompt + Jev-question loading and hashing (SPEC §14: versioned files; any edit
invalidates prior runs — run_id embeds hashes; criteria descriptions materially
affect Jev accuracy so jev_questions.json is versioned and hashed too)."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from .config import PROMPTS_DIR
from .models import ChoiceQ, JevQuestion, NoulQ, ScoreQ

PROMPT_NAMES = ("triage_system", "reply_system", "repair_system")
JEV_QUESTIONS_FILE = "jev_questions.json"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")


def prompt_hash(name: str) -> str:
    return hashlib.sha256(load_prompt(name).encode("utf-8")).hexdigest()[:16]


def _jev_questions_text() -> str:
    return (PROMPTS_DIR / JEV_QUESTIONS_FILE).read_text(encoding="utf-8")


def jev_questions_hash() -> str:
    return hashlib.sha256(_jev_questions_text().encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=None)
def load_jev_questions() -> dict[str, JevQuestion]:
    """The four §6 questions, built from the versioned criteria file."""
    raw = json.loads(_jev_questions_text())
    out: dict[str, JevQuestion] = {}
    for name, q in raw.items():
        if q["type"] == "choice":
            out[name] = ChoiceQ(instructions=q["instructions"], criteria=q["criteria"])
        elif q["type"] == "score":
            out[name] = ScoreQ(instructions=q["instructions"], criteria=q["criteria"])
        elif q["type"] == "noul":
            out[name] = NoulQ(instructions=q["instructions"])
        else:
            raise ValueError(f"unknown question type {q['type']!r} for {name}")
    return out


def all_prompt_hashes() -> dict[str, str]:
    hashes = {name: prompt_hash(name) for name in PROMPT_NAMES}
    hashes["jev_questions"] = jev_questions_hash()
    return hashes


def file_hash(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]
