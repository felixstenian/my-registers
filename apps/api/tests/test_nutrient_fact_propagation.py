"""SP-163 / INV-14 — NutrientFact propagation.

Ao PATCH um NutrientFact, todos os food_items e beverage_records vivos
que o referenciam devem ter seus macros recomputados. Itens em dias
fechados são pulados (listados em propagation_skipped).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    AuditEvent,
    DailySnapshot,
    FoodItem,
    NutrientFact,
)
from app.repositories.day_log import DayLogRepository

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user, log_date=None):
    if log_date is None:
        log_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=log_date)
    await session.commit()
    return dl


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _create_manual_fact(
    session: AsyncSession,
    user,
    *,
    canonical_name: str = "arroz_branco_cozido",
    kcal: Decimal = Decimal("130"),
    basis: str = "per_100g",
) -> NutrientFact:
    """Create a NutrientFact with source='manual' directly in DB."""
    fact = NutrientFact(
        canonical_name=canonical_name,
        aliases=[canonical_name],
        brand=None,
        source="manual",
        basis=basis,
        verified_by_user=True,
        created_by=user.id,
        kcal=kcal,
        protein_g=Decimal("2.5"),
        carbs_g=Decimal("28"),
        fat_g=Decimal("0.5"),
        fiber_g=Decimal("0.4"),
        sodium_mg=Decimal("1"),
    )
    session.add(fact)
    await session.flush()
    if basis == "per_100ml":
        fact.basis = "per_100ml"
        await session.flush()
    return fact


async def _create_food_item(
    session: AsyncSession, user, dl_id, fact_id, grams=100
) -> FoodItem:
    """Create a FoodItem directly, linked to a specific NutrientFact."""
    from app.models import FoodItem, FoodRecord

    food_record = FoodRecord(
        user_id=user.id,
        day_log_id=dl_id,
        meal_slot="lunch",
        occurred_at=datetime.now(UTC),
    )
    session.add(food_record)
    await session.flush()

    from app.integrations.nutrition.catalog import CatalogHit
    from app.services.nutrition_calculator import NutritionCalculator

    hit = CatalogHit.from_model(await session.get(NutrientFact, fact_id))  # type: ignore[arg-type]
    computed = NutritionCalculator.compute(hit=hit, grams=Decimal(str(grams)), ml=None)

    item = FoodItem(
        food_record_id=food_record.id,
        catalog_ref_id=fact_id,
        detected_name="arroz",
        normalized_name="arroz_branco_cozido",
        grams=Decimal(str(grams)),
        ml=None,
        quantity=None,
        unit="g",
        source="catalog",
        confidence=Decimal("0.9"),
        is_estimate=False,
        needs_confirmation=False,
        kcal=computed.kcal,
        protein_g=computed.protein_g,
        carbs_g=computed.carbs_g,
        fat_g=computed.fat_g,
        fiber_g=computed.fiber_g,
        sodium_mg=computed.sodium_mg,
        calcium_mg=computed.calcium_mg,
        iron_mg=computed.iron_mg,
        potassium_mg=computed.potassium_mg,
    )
    session.add(item)
    await session.flush()
    return item


async def _create_beverage_record(
    session: AsyncSession, user, dl_id, fact_id, volume_ml=200
):
    from app.integrations.nutrition.catalog import CatalogHit
    from app.models import BeverageRecord
    from app.services.nutrition_calculator import NutritionCalculator

    fact = await session.get(NutrientFact, fact_id)
    assert fact is not None
    hit = CatalogHit.from_model(fact)
    computed = NutritionCalculator.compute(
        hit=hit, grams=None, ml=Decimal(str(volume_ml))
    )

    record = BeverageRecord(
        user_id=user.id,
        day_log_id=dl_id,
        occurred_at=datetime.now(UTC),
        detected_name="leite",
        normalized_name="leite_integral",
        brand=None,
        volume_ml=volume_ml,
        source="catalog",
        confidence=Decimal("0.9"),
        is_estimate=False,
        needs_confirmation=False,
        catalog_ref_id=fact_id,
        kcal=computed.kcal,
        protein_g=computed.protein_g,
        carbs_g=computed.carbs_g,
        fat_g=computed.fat_g,
        fiber_g=computed.fiber_g,
        sodium_mg=computed.sodium_mg,
        calcium_mg=computed.calcium_mg,
        iron_mg=computed.iron_mg,
        potassium_mg=computed.potassium_mg,
    )
    session.add(record)
    await session.flush()
    return record


async def test_patch_nutrient_fact_propagates_to_food_items(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-14: PATCH nutrient_fact recomputa macros de food_items vivos."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    fact = await _create_manual_fact(db_session, admin_user, kcal=Decimal("130"))
    item = await _create_food_item(db_session, admin_user, dl.id, fact.id, grams=100)
    await db_session.commit()
    assert item.kcal == Decimal("130.00")

    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 200})
    assert resp.status_code == 200
    body = resp.json()
    assert body["propagated_food_items"] >= 1

    await db_session.refresh(item)
    assert item.kcal == Decimal("200.00")
    assert item.source == "user_corrected"


async def test_patch_nutrient_fact_skips_closed_days(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-14: items in closed days go to propagation_skipped."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    fact = await _create_manual_fact(db_session, admin_user, kcal=Decimal("130"))
    item = await _create_food_item(db_session, admin_user, dl.id, fact.id, grams=100)
    await db_session.commit()
    old_kcal = item.kcal

    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 200})
    assert resp.status_code == 200
    body = resp.json()
    assert body["propagated_food_items"] == 0
    assert len(body["propagation_skipped"]) >= 1
    assert body["propagation_skipped"][0]["reason"] == "day_closed"

    await db_session.refresh(item)
    assert item.kcal == old_kcal


async def test_patch_nutrient_fact_propagates_to_beverages(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-14: PATCH nutrient_fact recomputa beverage_records vivos."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    fact = await _create_manual_fact(
        db_session, admin_user, canonical_name="leite_integral", kcal=Decimal("57"),
        basis="per_100ml",
    )
    record = await _create_beverage_record(
        db_session, admin_user, dl.id, fact.id, volume_ml=200
    )
    await db_session.commit()
    # 57 × 200/100 = 114
    assert record.kcal == Decimal("114.00")

    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 100})
    assert resp.status_code == 200
    body = resp.json()
    assert body["propagated_beverage_records"] >= 1

    await db_session.refresh(record)
    # 100 × 200/100 = 200
    assert record.kcal == Decimal("200.00")
    assert record.source == "user_corrected"


async def test_patch_nutrient_fact_recomputes_snapshot(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-14: snapshots recomputed for affected open days."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    fact = await _create_manual_fact(db_session, admin_user, kcal=Decimal("130"))
    await _create_food_item(db_session, admin_user, dl.id, fact.id, grams=100)
    await db_session.commit()

    from app.services.daily_recompute import DailyRecomputeService

    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    snap = (
        await db_session.execute(select(DailySnapshot).where(DailySnapshot.day_log_id == dl.id))
    ).scalar_one()
    assert snap.kcal_in == Decimal("130.00")

    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 200})
    assert resp.status_code == 200
    assert resp.json()["propagated_food_items"] >= 1

    await db_session.refresh(snap)
    assert snap.kcal_in == Decimal("200.00")


async def test_patch_nutrient_fact_records_audit_for_propagation(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-14: audit events with action='propagate' for each updated item."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    fact = await _create_manual_fact(db_session, admin_user, kcal=Decimal("130"))
    item = await _create_food_item(db_session, admin_user, dl.id, fact.id, grams=100)
    await db_session.commit()

    await _login(client)
    await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 200})

    propagate_events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == item.id,
                    AuditEvent.action == "propagate",
                )
            )
        ).scalars()
    )
    assert len(propagate_events) == 1
    assert propagate_events[0].before is not None
    assert propagate_events[0].after is not None
    assert propagate_events[0].before["kcal"] == 130.0
    assert propagate_events[0].after["kcal"] == 200.0