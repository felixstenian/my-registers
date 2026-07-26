"""Cliente Anthropic (AsyncAnthropic) com `tool_use` forçado e retry semântico.

Const. Art. II §5-7 (LLM só interpreta, apenas via tool_use, texto livre é lixo)
e Const. §19 (segredos nunca em log). Referências:
- Estratégia: `app_plan.md` §8.1
- Schema tool: `app_plan.md` §8.2 e `tool_schema.py`
- Prompt de sistema: `prompts/system_v2.md`
- Plano de otimização: `docs/token-optimization-plan.md`

Otimizações ativas (Tier 1 do plano):
1. **Log de cache** — cada call loga `cache_creation` e `cache_read`
   input_tokens do `response.usage`, permitindo medir hit rate.
2. **Compressão de imagem** — Pillow redimensiona longest-side ≤ 1024px e
   reencoda como JPEG q=75 antes do base64. Reduz 5-15× o tamanho.
3. **Roteamento por complexidade** — texto puro sem foto usa o
   `fallback_model` (Haiku, ~4× mais barato que Sonnet); qualquer imagem
   usa o `model` principal (Sonnet, melhor visão).
4. **1 retry semântico** (default) em vez de 2 — a Fase 5 mostrou que o
   segundo retry raramente resolve, prompt já é estrito o suficiente.

SDK oficial já implementa retries HTTP em 5xx/429 (`max_retries=2`,
backoff exponencial); nós só tratamos retry SEMÂNTICO (Pydantic).
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

import anthropic
from app.core.config import get_settings
from app.integrations.anthropic.tool_schema import RECORD_INTENT_TOOL
from app.schemas.llm import LLMEnvelope

logger = logging.getLogger("app.anthropic")

_PROMPT_PATH = Path(__file__).parent / "prompts" / "system_v2.md"
_NARRATIVE_PROMPT_PATH = Path(__file__).parent / "prompts" / "narrative_v1.md"
_WEEKLY_NARRATIVE_PROMPT_PATH = Path(__file__).parent / "prompts" / "weekly_narrative_v1.md"

# Compressão de imagem — limite conservador para preservar OCR de rótulo.
_IMAGE_MAX_SIDE = 1024
_IMAGE_JPEG_QUALITY = 75

# Cap client-side para o "texto puro é curto" heurístico do roteamento.
# Mensagens longas ainda podem se beneficiar do Sonnet.
_HAIKU_TEXT_MAX_CHARS = 500


@lru_cache
def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


@lru_cache
def _load_narrative_prompt() -> str:
    return _NARRATIVE_PROMPT_PATH.read_text(encoding="utf-8")


@lru_cache
def _load_weekly_narrative_prompt() -> str:
    return _WEEKLY_NARRATIVE_PROMPT_PATH.read_text(encoding="utf-8")


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


@dataclass(slots=True)
class NarrativeResult:
    """Retorno de `call_narrative` (SP-103 / SP-104).

    `text` já vem sem o disclaimer; caller (DayCloseService) concatena
    depois para garantir sempre presente (Const. §26).
    """

    text: str | None
    tokens_input: int
    tokens_output: int
    model: str
    prompt_version: str
    error: str | None = None


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
        fallback_model: str | None = None,
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
        self.fallback_model = fallback_model or model
        self.max_tokens = max_tokens
        self.temperature = temperature

    @property
    def is_configured(self) -> bool:
        return self._configured

    def _pick_model(self, *, has_images: bool, user_text: str | None) -> str:
        """Roteamento por complexidade (Tier 1.3 do plano):

        - Qualquer foto → `model` principal (multimodal precisa de Sonnet).
        - Sem foto + texto curto → `fallback_model` (Haiku, ~4× mais barato).
        - Sem foto + texto longo (>500 chars) → `model` principal (extração
          longa pede mais robustez).
        """
        if has_images:
            return self.model
        if user_text is None:
            return self.fallback_model
        if len(user_text) > _HAIKU_TEXT_MAX_CHARS:
            return self.model
        return self.fallback_model

    async def call_record_intent(
        self,
        *,
        user_text: str | None,
        images: list[tuple[str, bytes]] | None = None,
        max_semantic_retries: int = 1,
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

        chosen_model = self._pick_model(has_images=bool(images), user_text=user_text)
        base_user_content = self._build_user_content(user_text, images)
        conversation: list[dict[str, Any]] = [{"role": "user", "content": base_user_content}]

        tokens_in_total = 0
        tokens_out_total = 0
        last_validation_errors: list[dict[str, Any]] = []

        # 1 chamada inicial + até `max_semantic_retries` chamadas de correção.
        for attempt in range(max_semantic_retries + 1):
            try:
                response = await self._client.messages.create(
                    model=chosen_model,
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
                    model=chosen_model,
                    prompt_version=self.PROMPT_VERSION,
                    error="anthropic_timeout",
                )
            except anthropic.APIStatusError as exc:
                # Captura body do erro (4xx sem body é raro, mas guardamos best-effort).
                body_msg: str | None
                try:
                    body_msg = str(getattr(exc, "message", None) or exc.response.text)
                except Exception:  # noqa: BLE001
                    body_msg = None
                logger.warning(
                    "anthropic_api_status",
                    extra={
                        "event": "anthropic_error",
                        "status_code": exc.status_code,
                        "model": chosen_model,
                        "body": body_msg,
                    },
                )
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=chosen_model,
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
                    model=chosen_model,
                    prompt_version=self.PROMPT_VERSION,
                    error="anthropic_error",
                )

            usage = getattr(response, "usage", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                cache_creation = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
                cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
                tokens_in_total += input_tokens
                tokens_out_total += output_tokens
                # Log estruturado — Tier 1.1 do plano de otimização.
                logger.info(
                    "anthropic_usage",
                    extra={
                        "event": "anthropic_usage",
                        "model": chosen_model,
                        "attempt": attempt,
                        "images": len(images),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_input_tokens": cache_creation,
                        "cache_read_input_tokens": cache_read,
                    },
                )

            tool_input = _extract_tool_input(response)
            if tool_input is None:
                # Const. §7 / INV-9: sem tool_use válido, o retorno é lixo.
                return LLMCallResult(
                    envelope=None,
                    raw_tool_input=None,
                    tokens_input=tokens_in_total,
                    tokens_output=tokens_out_total,
                    model=chosen_model,
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
                        model=chosen_model,
                        prompt_version=self.PROMPT_VERSION,
                        error="validation_exhausted",
                        validation_errors=last_validation_errors,
                    )
                # Retry: enviar de volta o `tool_use` limpo (SDK inclui
                # campos internos como `caller` que a API rejeita — Haiku
                # 4.5 devolve 400 quando esses campos aparecem no payload)
                # + resposta como `tool_result` (não texto solto — Haiku
                # exige tool_result após tool_use).
                tool_use_id = _find_tool_use_id(response) or ""
                conversation.append(
                    {
                        "role": "assistant",
                        "content": _clean_content_for_retry(response.content),
                    }
                )
                conversation.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "is_error": True,
                                "content": (
                                    "O JSON anterior falhou na validação com os "
                                    f"seguintes erros: {last_validation_errors}. "
                                    "Retorne novamente via `record_intent` com o "
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
                model=chosen_model,
                prompt_version=self.PROMPT_VERSION,
            )

        # Loop terminou sem retornar (retries esgotados).
        return LLMCallResult(
            envelope=None,
            raw_tool_input=None,
            tokens_input=tokens_in_total,
            tokens_output=tokens_out_total,
            model=chosen_model,
            prompt_version=self.PROMPT_VERSION,
            error="validation_exhausted",
            validation_errors=last_validation_errors,
        )

    NARRATIVE_PROMPT_VERSION = "narrative_v1"
    WEEKLY_NARRATIVE_PROMPT_VERSION = "weekly_narrative_v1"

    async def call_weekly_narrative(self, totals_payload: dict[str, Any]) -> NarrativeResult:
        """Narrativa semanal (SP-111 / T-802).

        Segunda chamada, sem tool_use, temperature=0.3, roteia sempre pro
        `self.model` principal. Payload contém window_start/end + totals +
        averages + warning_codes; nunca listas cruas de registros.
        """
        if not self._configured or self._client is None:
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.WEEKLY_NARRATIVE_PROMPT_VERSION,
                error="anthropic_not_configured",
            )

        import json

        user_text = (
            "Resumo agregado da semana (backend calculou tudo; use exatos):\n"
            f"{json.dumps(totals_payload, ensure_ascii=False)}"
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=500,
                temperature=0.3,
                system=[
                    {
                        "type": "text",
                        "text": _load_weekly_narrative_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_text}],
                    }
                ],
            )
        except anthropic.APITimeoutError:
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.WEEKLY_NARRATIVE_PROMPT_VERSION,
                error="anthropic_timeout",
            )
        except anthropic.APIError as exc:
            logger.warning(
                "anthropic_weekly_narrative_error",
                extra={"event": "anthropic_error", "err": type(exc).__name__},
            )
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.WEEKLY_NARRATIVE_PROMPT_VERSION,
                error="anthropic_error",
            )

        usage = getattr(response, "usage", None)
        tokens_input = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_output = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

        text_blocks = [
            getattr(block, "text", "")
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        joined = "\n".join(t for t in text_blocks if t).strip()

        return NarrativeResult(
            text=joined or None,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            model=self.model,
            prompt_version=self.WEEKLY_NARRATIVE_PROMPT_VERSION,
            error=None if joined else "empty_narrative",
        )

    async def call_narrative(
        self,
        *,
        totals_payload: dict[str, Any],
    ) -> NarrativeResult:
        """Segunda chamada (SP-103 / T-702): narrativa em pt-BR baseada em
        totais **já calculados**. Sem tool_use, temperature=0.3.

        Sempre roteia para o Sonnet (`self.model`) — texto criativo curto
        precisa da qualidade estilística; o payload é pequeno o suficiente
        para não valer a pena Haiku.
        """
        if not self._configured or self._client is None:
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.NARRATIVE_PROMPT_VERSION,
                error="anthropic_not_configured",
            )

        # Compact single-block user message — o schema é pequeno e serve
        # como contexto suficiente. Payload em JSON serializado (o modelo
        # é ótimo em ler estrutura JSON).
        import json

        user_text = (
            "Totais do dia (calculados pelo backend, use exatos):\n"
            f"{json.dumps(totals_payload, ensure_ascii=False)}"
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=400,
                temperature=0.3,
                system=[
                    {
                        "type": "text",
                        "text": _load_narrative_prompt(),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_text}],
                    }
                ],
            )
        except anthropic.APITimeoutError:
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.NARRATIVE_PROMPT_VERSION,
                error="anthropic_timeout",
            )
        except anthropic.APIError as exc:
            logger.warning(
                "anthropic_narrative_error",
                extra={"event": "anthropic_error", "err": type(exc).__name__},
            )
            return NarrativeResult(
                text=None,
                tokens_input=0,
                tokens_output=0,
                model=self.model,
                prompt_version=self.NARRATIVE_PROMPT_VERSION,
                error="anthropic_error",
            )

        usage = getattr(response, "usage", None)
        tokens_input = int(getattr(usage, "input_tokens", 0) or 0) if usage else 0
        tokens_output = int(getattr(usage, "output_tokens", 0) or 0) if usage else 0

        text_blocks = [
            getattr(block, "text", "")
            for block in getattr(response, "content", [])
            if getattr(block, "type", None) == "text"
        ]
        joined = "\n".join(t for t in text_blocks if t).strip()

        return NarrativeResult(
            text=joined or None,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            model=self.model,
            prompt_version=self.NARRATIVE_PROMPT_VERSION,
            error=None if joined else "empty_narrative",
        )

    @staticmethod
    def _build_user_content(
        user_text: str | None, images: list[tuple[str, bytes]]
    ) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for content_type, data in images:
            compressed_data, out_media_type = _compress_image(data, content_type)
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": out_media_type,
                        "data": base64.b64encode(compressed_data).decode("ascii"),
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


def _compress_image(data: bytes, content_type: str) -> tuple[bytes, str]:
    """Redimensiona longest-side ≤ 1024px + JPEG q=75.

    Reduz drasticamente o token count (imagens grandes hoje custam 5-11K
    input tokens; após compressão fica em 500-1500). Se algo falhar,
    devolve os bytes originais e o content_type original — melhor mandar
    grande do que não mandar.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            needs_resize = max(width, height) > _IMAGE_MAX_SIDE
            already_jpeg = content_type == "image/jpeg"
            if not needs_resize and already_jpeg:
                return data, content_type
            img.load()
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            if needs_resize:
                img.thumbnail((_IMAGE_MAX_SIDE, _IMAGE_MAX_SIDE))
            buf = io.BytesIO()
            img.save(
                buf,
                format="JPEG",
                quality=_IMAGE_JPEG_QUALITY,
                optimize=True,
            )
            return buf.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError) as exc:
        logger.warning(
            "image_compression_failed",
            extra={
                "event": "anthropic_image_compression",
                "err": type(exc).__name__,
            },
        )
        return data, content_type


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


def _find_tool_use_id(response: Any) -> str | None:
    for block in getattr(response, "content", []):
        if getattr(block, "type", None) == "tool_use":
            return getattr(block, "id", None)
    return None


def _clean_content_for_retry(content: Any) -> list[dict[str, Any]]:
    """Devolve os blocos de resposta em formato aceitável para reenviar
    como `assistant` na próxima chamada.

    O SDK anexa metadata interna (ex.: `caller`) nos blocos de `tool_use`
    que a API rejeita com HTTP 400 (Haiku 4.5 é estrito quanto a isso).
    Aqui mantemos só os campos que compõem o contrato do endpoint:
    `type`, `id`, `name`, `input` para `tool_use`; `type`, `text` para
    blocos de texto.
    """
    cleaned: list[dict[str, Any]] = []
    for block in content or []:
        btype = getattr(block, "type", None)
        if btype == "tool_use":
            cleaned.append(
                {
                    "type": "tool_use",
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}),
                }
            )
        elif btype == "text":
            cleaned.append({"type": "text", "text": getattr(block, "text", "")})
    return cleaned


@lru_cache
def get_anthropic_client() -> AnthropicClient:
    s = get_settings()
    return AnthropicClient(
        api_key=s.anthropic_api_key,
        model=s.anthropic_model,
        fallback_model=s.anthropic_fallback_model,
        max_tokens=s.anthropic_max_tokens,
        temperature=s.anthropic_temperature,
    )
