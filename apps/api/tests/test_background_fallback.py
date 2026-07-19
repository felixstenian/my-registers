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


class OrphanAnthropic:
    """Explode DEPOIS de já ter chamado o LLM — variante que simula erro
    tardio em service downstream (ex.: recompute, WeeklyReportService)."""

    is_configured = True
    model = "fake-orphan"

    async def call_record_intent(self, **_kwargs):
        from app.integrations.anthropic.client import LLMCallResult
        from app.schemas.llm import LLMEnvelope

        envelope = LLMEnvelope.model_validate(
            {
                "intent": "log_food",
                "confidence": 0.9,
                "user_text_summary": ".",
                "needs_clarification": False,
                "meal_slot": "breakfast",
                # payload inválido para o schema do FoodItemIn: `grams_estimate`
                # existe mas `detected_name` está OK; falha vai vir do service.
                "food_items": [
                    {
                        "detected_name": "aveia",
                        "normalized_name": "aveia",
                        "grams_estimate": 100,
                        "confidence": 0.9,
                        "is_estimate": False,
                    }
                ],
            }
        )
        return LLMCallResult(
            envelope=envelope,
            raw_tool_input=envelope.model_dump(mode="json"),
            tokens_input=10,
            tokens_output=5,
            model=self.model,
            prompt_version="system_v2",
        )


async def test_fallback_covers_downstream_service_failure(
    admin_user: User, test_engine, db_session: AsyncSession, fake_storage
):
    """Envelope válido, mas o service downstream (MealService) explode porque
    o day_log_id não existe (edge case artificial). Fallback é acionado.
    """
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    chat = ChatService(db_session)
    user_message = await chat.post_user_message(
        user=admin_user, text="add 100g de aveia", media_ids=[]
    )
    # Force day_log_id inválido para causar exceção downstream.
    import uuid as _uuid

    user_message.day_log_id = _uuid.uuid4()
    await db_session.commit()

    await run_processor_in_background(
        user_message.id,
        session_factory=Session,
        anthropic_client=OrphanAnthropic(),  # type: ignore[arg-type]
        storage=fake_storage,
    )

    async with Session() as verify:
        messages = list(
            (
                await verify.execute(select(Message).where(Message.user_id == admin_user.id))
            ).scalars()
        )
    assistants = [m for m in messages if m.role == "assistant"]
    assert len(assistants) == 1
    assert assistants[0].content == _FALLBACK_LLM_ERROR
