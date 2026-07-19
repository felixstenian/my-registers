"""Aliases pt-BR/EN → canonical activity_type (regressão do bug 0 kcal)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord
from app.schemas.llm import LLMEnvelope
from app.services.activity import ActivityService
from app.services.activity_calculator import ActivityCalculator


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("corrida", "cardio_run"),
        ("Correr", "cardio_run"),
        ("running", "cardio_run"),
        ("run", "cardio_run"),
        ("caminhada", "cardio_walk"),
        ("walk", "cardio_walk"),
        ("bicicleta", "bike"),
        ("ciclismo", "bike"),
        ("natação", "swim"),
        ("nadar", "swim"),
        ("musculação", "strength"),
        ("academia", "strength"),
        ("hiit", "cardio"),
        ("esteira", "cardio"),
        ("elíptico", "cardio"),
        ("já_canonical_cardio_run", "ja_canonical_cardio_run"),  # não modifica
    ],
)
def test_canonicalize(raw: str, expected: str):
    assert ActivityCalculator.canonicalize(raw) == expected


def test_lookup_met_accepts_pt_br_alias():
    """Regressão: LLM manda 'corrida' e obtemos MET 8.3 (moderate)."""
    assert ActivityCalculator.lookup_met("corrida", "moderate") == Decimal("8.3")
    assert ActivityCalculator.lookup_met("Corri", "light") == Decimal("6.0")
    assert ActivityCalculator.lookup_met("caminhada", "moderate") == Decimal("3.8")


def test_compute_with_pt_br_activity_type():
    """Regressão do bug reportado: 40 min corrida moderada + 65 kg → 359.67 kcal."""
    result = ActivityCalculator.compute(
        activity_type="corrida",  # pt-BR livre, não canonical
        intensity="moderate",
        duration_minutes=Decimal("40"),
        weight_kg=Decimal("65"),
    )
    assert result.kcal_burned == Decimal("359.67")
    assert result.met_value == Decimal("8.3")
    assert result.reasons == []


@pytest.mark.asyncio
async def test_activity_service_persists_kcal_when_pt_br_type(db_session: AsyncSession, admin_user):
    """End-to-end no service: LLM manda activity_type='corrida', service
    persiste kcal correto (não zero)."""
    admin_user.weight_kg = Decimal("65")
    from datetime import UTC, datetime

    from app.repositories.day_log import DayLogRepository

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    await db_session.commit()

    envelope = LLMEnvelope.model_validate(
        {
            "intent": "log_activity",
            "confidence": 0.9,
            "user_text_summary": "Corrida.",
            "needs_clarification": False,
            "activity": {
                "detected_name": "corrida",
                "activity_type": "corrida",  # pt-BR livre
                "duration_minutes": 40,
                "distance_km": None,
                "intensity": "moderate",
                "confidence": 0.9,
            },
        }
    )
    await ActivityService(db_session).create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    record = (await db_session.execute(select(ActivityRecord))).scalar_one()
    assert record.kcal_burned == Decimal("359.67")
    assert record.met_value == Decimal("8.3")
