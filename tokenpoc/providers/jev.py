"""Live Jev adapter — JevStation `POST /api/v1/systemone` documented contract
(https://jevstation.com/docs).

Grounded in the published surface:
  - endpoint: POST https://jevstation.com/api/v1/systemone
    (the user-supplied https://api.typesafe.ai/v1/systemone is TypeSafe's direct
    path with the same request/answer shapes; endpoint is configurable)
  - auth: `Authorization: Bearer <JEVSTATION_API_KEY>` from env, never hard-coded
  - request: {state, questions: {id: {type, instructions, criteria?}}}
    · choice: criteria = option→description map (2–12 options)
    · score:  criteria = ordered level array (2–10 levels)
    · noul:   instructions only
  - response: house envelope {code: 0|-1, message, data}; data carries
    answers (typed, keyed by our ids), usage.input_tokens/output_tokens,
    credits, latency_ms, and the pinned model version (log it per decision)
  - errors: 401 bad key · 400 malformed · 402 no credits · 413 state too large ·
    404 unknown question_set_id · 429 rate limit (honour retry-after) ·
    502 evaluation failed (refunded) · 503 at capacity
  - retry: exponential backoff on 429/529/5xx, max 3 (mirrors model client)
  - limits: ≤12 questions/call, instructions ≤600 chars, state ≤24,000 chars

Uses stdlib urllib so the package imports offline with no extra deps.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Union

from ..config import JEV_ENDPOINT, MAX_RETRIES
from ..models import (
    ChoiceQ,
    ChoiceR,
    JevQuestion,
    JevResponse,
    JevUsage,
    NoulQ,
    NoulR,
    ScoreQ,
    ScoreR,
)

# Documented hard limits — validated client-side so a bad question set fails
# fast and free instead of burning a 400 round-trip.
MAX_QUESTIONS_PER_CALL = 12
MAX_INSTRUCTIONS_CHARS = 600
MAX_STATE_CHARS = 24_000

_NON_RETRYABLE = {400, 401, 402, 403, 404, 413}  # real statuses + edge 403 (fail fast)

# JevStation's edge (Cloudflare) returns 403 for Python's default
# "Python-urllib/3.x" User-Agent BEFORE the request reaches the API's auth
# layer (verified: same request with a normal UA gets 401/405 from the API
# itself). Send an identifying client UA on every request.
_USER_AGENT = "tokenpoc/0.1 (jev-token-poc experiment harness)"


class JevError(Exception):
    pass


class JevProvider:
    provider_name = "jev"

    def __init__(self, api_key: str, endpoint: str | None = None, timeout: float = 30.0):
        if not api_key:
            raise JevError(
                "Jev API key not set (JEVSTATION_API_KEY / JEV_API_KEY required for --jev-mode live)"
            )
        self._api_key = api_key
        # resolved at construction so a .env-loaded JEV_ENDPOINT override applies
        self._endpoint = endpoint or os.environ.get("JEV_ENDPOINT", JEV_ENDPOINT)
        self._timeout = timeout

    @property
    def endpoint(self) -> str:
        """Non-secret endpoint used for actionable CLI diagnostics."""
        return self._endpoint

    # -- free preflight: GET with the same header returns plan/credits/limits --

    def check_key(self) -> dict:
        req = urllib.request.Request(
            self._endpoint,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "User-Agent": _USER_AGENT,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise JevError("Jev API key rejected (401) — check JEV_API_KEY") from exc
            if exc.code == 405:
                # TypeSafe's direct endpoint has no GET preflight (JevStation's
                # does). Not an auth failure — skip the preflight silently.
                return {"preflight": "unsupported on this endpoint"}
            if exc.code == 403:
                raise JevError(
                    "Jev key check failed: HTTP 403 — the edge rejected the request "
                    "before auth (bot filter) or the key lacks access. If you are "
                    "using a JevStation key, ensure JEV_ENDPOINT="
                    "https://jevstation.com/api/v1/systemone; a TypeSafe direct key "
                    "belongs on https://api.typesafe.ai/v1/systemone."
                ) from exc
            raise JevError(f"Jev key check failed: HTTP {exc.code}") from exc
        return body.get("data", body)

    def evaluate(
        self, state: Union[str, dict], questions: dict[str, JevQuestion]
    ) -> JevResponse:
        self._validate_limits(state, questions)
        payload = json.dumps(
            {
                "state": state,
                "questions": {name: self._serialize_q(q) for name, q in questions.items()},
            }
        ).encode("utf-8")
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            req = urllib.request.Request(
                self._endpoint,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                method="POST",
            )
            try:
                start = time.perf_counter()
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                latency_ms = (time.perf_counter() - start) * 1000.0
                return self._parse_response(body, questions, latency_ms)
            except urllib.error.HTTPError as exc:
                if exc.code in _NON_RETRYABLE:
                    if exc.code == 401:
                        raise JevError(
                            f"Jev API key rejected by {self._endpoint} (HTTP 401). "
                            "A JevStation key belongs on "
                            "https://jevstation.com/api/v1/systemone; a TypeSafe direct "
                            "key belongs on https://api.typesafe.ai/v1/systemone."
                        ) from exc
                    raise JevError(
                        f"Jev API HTTP {exc.code}: {self._error_hint(exc.code)}"
                    ) from exc
                # retryable: 429 (honour retry-after), 529, 502/503/5xx
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(self._backoff_delay(exc, attempt))
                    continue
            except urllib.error.URLError as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(2**attempt)
                    continue
        raise JevError(f"Jev call failed after {MAX_RETRIES} retries: {last_exc}")

    # -- helpers --

    @staticmethod
    def _error_hint(code: int) -> str:
        return {
            400: "malformed body or questions",
            401: "missing/invalid API key",
            402: "not enough credits",
            403: "forbidden — edge/bot filter or key-endpoint mismatch (JevStation key ↔ JevStation endpoint)",
            404: "unknown question_set_id",
            413: "state too large (max 24,000 chars)",
        }.get(code, "error")

    @staticmethod
    def _backoff_delay(exc: urllib.error.HTTPError, attempt: int) -> float:
        if exc.code == 429:
            retry_after = exc.headers.get("retry-after") if exc.headers else None
            if retry_after:
                try:
                    return max(float(retry_after), 1.0)
                except ValueError:
                    pass
        return float(2**attempt)

    @staticmethod
    def _validate_limits(state: Union[str, dict], questions: dict[str, JevQuestion]) -> None:
        if len(questions) > MAX_QUESTIONS_PER_CALL:
            raise JevError(f"max {MAX_QUESTIONS_PER_CALL} questions per call, got {len(questions)}")
        state_len = len(state) if isinstance(state, str) else len(json.dumps(state))
        if state_len > MAX_STATE_CHARS:
            raise JevError(f"state too large ({state_len} chars > {MAX_STATE_CHARS})")
        for name, q in questions.items():
            if len(q.instructions) > MAX_INSTRUCTIONS_CHARS:
                raise JevError(f"{name}: instructions exceed {MAX_INSTRUCTIONS_CHARS} chars")
            if isinstance(q, ChoiceQ) and not (2 <= len(q.criteria) <= 12):
                raise JevError(f"{name}: choice needs 2–12 options, got {len(q.criteria)}")
            if isinstance(q, ScoreQ) and not (2 <= len(q.criteria) <= 10):
                raise JevError(f"{name}: score needs 2–10 levels, got {len(q.criteria)}")

    @staticmethod
    def _serialize_q(q: JevQuestion) -> dict:
        if isinstance(q, ChoiceQ):
            return {"type": "choice", "instructions": q.instructions, "criteria": q.criteria}
        if isinstance(q, ScoreQ):
            return {"type": "score", "instructions": q.instructions, "criteria": q.criteria}
        if isinstance(q, NoulQ):
            return {"type": "noul", "instructions": q.instructions}
        raise JevError(f"unsupported question type: {type(q).__name__}")

    def _parse_response(
        self, body: dict, questions: dict[str, JevQuestion], latency_ms: float
    ) -> JevResponse:
        # House envelope: {code: 0|-1, message, data}
        if body.get("code", 0) != 0:
            raise JevError(f"Jev evaluation failed: {body.get('message', 'unknown error')}")
        data = body.get("data", body)  # tolerate direct-TypeSafe responses without envelope
        usage = data.get("usage")
        if usage is None or "input_tokens" not in usage or "output_tokens" not in usage:
            raise JevError("Jev response lacked usage metadata (FR-6 requires it)")
        raw_answers = data.get("answers", {})
        answers = {}
        for name, q in questions.items():
            if name not in raw_answers:
                raise JevError(f"Jev response missing answer for question {name!r}")
            a = raw_answers[name]
            if isinstance(q, ChoiceQ):
                answers[name] = ChoiceR(
                    choice=a["choice"],
                    probabilities=a["probabilities"],
                    confidence=a["confidence"],
                )
            elif isinstance(q, ScoreQ):
                answers[name] = ScoreR(
                    score=a["score"],
                    probabilities=a["probabilities"],
                    confidence=a["confidence"],
                    legend=a.get("legend"),
                )
            else:
                answers[name] = NoulR(noul=a["noul"])
        return JevResponse(
            answers=answers,
            usage=JevUsage(
                input_tokens=int(usage["input_tokens"]),
                output_tokens=int(usage["output_tokens"]),
            ),
            latency_ms=latency_ms,
            provider=self.provider_name,
            model=data.get("model", ""),
        )
