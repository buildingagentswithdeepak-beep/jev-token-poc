"""GitHub Copilot SDK-backed frontier-model client.

This is the supported Copilot subscription path (not the retired GitHub Models
API and not the internal copilot_internal token endpoint). It preserves the
existing synchronous ModelClient seam while driving the official async SDK.

Safety/determinism boundaries:
- mode="empty"; no tools, skills, memory, config discovery, file hooks or store.
- a fresh session per call, so no conversation carry-over can confound tokens.
- actual tokens and effective model come exclusively from `assistant.usage`.
- explicit model IDs fail closed if Copilot silently substitutes another model.
  `auto` intentionally accepts the provider-selected effective model.
- Copilot SDK does not expose a per-call max-output-token parameter; max_tokens
  is therefore expressed as a hard textual response constraint. This is a
  documented provider trade-off versus the direct Anthropic adapter.
"""
from __future__ import annotations

import asyncio

import os
import time
import uuid
from pathlib import Path

from ..config import COPILOT_RUNTIME_DIR, MAX_RETRIES, PROJECT_DIR
from ..models import ModelResponse


class CopilotModelError(RuntimeError):
    pass


class CopilotUsageMissing(CopilotModelError):
    pass


def _materialize_runtime_on_windows() -> None:
    """Work around github-copilot-sdk 1.0.23's Windows directory-rename issue.

    The SDK still performs its own checksum-verified package fetch; only the
    final staging-dir rename is avoided by extracting directly into the
    project-local cache. No unverified binary is accepted.
    """
    if os.name != "nt":
        return
    from copilot import _cli_download as download

    version = download.CLI_VERSION
    platform = download.get_runtime_platform()
    pair_dir = download.get_cache_dir(version) / "prebuilds" / platform
    wrapper_name = "copilot-runtime.exe"
    if download._runtime_bundle_is_complete(pair_dir, wrapper_name):
        return
    pair_dir.mkdir(parents=True, exist_ok=True)
    data = download._fetch_verified_release_package(version, platform)
    download._materialize_runtime_bundle(data, platform, pair_dir)
    (pair_dir / download._HOSTLESS_ASSETS_MARKER).write_text("1\n", encoding="ascii")
    if not download._runtime_bundle_is_complete(pair_dir, wrapper_name):
        raise CopilotModelError("Copilot runtime materialization was incomplete")


class CopilotModelClient:
    provider_name = "github-copilot"

    def __init__(self, model_id: str = "auto", timeout_seconds: float = 180.0):
        # Resolve before importing/constructing the SDK client.
        os.environ.setdefault("COPILOT_CLI_EXTRACT_DIR", str(COPILOT_RUNTIME_DIR))
        _materialize_runtime_on_windows()

        from copilot import CopilotClient

        self.model_id = model_id
        self.timeout_seconds = timeout_seconds
        self._loop = asyncio.new_event_loop()
        self._client = CopilotClient(
            mode="empty",
            base_directory=str(PROJECT_DIR / ".copilot-empty"),
        )
        self._closed = False
        self._loop.run_until_complete(self._client.start())
        self.available_model_ids = self._loop.run_until_complete(self._list_model_ids())
        if model_id != "auto" and model_id not in self.available_model_ids:
            self.close()
            raise CopilotModelError(
                f"Copilot model {model_id!r} is unavailable. Available: "
                f"{', '.join(sorted(self.available_model_ids)) or '(none)'}"
            )


    async def _list_model_ids(self) -> set[str]:
        models = await self._client.list_models()
        ids = {"auto"}
        for model in models:
            value = (
                model.get("id") or model.get("name")
                if isinstance(model, dict)
                else getattr(model, "id", None) or getattr(model, "name", None)
            )
            if value:
                ids.add(str(value))
        return ids

    def complete(self, *, system: str, user: str, max_tokens: int) -> ModelResponse:
        if self._closed:
            raise CopilotModelError("Copilot client is closed")
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._loop.run_until_complete(
                    self._complete_async(system=system, user=user, max_tokens=max_tokens)
                )
            except CopilotUsageMissing:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    time.sleep(2**attempt)
                    continue
        raise CopilotModelError(
            f"Copilot call failed after {MAX_RETRIES} retries: {last_exc}"
        ) from last_exc

    async def _complete_async(
        self, *, system: str, user: str, max_tokens: int
    ) -> ModelResponse:
        from copilot.session_events import AssistantUsageData, SessionErrorData

        usages: list[AssistantUsageData] = []
        errors: list[str] = []

        def on_event(event) -> None:
            if isinstance(event.data, AssistantUsageData):
                usages.append(event.data)
            elif isinstance(event.data, SessionErrorData):
                errors.append(event.data.message)

        bounded_system = (
            f"{system}\n\nHARD OUTPUT LIMIT: Keep the response within approximately "
            f"{max_tokens} tokens. Do not use tools."
        )
        start = time.perf_counter()
        async with await self._client.create_session(
            session_id=str(uuid.uuid4()),
            model=self.model_id,
            available_tools=[],
            enable_skills=False,
            enable_config_discovery=False,
            enable_session_store=False,
            enable_session_telemetry=False,
            enable_file_hooks=False,
            skip_custom_instructions=True,
            memory={"enabled": False},
            infinite_sessions={"enabled": False},
            system_message={"mode": "replace", "content": bounded_system},
            on_event=on_event,
        ) as session:
            event = await session.send_and_wait(user, timeout=self.timeout_seconds)
        latency_ms = (time.perf_counter() - start) * 1000.0

        if errors:
            raise CopilotModelError("; ".join(errors))
        if event is None or not getattr(event.data, "content", None):
            raise CopilotModelError("Copilot returned no assistant message")
        if not usages:
            raise CopilotUsageMissing(
                "Copilot returned no assistant.usage event; token estimation is prohibited"
            )
        if any(u.input_tokens is None or u.output_tokens is None for u in usages):
            raise CopilotUsageMissing(
                "Copilot usage event lacked input/output tokens; estimation is prohibited"
            )

        effective_models = {u.model for u in usages}
        if len(effective_models) != 1:
            raise CopilotModelError(
                f"One logical call used multiple effective models: {sorted(effective_models)}"
            )
        effective_model = next(iter(effective_models))
        if self.model_id != "auto" and effective_model != self.model_id:
            raise CopilotModelError(
                f"Copilot silently substituted {effective_model!r} for requested "
                f"model {self.model_id!r}; refusing a misattributed experiment"
            )

        return ModelResponse(
            text=event.data.content,
            input_tokens=sum(int(u.input_tokens or 0) for u in usages),
            output_tokens=sum(int(u.output_tokens or 0) for u in usages),
            model_id=effective_model,
            latency_ms=latency_ms,
            provider=self.provider_name,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run_until_complete(self._client.stop())
        except (RuntimeError, OSError):
            # Shutdown must never corrupt an already-written run artifact.
            pass
        finally:
            self._loop.close()
