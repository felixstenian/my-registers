"""Cliente Anthropic (AsyncAnthropic) com `tool_use` forçado e retry semântico.

Const. Art. II §5-7 (LLM só interpreta, apenas via tool_use, texto livre é lixo)
e Const. §19 (segredos nunca em log). Referências:
- Estratégia: `app_plan.md` §8.1
- Schema tool: `app_plan.md` §8.2 e `tool_schema.py`
- Prompt de sistema: `prompts/system_v2.md`

O SDK oficial já implementa retries em 5xx/429 (`max_retries=2`, backoff
exponencial); nós tratamos manualmente retry SEMÂNTICO: se o `input` da tool
falhar na validação Pydantic, mandamos o `ValidationError` de volta como
`role=user` numa nova chamada (até 2 tentativas).
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import ValidationError

import anthropic
from app.core.config import get_settings
from app.integrations.anthropic.tool_schema import RECORD_INTENT_TOOL
from app.schemas.llm import LLMEnvelope

logger = logging.getLogger("app.anthropic")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_v2.md"


@lru_cache
def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


@dataclass(slots=True)
class LLMCallResult:
    envelope: LLMEnvelope | None
    raw_tool_input: dict[str, Any] | None
    tokens_input: int
    tokens_output: int
    model: str
    prompt_version: str
    error: str | None = None
    validation_errors: list[dict[str, Any]] = field(default_factory=list)


class AnthropicClient:
    """Wrapper fino sobre a SDK oficial da Anthropic.

    Substituído por um fake nos testes via `app.dependency_overrides`.
    """

    PROMPT_VERSION = "system_v2"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.1,
        timeout_seconds: float = 60.0,
        max_http_retries: int = 2,
    ) -> None:
        # Sem API key → cliente marcado como não configurado; caller deve
        # tratar como erro sem sequer bater na rede (útil pra dev/CI).
        self._api_key = api_key
        self._configured = bool(api_key)
        self._client = (
            anthropic.AsyncAnthropic(
                api_key=api_key,
                timeout=timeout_seconds,
                max_retries=max_http_retries,
            )
            if self._configured
            else None
        )
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def is_configured(self) -> bool:
        return self._configured

    async def call_record_intent(
        self,
        *,
        user_text: str | None,
        images: list[tuple[str, bytes]] | None = None,
        max_semantic_retries: int = 2,
    ) -> LLMCallResult:
        images = images or []
        if not self._configured or self._client is None:
            return LLMCallResult(
                envelope=None,
                raw_tool_input=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.PROMPT_VERSION,
                error="anthropic_not_configured",
            )

        base_user_content = self._build_user_content(user_text, images)
        conversation: list[dict[str, Any]] = [
            {"role": "user", "content": base_user_content}
        ]

        tokens_in_total = 0
        tokens_out_total = 0
        last_validation_errors: list[dict[str, Any]] = []

        # 1 chamada inicial + até `max_semantic_retries` chamadas de correção.
        for attempt in range(max_semantic_retries + 1):
            try:
                response = await self._client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=[
                        {
                            "type": "text",
                            "text": _load_system_prompt(),
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=[
                        {
                            **RECORD_INTENT_TOOL,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tool_choice={"type": "tool", "name": "record_intent"},
                    messages=conversation,
                )
            except anthropic.APITimeoutError:
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=self.model,
                    prompt_version=self.PROMPT_VERSION,
                    error="anthropic_timeout",
                )
            except anthropic.APIStatusError as exc:
                logger.warning(
                    "anthropic_api_status",
                    extra={"event": "anthropic_error", "status_code": exc.status_code},
                )
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=self.model,
                    prompt_version=self.PROMPT_VERSION,
                    error=f"anthropic_status_{exc.status_code}",
                )
            except anthropic.APIError as exc:
                logger.warning(
                    "anthropic_api_error",
                    extra={"event": "anthropic_error", "err": type(exc).__name__},
                )
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=self.model,
                    prompt_version=self.PROMPT_VERSION,
                    error="anthropic_error",
                )

            usage = getattr(response, "usage", None)
            if usage is not None:
                tokens_in_total += int(getattr(usage, "input_tokens", 0) or 0)
                tokens_out_total += int(getattr(usage, "output_tokens", 0) or 0)

            tool_input = _extract_tool_input(response)
            if tool_input is None:
                # Const. §7 / INV-9: sem tool_use válido, o retorno é lixo.
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=self.model,
                    prompt_version=self.PROMPT_VERSION,
                    error="no_tool_use",
                )

            try:
                envelope = LLMEnvelope.model_validate(tool_input)
            except ValidationError as exc:
                last_validation_errors = exc.errors()
                if attempt >= max_semantic_retries:
                    return LLMCallResult(
                        envelope=None,
                        raw_tool_input=tool_input,
                        tokens_input=tokens_in_total,
                        tokens_output=tokens_out_total,
                        model=self.model,
                        prompt_version=self.PROMPT_VERSION,
                        error="validation_exhausted",
                        validation_errors=last_validation_errors,
                    )
                conversation.append(
                    {"role": "assistant", "content": response.content}
                )
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "O JSON anterior falhou na validação com os "
                                    f"seguintes erros: {last_validation_errors}. "
                                    "Retorne APENAS via `record_intent` com o "
                                    "schema correto, mantendo o mesmo sentido."
                                ),
                            }
                        ],
                    }
                )
                continue

            return LLMCallResult(
                envelope=envelope,
                raw_tool_input=tool_input,
                tokens_input=tokens_in_total,
                tokens_output=tokens_out_total,
                model=self.model,
                prompt_version=self.PROMPT_VERSION,
            )

        # Loop terminou sem retornar (retries esgotados).
        return LLMCallResult(
            envelope=None,
            raw_tool_input=None,
            tokens_input=tokens_in_total,
            tokens_output=tokens_out_total,
            model=self.model,
            prompt_version=self.PROMPT_VERSION,
            error="validation_exhausted",
            validation_errors=last_validation_errors,
        )

    @staticmethod
    def _build_user_content(
        user_text: str | None, images: list[tuple[str, bytes]]
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for content_type, data in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": content_type,
                        "data": base64.b64encode(data).decode("ascii"),
                    },
                }
            )
        if user_text:
            content.append({"type": "text", "text": user_text})
        if not content:
            # Anthropic exige ao menos um bloco; envelope vazio é reconhecível
            # como `clarify`/`unknown` pelo modelo.
            content.append({"type": "text", "text": "(mensagem vazia)"})
        return content


def _extract_tool_input(response: Any) -> dict[str, Any] | None:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", "") != "record_intent":
            continue
        input_data = getattr(block, "input", None)
        if isinstance(input_data, dict):
            return input_data
    return None


@lru_cache
def get_anthropic_client() -> AnthropicClient:
    s = get_settings()
    return AnthropicClient(
        api_key=s.anthropic_api_key,
        model=s.anthropic_model,
        max_tokens=s.anthropic_max_tokens,
        temperature=s.anthropic_temperature,
    )
