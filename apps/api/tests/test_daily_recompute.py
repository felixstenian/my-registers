"""INV-4 / SP-90 (parcial) — DailyRecomputeService reconstrói from-scratch."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.schemas.llm import LLMEnvelope
from app.services.daily_recompute import DailyRecomputeService
from app.services.meal import MealService

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


def _envelope(items: list[dict]) -> LLMEnvelope:
    return LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.9,
            "user_text_summary": "Registro.",
            "needs_clarification": False,
            "meal_slot": "lunch",
            "food_items": items,
        }
    )


async def test_snapshot_sums_food_items(
    db_session: AsyncSession, admin_user
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    meal = MealService(db_session, catalog)
    recompute = DailyRecomputeService(db_session)

    await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "arroz",
                    "normalized_name": "arroz_branco_cozido",
                    "grams_estimate": 150,
                    "confidence": 0.9,
                    "is_estimate": False,
                },
                {
                    "detected_name": "frango",
                    "normalized_name": "peito_de_frango_grelhado",
                    "grams_estimate": 180,
                    "confidence": 0.9,
                    "is_estimate": False,
                },
            ]
        ),
    )
    result = await recompute.recompute(dl.id)
    await db_session.commit()

    snap = result.snapshot
    # arroz 150g × 124 = 186; frango 180g × 159 = 286.2 → 472.2
    assert snap.kcal_in.compare(Decimal("472.20")) == 0
    assert snap.kcal_balance.compare(Decimal("472.20")) == 0
    assert snap.version == 1


async def test_recompute_is_idempotent_and_increments_version(
    db_session: AsyncSession, admin_user
):
    """INV-4: mesmos itens → mesmos totais, mas version++ a cada chamada."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    meal = MealService(db_session, catalog)
    recompute = DailyRecomputeService(db_session)

    await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "arroz",
                    "normalized_name": "arroz_branco_cozido",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ]
        ),
    )
    r1 = await recompute.recompute(dl.id)
    v1 = r1.snapshot.version  # capturar antes: identity map faz r1.snapshot == r2.snapshot
    k1 = r1.snapshot.kcal_in
    r2 = await recompute.recompute(dl.id)
    await db_session.commit()

    assert r2.snapshot.kcal_in == k1
    assert r2.snapshot.version == v1 + 1


async def test_recompute_new_items_reflect_immediately(
    db_session: AsyncSession, admin_user
):
    """SP-20: snapshot recompute após novos itens; sem cache stale."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    meal = MealService(db_session, catalog)
    recompute = DailyRecomputeService(db_session)

    await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "arroz",
                    "normalized_name": "arroz_branco_cozido",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ]
        ),
    )
    r1 = await recompute.recompute(dl.id)
    first_kcal = r1.snapshot.kcal_in

    await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "frango",
                    "normalized_name": "peito_de_frango_grelhado",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ]
        ),
    )
    r2 = await recompute.recompute(dl.id)
    await db_session.commit()

    assert r2.snapshot.kcal_in > first_kcal
    # totais devem bater com soma dos dois: 124 + 159 = 283
    assert r2.snapshot.kcal_in.compare(283) == 0


async def test_deleted_items_excluded_from_snapshot(
    db_session: AsyncSession, admin_user
):
    """INV-4: soft delete no food_item some do snapshot na próxima recompute."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    meal = MealService(db_session, catalog)
    recompute = DailyRecomputeService(db_session)

    result = await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "arroz",
                    "normalized_name": "arroz_branco_cozido",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ]
        ),
    )
    r1 = await recompute.recompute(dl.id)
    assert r1.snapshot.kcal_in > 0

    # soft delete
    result.items[0].deleted_at = datetime.now(UTC)
    await db_session.flush()
    r2 = await recompute.recompute(dl.id)
    await db_session.commit()
    assert r2.snapshot.kcal_in == Decimal("0")


async def test_warnings_include_missing_catalog_and_needs_confirmation(
    db_session: AsyncSession, admin_user
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user.id)
    catalog = LocalTBCACatalog(db_session)
    meal = MealService(db_session, catalog)
    recompute = DailyRecomputeService(db_session)

    await meal.create_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_envelope(
            [
                {
                    "detected_name": "prato exótico",
                    "normalized_name": "prato_exotico_desconhecido",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ]
        ),
    )
    result = await recompute.recompute(dl.id)
    await db_session.commit()
    codes = {w["code"] for w in result.snapshot.warnings}
    assert "no_catalog_hit" in codes
    assert "needs_confirmation" in codes
