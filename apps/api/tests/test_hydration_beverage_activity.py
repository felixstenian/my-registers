"""SP-40..42, SP-50..52, SP-60..64 — services de hidratação, bebida e atividade.

INV-2/INV-3: água e bebida calórica em tabelas distintas (não há como
misturar por engano). INV-10: audit_event por mutação.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    ActivityRecord,
    AuditEvent,
    BeverageRecord,
    WaterRecord,
)
from app.schemas.llm import LLMEnvelope
from app.services.activity import ActivityService, WeightRequired
from app.services.beverage import BeverageService
from app.services.hydration import HydrationService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user_id):
    from app.repositories.day_log import DayLogRepository

    dl = await DayLogRepository(session).get_or_create(
        user_id=user_id, log_date=datetime.now(UTC).date()
    )
    await session.commit()
    return dl


def _envelope(**overrides) -> LLMEnvelope:
    base: dict = {
        "intent": "log_water",
        "confidence": 0.9,
        "user_text_summary": "Registro de líquido/atividade.",
        "needs_clarification": False,
    }
    base.update(overrides)
    return LLMEnvelope.model_validate(base)


# ---------------------------------------------------------------------------
# HydrationService — SP-40, SP-41, SP-42, INV-2
# ---------------------------------------------------------------------------


async def test_sp40_water_records_volume(db_session: AsyncSession, admin_user):
    dl = await _day_log(db_session, admin_user.id)
    service = HydrationService(db_session)
    envelope = _envelope(intent="log_water", water={"volume_ml": 500, "confidence": 0.95})
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    assert result.record.volume_ml == 500
    assert result.record.user_id == admin_user.id
    # Schema não tem kcal em water_records (INV-2 estrutural).
    assert not hasattr(result.record, "kcal")


async def test_sp41_rejects_water_intent_when_summary_hints_beverage(
    db_session: AsyncSession, admin_user
):
    """SP-41 / Art. IV §14: log_water com resumo contendo 'cafe'/'leite'/etc
    é rejeitado (não persiste). O processor traduz em clarify."""
    dl = await _day_log(db_session, admin_user.id)
    service = HydrationService(db_session)
    envelope = _envelope(
        intent="log_water",
        user_text_summary="Usuário tomou um café expresso.",
        water={"volume_ml": 50, "confidence": 0.9},
    )
    with pytest.raises(ValidationAppError) as exc:
        await service.create_from_llm(
            user=admin_user,
            day_log_id=dl.id,
            message_id=None,
            envelope=envelope,
        )
    assert exc.value.code == "water_intent_rejected"

    # Nada persistido.
    rows = list((await db_session.execute(select(WaterRecord))).scalars())
    assert rows == []


async def test_hydration_grava_audit_event(db_session: AsyncSession, admin_user):
    dl = await _day_log(db_session, admin_user.id)
    service = HydrationService(db_session)
    envelope = _envelope(intent="log_water", water={"volume_ml": 250, "confidence": 0.9})
    await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    assert len(events) == 1
    assert events[0].entity_type == "water_record"
    assert events[0].action == "create"
    assert events[0].actor == "llm"


# ---------------------------------------------------------------------------
# BeverageService — SP-50, SP-51, SP-52, INV-3
# ---------------------------------------------------------------------------


async def test_sp50_beverage_with_catalog_hit(db_session: AsyncSession, admin_user):
    """SP-50: café/refrigerante/etc → beverage_records com kcal do catálogo."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = BeverageService(db_session, catalog)

    envelope = _envelope(
        intent="log_beverage",
        beverage={
            "detected_name": "leite integral",
            "brand": None,
            "volume_ml": 200,
            "beverage_kind": "other",
            "confidence": 0.9,
        },
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    assert result.record.catalog_ref_id is not None
    # leite 200ml × 57 kcal/100ml = 114 (seed TBCA: leite_integral = 57 kcal/100ml)
    assert result.record.kcal == Decimal("114.00")
    assert result.record.protein_g > 0
    assert result.record.volume_ml == 200


async def test_sp52_beverage_no_catalog_zeros(db_session: AsyncSession, admin_user):
    """SP-52: bebida sem catálogo → macros zerados + warning no_catalog_hit."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = BeverageService(db_session, catalog)

    envelope = _envelope(
        intent="log_beverage",
        beverage={
            "detected_name": "kombucha artesanal casa",
            "brand": None,
            "volume_ml": 300,
            "beverage_kind": "other",
            "confidence": 0.85,
        },
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    assert result.record.catalog_ref_id is None
    assert result.record.kcal == Decimal("0")
    assert result.record.needs_confirmation is True
    assert any(w["code"] == "no_catalog_hit" for w in result.warnings)


async def test_beverage_never_lands_in_water_table(db_session: AsyncSession, admin_user):
    """INV-3 estrutural: bebida calórica só entra em beverage_records."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = BeverageService(db_session, catalog)

    envelope = _envelope(
        intent="log_beverage",
        beverage={
            "detected_name": "café",
            "brand": None,
            "volume_ml": 100,
            "beverage_kind": "other",
            "confidence": 0.9,
        },
    )
    await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    water_rows = list((await db_session.execute(select(WaterRecord))).scalars())
    beverage_rows = list((await db_session.execute(select(BeverageRecord))).scalars())
    assert water_rows == []
    assert len(beverage_rows) == 1


# ---------------------------------------------------------------------------
# ActivityService — SP-60, SP-61, SP-62, SP-63, SP-64
# ---------------------------------------------------------------------------


async def _admin_with_weight(db_session: AsyncSession, admin_user, weight_kg):
    admin_user.weight_kg = Decimal(str(weight_kg))
    await db_session.commit()
    return admin_user


async def test_sp60_activity_computes_kcal_burned(db_session: AsyncSession, admin_user):
    """SP-60: corrida 40min moderada + peso → kcal_burned deterministicamente."""
    user = await _admin_with_weight(db_session, admin_user, 78)
    dl = await _day_log(db_session, user.id)
    service = ActivityService(db_session)

    envelope = _envelope(
        intent="log_activity",
        activity={
            "detected_name": "corrida",
            "activity_type": "cardio_run",
            "duration_minutes": 40,
            "distance_km": None,
            "intensity": "moderate",
            "confidence": 0.9,
        },
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    assert result.record.met_value == Decimal("8.3")
    # 8.3 × 78 × 40/60 = 431.60
    assert result.record.kcal_burned == Decimal("431.60")
    assert result.record.calc_method == "mets_body_weight"
    assert result.record.duration_minutes == Decimal("40.00")


async def test_sp61_missing_weight_raises_weight_required(db_session: AsyncSession, admin_user):
    """SP-61: users.weight_kg=null → não persiste; service levanta WeightRequired."""
    dl = await _day_log(db_session, admin_user.id)
    service = ActivityService(db_session)

    envelope = _envelope(
        intent="log_activity",
        activity={
            "detected_name": "corrida",
            "activity_type": "cardio_run",
            "duration_minutes": 30,
            "distance_km": None,
            "intensity": "moderate",
            "confidence": 0.9,
        },
    )
    with pytest.raises(WeightRequired):
        await service.create_from_llm(
            user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
        )

    rows = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert rows == []


async def test_sp62_strength_unknown_intensity_uses_moderate_met(
    db_session: AsyncSession, admin_user
):
    """SP-62: musculação sem intensidade → default moderate=5.0."""
    user = await _admin_with_weight(db_session, admin_user, 80)
    dl = await _day_log(db_session, user.id)
    service = ActivityService(db_session)

    envelope = _envelope(
        intent="log_activity",
        activity={
            "detected_name": "musculação",
            "activity_type": "strength",
            "duration_minutes": 60,
            "distance_km": None,
            "intensity": "unknown",
            "confidence": 0.6,
        },
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    # met usado no cálculo é 5.0 (moderate); o registro guarda 'unknown' original.
    assert result.record.met_value == Decimal("5.0")
    assert result.record.intensity == "unknown"
    # 5 × 80 × 1 = 400
    assert result.record.kcal_burned == Decimal("400.00")


async def test_sp64_audit_and_calc_method_stored(db_session: AsyncSession, admin_user):
    """SP-64: met_value + calc_method persistidos para recomputo futuro."""
    user = await _admin_with_weight(db_session, admin_user, 75)
    dl = await _day_log(db_session, user.id)
    service = ActivityService(db_session)

    envelope = _envelope(
        intent="log_activity",
        activity={
            "detected_name": "caminhada",
            "activity_type": "cardio_walk",
            "duration_minutes": 30,
            "distance_km": None,
            "intensity": "light",
            "confidence": 0.85,
        },
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    assert result.record.met_value == Decimal("2.8")
    assert result.record.calc_method == "mets_body_weight"

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    activity_events = [e for e in events if e.entity_type == "activity_record"]
    assert len(activity_events) == 1
    assert activity_events[0].actor == "llm"
