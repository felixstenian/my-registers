"""Fallback do run_processor_in_background quando MessageProcessor.process
levanta exceção inesperada.

Regressão do bug: se qualquer service (ex.: MealService, snapshot recompute,
serviço de resumo) levantar exceção não capturada dentro de
`MessageProcessor.process()`, a transação é rollbacked e NENHUMA assistant
message é criada. O usuário fica preso ao "digitando"; nem refresh resolve.

Contrato garantido pelo fallback: **sempre** existe uma assistant message
para cada user message processada, mesmo quando o pipeline falha.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Message, User
from app.services.chat import ChatService
from app.services.message_processor import (
    _FALLBACK_LLM_ERROR,
    run_processor_in_background,
)

pytestmark = pytest.mark.asyncio


class ExplodingAnthropic:
    """Simula falha inesperada no pipeline (não é um erro estruturado do
    LLMCallResult — é uma exceção Python que não deveria escapar)."""

    is_configured = True
    model = "fake-exploding"

    async def call_record_intent(self, **_kwargs):
        raise RuntimeError("simulated pipeline failure")


class NoopStorage:
    async def get_object(self, _key):  # pragma: no cover
        return b""


async def test_fallback_assistant_message_created_on_exception(
    admin_user: User, test_engine, db_session: AsyncSession, fake_storage
):
    """Se `processor.process()` explode, o wrapper cria um assistant amigável
    em NOVA sessão — o usuário sempre vê algo."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    # Cria a user message (que será processada) via ChatService.
    chat = ChatService(db_session)
    user_message = await chat.post_user_message(
        user=admin_user, text="add 100g de aveia", media_ids=[]
    )
    await db_session.commit()

    # Roda o background task com um cliente que explode.
    await run_processor_in_background(
        user_message.id,
        session_factory=Session,
        anthropic_client=ExplodingAnthropic(),  # type: ignore[arg-type]
        storage=fake_storage,
    )

    # Uma nova sessão deve ver o assistant message do fallback.
    async with Session() as verify:
        messages = list(
            (
                await verify.execute(select(Message).where(Message.user_id == admin_user.id))
            ).scalars()
        )

    assert len(messages) == 2  # user + fallback assistant
    assistant = next(m for m in messages if m.role == "assistant")
    assert assistant.content == _FALLBACK_LLM_ERROR
    assert assistant.llm_intent == "unknown"
    assert assistant.raw_llm_response == {"error": "background_processor_failed"}


async def test_fallback_uses_new_session_after_rollback(
    admin_user: User, test_engine, db_session: AsyncSession, fake_storage
):
    """Regressão: se o rollback fecha a sessão original, o fallback
    precisa abrir uma nova para conseguir persistir."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    chat = ChatService(db_session)
    user_message = await chat.post_user_message(user=admin_user, text="oi", media_ids=[])
    await db_session.commit()

    await run_processor_in_background(
        user_message.id,
        session_factory=Session,
        anthropic_client=ExplodingAnthropic(),  # type: ignore[arg-type]
        storage=fake_storage,
    )

    async with Session() as verify:
        assistants = list(
            (
                await verify.execute(
                    select(Message).where(
                        Message.user_id == admin_user.id,
                        Message.role == "assistant",
                    )
                )
            ).scalars()
        )
    # Exatamente um assistant — nem 0 (fallback falhou), nem 2 (fallback rodou
    # duas vezes por bug de retry).
    assert len(assistants) == 1
    assert assistants[0].day_log_id == user_message.day_log_id
