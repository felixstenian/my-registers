"""MessageProcessor — worker que roda em `BackgroundTasks` após POST /chat/messages.

Fluxo (SP-13, SP-14):
1. Carrega a mensagem do usuário e a mídia anexada.
2. Baixa os bytes de cada media do MinIO (para envio base64 à Anthropic).
3. Chama `AnthropicClient.call_record_intent` (com retry semântico embutido).
4. Se o envelope volta válido → passa pelo `IntentDispatcher`.
   - `clarify` / `unknown` → cria `messages(role='assistant', content=...)`.
   - `log_food` etc. → `IntentNotImplemented` (Fase 4+); vira pedido genérico
     de reformulação enquanto essas fases não chegam.
5. Se a chamada falhou (timeout, 5xx, validation exhausted) → cria mensagem
   amigável e grava `raw_llm_response.error` (SP-14).

O background task cria sua própria `AsyncSession` porque a sessão da
request original já fechou quando ele executa.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.integrations.anthropic.client import AnthropicClient, LLMCallResult
from app.integrations.storage.minio import MinioStorage
from app.models import Media, Message, MessageMedia
from app.repositories.message import MessageRepository
from app.services.intent_dispatcher import (
    DispatchResult,
    IntentDispatcher,
    IntentNotImplemented,
)

logger = logging.getLogger("app.message_processor")

_FALLBACK_LLM_ERROR = (
    "Não consegui interpretar sua mensagem agora. Pode reformular?"
)
_FALLBACK_NOT_IMPLEMENTED = (
    "Recebi sua mensagem, mas o registro dessa categoria ainda não está "
    "disponível — está previsto para uma fase futura."
)


class MessageProcessor:
    def __init__(
        self,
        *,
        session: AsyncSession,
        anthropic: AnthropicClient,
        storage: MinioStorage,
    ) -> None:
        self.session = session
        self.anthropic = anthropic
        self.storage = storage
        self.messages = MessageRepository(session)
        self.dispatcher = IntentDispatcher()

    async def process(self, message_id: uuid.UUID) -> Message | None:
        stmt = select(Message).where(Message.id == message_id)
        user_message = (await self.session.execute(stmt)).scalar_one_or_none()
        if user_message is None or user_message.role != "user":
            logger.warning(
                "process_missing_user_message",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
            return None

        images = await self._load_media(message_id)

        result = await self.anthropic.call_record_intent(
            user_text=user_message.content,
            images=images,
        )

        if result.error == "no_queued_result":
            # Sentinela usado pelo FakeAnthropicClient nos testes que exercem
            # apenas o pipeline de chat (SP-10..SP-12) e não configuram
            # resposta da LLM. Em produção esse code nunca acontece.
            logger.info(
                "processor_skipped_no_queued_result",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
            return None

        if result.error is not None or result.envelope is None:
            return await self._record_error(user_message, result)

        try:
            dispatch = self.dispatcher.dispatch(result.envelope)
        except IntentNotImplemented as exc:
            logger.info(
                "intent_not_implemented",
                extra={"event": "intent_dispatch", "intent": exc.intent},
            )
            return await self._record_not_implemented(user_message, result, exc.intent)

        return await self._record_success(user_message, result, dispatch)

    async def _load_media(
        self, message_id: uuid.UUID
    ) -> list[tuple[str, bytes]]:
        stmt = (
            select(Media)
            .join(MessageMedia, MessageMedia.media_id == Media.id)
            .where(MessageMedia.message_id == message_id)
        )
        rows = list((await self.session.execute(stmt)).scalars())
        images: list[tuple[str, bytes]] = []
        for media in rows:
            try:
                data = await self.storage.get_object(media.storage_key)
            except Exception as exc:  # noqa: BLE001 — não bloquear a mensagem
                logger.warning(
                    "media_download_failed",
                    extra={
                        "event": "message_processor",
                        "media_id": str(media.id),
                        "err": type(exc).__name__,
                    },
                )
                continue
            images.append((media.content_type, data))
        return images

    async def _record_success(
        self,
        user_message: Message,
        result: LLMCallResult,
        dispatch: DispatchResult,
    ) -> Message:
        raw = _pack_raw(result)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=dispatch.content,
            llm_intent=dispatch.llm_intent,
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=dispatch.llm_confidence,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _record_error(
        self, user_message: Message, result: LLMCallResult
    ) -> Message:
        raw = _pack_raw(result)
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=_FALLBACK_LLM_ERROR,
            llm_intent="unknown",
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )

    async def _record_not_implemented(
        self, user_message: Message, result: LLMCallResult, intent: str
    ) -> Message:
        raw = _pack_raw(result)
        raw["dispatch"] = {"not_implemented": intent}
        return await self.messages.create(
            user_id=user_message.user_id,
            day_log_id=user_message.day_log_id,
            role="assistant",
            content=_FALLBACK_NOT_IMPLEMENTED,
            llm_intent=intent,
            llm_model=result.model,
            llm_prompt_version=result.prompt_version,
            llm_confidence=result.envelope.confidence if result.envelope else None,
            raw_llm_response=raw,
            tokens_input=result.tokens_input,
            tokens_output=result.tokens_output,
        )


def _pack_raw(result: LLMCallResult) -> dict[str, Any]:
    packed = asdict(result)
    # `envelope` é um BaseModel e não é JSON-serializable por asdict.
    packed["envelope"] = (
        result.envelope.model_dump(mode="json") if result.envelope else None
    )
    return packed


async def run_processor_in_background(
    message_id: uuid.UUID,
    *,
    session_factory: Callable[[], AsyncSession],
    anthropic_client: AnthropicClient,
    storage: MinioStorage,
) -> None:
    """Wrapper para FastAPI `BackgroundTasks`: sessão dedicada via factory.

    `session_factory` é injetada pela rota (dep FastAPI) para permitir que
    testes usem o mesmo engine da sessão de request (evita 'attached to a
    different loop' quando o event loop do teste difere do que criou o
    engine module-level).
    """
    async with session_factory() as session:
        processor = MessageProcessor(
            session=session, anthropic=anthropic_client, storage=storage
        )
        try:
            await processor.process(message_id)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception(
                "background_processor_failed",
                extra={"event": "message_processor", "message_id": str(message_id)},
            )
