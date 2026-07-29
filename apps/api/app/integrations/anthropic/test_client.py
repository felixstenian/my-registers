"""Cliente Anthropic para o ambiente E2E (`APP_ENV=test`).

Substitui `AnthropicClient` real por um consumidor de fila HTTP-controlável.
Playwright enfileira respostas via `POST /test/queue-llm-response` antes de
disparar a interação na UI; o backend consome dessa fila em vez de bater na
API real da Anthropic — 0 custo, 0 flake por variação de LLM.

Filas são módulo-level (uma instância `TestAnthropicClient` por request; o
estado vive no módulo). Falha explícita com `error="no_queued_result"` se
consumidor tenta puxar de fila vazia — testes precisam enfileirar antes.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from app.integrations.anthropic.client import LLMCallResult, NarrativeResult
from app.schemas.llm import LLMEnvelope

_QUEUE_RECORD_INTENT: deque[LLMEnvelope] = deque()
_QUEUE_NARRATIVE: deque[str | None] = deque()
_QUEUE_WEEKLY_NARRATIVE: deque[str | None] = deque()


def queue_record_intent(envelope: LLMEnvelope) -> None:
    _QUEUE_RECORD_INTENT.append(envelope)


def queue_narrative(text: str | None) -> None:
    _QUEUE_NARRATIVE.append(text)


def queue_weekly_narrative(text: str | None) -> None:
    _QUEUE_WEEKLY_NARRATIVE.append(text)


def clear_all_queues() -> None:
    _QUEUE_RECORD_INTENT.clear()
    _QUEUE_NARRATIVE.clear()
    _QUEUE_WEEKLY_NARRATIVE.clear()


def queue_sizes() -> dict[str, int]:
    return {
        "record_intent": len(_QUEUE_RECORD_INTENT),
        "narrative": len(_QUEUE_NARRATIVE),
        "weekly_narrative": len(_QUEUE_WEEKLY_NARRATIVE),
    }


class TestAnthropicClient:
    """Interface-compatível com `AnthropicClient` mas serve respostas da fila.

    Só é montado quando `settings.app_env == "test"` — em `app.api.deps`.
    """

    PROMPT_VERSION = "system_v2"
    NARRATIVE_PROMPT_VERSION = "narrative_v1"
    WEEKLY_NARRATIVE_PROMPT_VERSION = "weekly_narrative_v1"

    def __init__(self, model: str = "test-model") -> None:
        self.model = model
        self.fallback_model = model

    @property
    def is_configured(self) -> bool:
        return True

    async def call_record_intent(
        self,
        *,
        user_text: str | None,
        images: list[tuple[str, bytes]] | None = None,
        max_semantic_retries: int = 1,
    ) -> LLMCallResult:
        if not _QUEUE_RECORD_INTENT:
            return LLMCallResult(
                envelope=None,
                raw_tool_input=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.PROMPT_VERSION,
                error="no_queued_result",
            )
        envelope = _QUEUE_RECORD_INTENT.popleft()
        return LLMCallResult(
            envelope=envelope,
            raw_tool_input=_envelope_to_dict(envelope),
            tokens_input=0,
            tokens_output=0,
            model=self.model,
            prompt_version=self.PROMPT_VERSION,
        )

    async def call_narrative(self, *, totals_payload: dict[str, Any]) -> NarrativeResult:
        text = _QUEUE_NARRATIVE.popleft() if _QUEUE_NARRATIVE else None
        return NarrativeResult(
            text=text,
            tokens_input=0,
            tokens_output=0,
            model=self.model,
            prompt_version=self.NARRATIVE_PROMPT_VERSION,
            error=None if text else "no_queued_result",
        )

    async def call_weekly_narrative(self, totals_payload: dict[str, Any]) -> NarrativeResult:
        text = _QUEUE_WEEKLY_NARRATIVE.popleft() if _QUEUE_WEEKLY_NARRATIVE else None
        return NarrativeResult(
            text=text,
            tokens_input=0,
            tokens_output=0,
            model=self.model,
            prompt_version=self.WEEKLY_NARRATIVE_PROMPT_VERSION,
            error=None if text else "no_queued_result",
        )


def _envelope_to_dict(envelope: LLMEnvelope) -> dict[str, Any]:
    return envelope.model_dump(mode="python", exclude_none=True)
