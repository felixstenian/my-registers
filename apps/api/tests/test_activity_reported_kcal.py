"""Prioridade do kcal_burned_reported (print de smartwatch/app) sobre o
cálculo por MET × peso. Fecha o gap reportado no PR #6."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord, Message, User
from app.schemas.llm import LLMEnvelope
from app.services.activity import ActivityService, WeightRequired

pytestmark = pytest.mark.asyncio


async def _day_log(session: AsyncSession, user_id):
    from app.repositories.day_log import DayLogRepository

    dl = await DayLogRepository(session).get_or_create(
        user_id=user_id, log_date=datetime.now(UTC).date()
    )
    await session.commit()
    return dl


def _envelope(**activity_overrides) -> LLMEnvelope:
    base_activity: dict = {
        "detected_name": "corrida",
        "activity_type": "cardio_run",
        "duration_minutes": 45,
        "distance_km": 8.0,
        "intensity": "moderate",
        "confidence": 0.95,
    }
    base_activity.update(activity_overrides)
    return LLMEnvelope.model_validate(
        {
            "intent": "log_activity",
            "confidence": 0.95,
            "user_text_summary": "Print de smartwatch.",
            "needs_clarification": False,
            "activity": base_activity,
        }
    )


# ---------------------------------------------------------------------------
# Service-level
# ---------------------------------------------------------------------------


async def test_reported_kcal_wins_over_met_calculation(db_session: AsyncSession, admin_user: User):
    """Print de smartwatch com 520 kcal: registra 520 (não 373 do MET)."""
    admin_user.weight_kg = Decimal("65")
    dl = await _day_log(db_session, admin_user.id)

    envelope = _envelope(kcal_burned_reported=520)
    await ActivityService(db_session).create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    record = (await db_session.execute(select(ActivityRecord))).scalar_one()
    assert record.kcal_burned == Decimal("520")
    assert record.calc_method == "user_manual"
    # met_value ainda é gravado como contexto (se o tipo bater na tabela).
    assert record.met_value == Decimal("8.3")


async def test_reported_kcal_bypasses_weight_required(db_session: AsyncSession, admin_user: User):
    """SP-61 não aplica se o valor veio do dispositivo — dispensa peso."""
    # weight_kg fica None de propósito
    assert admin_user.weight_kg is None
    dl = await _day_log(db_session, admin_user.id)

    envelope = _envelope(kcal_burned_reported=420)
    await ActivityService(db_session).create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    record = (await db_session.execute(select(ActivityRecord))).scalar_one()
    assert record.kcal_burned == Decimal("420")
    assert record.calc_method == "user_manual"


async def test_missing_reported_and_missing_weight_still_raises(
    db_session: AsyncSession, admin_user: User
):
    """Sem valor reportado E sem peso → WeightRequired (fluxo Fase 5 original)."""
    dl = await _day_log(db_session, admin_user.id)

    envelope = _envelope()  # sem kcal_burned_reported
    with pytest.raises(WeightRequired):
        await ActivityService(db_session).create_from_llm(
            user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
        )


async def test_reported_kcal_zero_treated_as_reported(db_session: AsyncSession, admin_user: User):
    """Edge case: dispositivo reporta 0 kcal (não é o mesmo que 'sem valor')."""
    admin_user.weight_kg = Decimal("65")
    dl = await _day_log(db_session, admin_user.id)

    envelope = _envelope(kcal_burned_reported=0)
    await ActivityService(db_session).create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    record = (await db_session.execute(select(ActivityRecord))).scalar_one()
    assert record.kcal_burned == Decimal("0")
    assert record.calc_method == "user_manual"


# ---------------------------------------------------------------------------
# End-to-end via chat
# ---------------------------------------------------------------------------


async def test_end_to_end_smartwatch_screenshot(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Usuário anexa print de smartwatch com kcal já calculado → registra o
    valor do dispositivo, mesmo sem peso configurado."""
    await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_activity",
                confidence=0.95,
                user_text_summary="Print de smartwatch, corrida 45min.",
                needs_clarification=False,
                activity={
                    "detected_name": "corrida (Garmin)",
                    "activity_type": "cardio_run",
                    "duration_minutes": 45,
                    "distance_km": 8.0,
                    "intensity": "moderate",
                    "confidence": 0.95,
                    "kcal_burned_reported": 520,
                },
            )
        )
    )
    resp = await client.post("/chat/messages", json={"text": "corrida foto anexada"})
    assert resp.status_code == 202

    record = (await db_session.execute(select(ActivityRecord))).scalar_one()
    assert record.kcal_burned == Decimal("520")
    assert record.calc_method == "user_manual"

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert "520" in assistant.content
    assert "informado pelo dispositivo" in assistant.content
