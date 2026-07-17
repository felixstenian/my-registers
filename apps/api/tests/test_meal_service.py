"""SP-20..SP-26 + audit — MealService via LLMEnvelope."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, DayLog, FoodItem, FoodRecord
from app.schemas.llm import LLMEnvelope
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user_id) -> DayLog:
    from app.repositories.day_log import DayLogRepository

    dl = await DayLogRepository(session).get_or_create(
        user_id=user_id, log_date=datetime.now(UTC).date()
    )
    await session.commit()
    return dl


def _envelope(items: list[dict], **overrides) -> LLMEnvelope:
    data: dict = {
        "intent": "log_food",
        "confidence": 0.9,
        "user_text_summary": "Registro de comida.",
        "needs_clarification": False,
        "meal_slot": "lunch",
        "food_items": items,
    }
    data.update(overrides)
    return LLMEnvelope.model_validate(data)


async def test_sp20_explicit_quantities_resolve_from_catalog(
    db_session: AsyncSession, admin_user
):
    """SP-20: 3 itens com quantidade explícita viram 1 food_records + 3
    food_items com kcal/macros vindos do catálogo."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "arroz branco cozido",
                "normalized_name": "arroz_branco_cozido",
                "quantity": 150,
                "unit": "g",
                "grams_estimate": 150,
                "confidence": 0.95,
                "is_estimate": False,
            },
            {
                "detected_name": "feijão preto cozido",
                "normalized_name": "feijao_preto_cozido",
                "quantity": 90,
                "unit": "g",
                "grams_estimate": 90,
                "confidence": 0.9,
                "is_estimate": False,
            },
            {
                "detected_name": "peito de frango grelhado",
                "normalized_name": "peito_de_frango_grelhado",
                "quantity": 180,
                "unit": "g",
                "grams_estimate": 180,
                "confidence": 0.94,
                "is_estimate": False,
            },
        ]
    )

    result = await service.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=envelope,
    )
    await db_session.commit()

    assert result.food_record.meal_slot == "lunch"
    assert len(result.items) == 3
    for item in result.items:
        assert item.catalog_ref_id is not None
        assert item.kcal is not None and item.kcal > 0
        assert not item.needs_confirmation
    # arroz 150g × 124kcal/100 = 186; feijão 90g × 77 = 69.3; frango 180g × 159 = 286.2
    kcal_by_name = {i.normalized_name: i.kcal for i in result.items}
    assert kcal_by_name["arroz_branco_cozido"].compare(186) == 0
    assert kcal_by_name["peito_de_frango_grelhado"].compare(Decimal("286.20")) == 0


async def test_sp21_domestic_unit_marks_estimate_and_low_confidence(
    db_session: AsyncSession, admin_user
):
    """SP-21: 'uma concha de feijão' → is_estimate=True, confidence ≤ 0.7."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "feijão preto cozido",
                "normalized_name": "feijao_preto_cozido",
                "quantity": 1,
                "unit": "concha",
                "grams_estimate": 90,
                "confidence": 0.7,
                "is_estimate": True,
            },
        ]
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    item = result.items[0]
    assert item.is_estimate is True
    assert item.unit == "concha"
    assert item.kcal > 0  # ainda calcula com grams_estimate


async def test_sp23_unknown_item_zeros_and_warning(
    db_session: AsyncSession, admin_user
):
    """SP-23: alimento não no catálogo → macros zerados + warning
    'no_catalog_hit'."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "sushi de salmão especial casa",
                "normalized_name": "sushi_salmao_especial",
                "quantity": 6,
                "unit": "unidade",
                "grams_estimate": 180,
                "confidence": 0.8,
                "is_estimate": False,
            }
        ]
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    item = result.items[0]
    assert item.catalog_ref_id is None
    assert item.kcal == 0
    assert item.needs_confirmation is True  # sem catálogo dispara flag
    assert any(w["code"] == "no_catalog_hit" for w in result.warnings)


async def test_sp24_low_confidence_flags_needs_confirmation(
    db_session: AsyncSession, admin_user
):
    """SP-24: confidence < 0.5 → needs_confirmation=True."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "arroz",
                "normalized_name": "arroz",
                "quantity": 150,
                "unit": "g",
                "grams_estimate": 150,
                "confidence": 0.3,
                "is_estimate": False,
            }
        ]
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    item = result.items[0]
    assert item.confidence.compare(Decimal("0.3")) == 0
    assert item.needs_confirmation is True
    assert any(w["code"] == "low_confidence_item" for w in result.warnings)


async def test_sp26_unspecified_meal_slot_defaults(
    db_session: AsyncSession, admin_user
):
    """SP-26: envelope sem meal_slot → 'unspecified'."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "arroz",
                "normalized_name": "arroz",
                "grams_estimate": 100,
                "confidence": 0.9,
                "is_estimate": False,
            }
        ],
        meal_slot=None,
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    assert result.food_record.meal_slot == "unspecified"


async def test_audit_event_recorded_on_create(
    db_session: AsyncSession, admin_user
):
    """INV-10 (Const. Art. III §11): create de food_record grava audit_event."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "arroz",
                "normalized_name": "arroz",
                "grams_estimate": 100,
                "confidence": 0.9,
                "is_estimate": False,
            }
        ]
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    assert len(events) == 1
    event = events[0]
    assert event.entity_type == "food_record"
    assert event.entity_id == result.food_record.id
    assert event.action == "create"
    assert event.actor == "llm"
    assert event.after and "meal_slot" in event.after


async def test_ownership_isolation(
    db_session: AsyncSession, admin_user
):
    """Const. Art. V §21: food_records fica só com o próprio user_id."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)

    envelope = _envelope(
        [
            {
                "detected_name": "arroz",
                "normalized_name": "arroz",
                "grams_estimate": 100,
                "confidence": 0.9,
                "is_estimate": False,
            }
        ]
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    records = list((await db_session.execute(select(FoodRecord))).scalars())
    items = list((await db_session.execute(select(FoodItem))).scalars())
    assert all(r.user_id == admin_user.id for r in records)
    assert all(i.food_record_id == result.food_record.id for i in items)
