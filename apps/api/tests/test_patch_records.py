"""SP-164/165/166 — PATCH /records/water/{id}, /beverage/{id}, /activity/{id}.

Tests: happy path (update + recompute + audit), closed day (409),
not found (404), activity kcal override (calc_method=user_manual).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    AuditEvent,
    DailySnapshot,
)
from app.repositories.day_log import DayLogRepository
from app.schemas.llm import LLMEnvelope
from app.services.activity import ActivityService
from app.services.beverage import BeverageService
from app.services.hydration import HydrationService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user):
    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


def _envelope(**overrides) -> LLMEnvelope:
    base: dict = {
        "intent": "log_water",
        "confidence": 0.9,
        "user_text_summary": ".",
        "needs_clarification": False,
    }
    base.update(overrides)
    return LLMEnvelope.model_validate(base)


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _admin_with_weight(session: AsyncSession, admin_user, weight_kg):
    admin_user.weight_kg = Decimal(str(weight_kg))
    await session.commit()
    return admin_user


# ---------------------------------------------------------------------------
# SP-164 — PATCH /records/water/{id}
# ---------------------------------------------------------------------------


async def test_patch_water_updates_volume(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    dl = await _day_log(db_session, admin_user)
    service = HydrationService(db_session)
    envelope = _envelope(water={"volume_ml": 500, "confidence": 0.9})
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    record = result.record

    await _login(client)
    resp = await client.patch(f"/records/water/{record.id}", json={"volume_ml": 750})
    assert resp.status_code == 200
    body = resp.json()
    assert body["volume_ml"] == 750

    await db_session.refresh(record)
    assert record.volume_ml == 750
    assert record.source == "user_corrected"

    events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == record.id,
                    AuditEvent.action == "correct",
                )
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].before is not None
    assert events[0].after is not None
    assert events[0].before["volume_ml"] == 500
    assert events[0].after["volume_ml"] == 750


async def test_patch_water_closed_day_409(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    dl = await _day_log(db_session, admin_user)
    service = HydrationService(db_session)
    envelope = _envelope(water={"volume_ml": 300, "confidence": 0.9})
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    resp = await client.patch(f"/records/water/{result.record.id}", json={"volume_ml": 500})
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict_closed_day"


async def test_patch_water_not_found(client: AsyncClient, admin_user, db_session: AsyncSession):
    await _login(client)
    import uuid

    resp = await client.patch(f"/records/water/{uuid.uuid4()}", json={"volume_ml": 500})
    assert resp.status_code == 404


async def test_patch_water_recomputes_snapshot(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    dl = await _day_log(db_session, admin_user)
    service = HydrationService(db_session)
    envelope = _envelope(water={"volume_ml": 500, "confidence": 0.9})
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    from app.services.daily_recompute import DailyRecomputeService

    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    await _login(client)
    await client.patch(f"/records/water/{result.record.id}", json={"volume_ml": 1000})

    snap = (
        await db_session.execute(select(DailySnapshot).where(DailySnapshot.day_log_id == dl.id))
    ).scalar_one()
    await db_session.refresh(snap)
    assert snap.water_ml == 1000


# ---------------------------------------------------------------------------
# SP-165 — PATCH /records/beverage/{id}
# ---------------------------------------------------------------------------


async def test_patch_beverage_updates_volume_and_recomputes(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
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
    record = result.record
    old_kcal = record.kcal

    await _login(client)
    resp = await client.patch(f"/records/beverage/{record.id}", json={"volume_ml": 400})
    assert resp.status_code == 200
    body = resp.json()
    assert body["volume_ml"] == 400
    # 400ml × 57 kcal/100ml = 228 (double of 200ml × 57 = 114)
    assert body["kcal"] == pytest.approx(228.00)

    await db_session.refresh(record)
    assert record.source == "user_corrected"
    assert record.kcal is not None
    assert old_kcal is not None
    assert record.kcal > old_kcal


async def test_patch_beverage_closed_day_409(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
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
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    resp = await client.patch(f"/records/beverage/{result.record.id}", json={"volume_ml": 200})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# SP-166 — PATCH /records/activity/{id}
# ---------------------------------------------------------------------------


async def _create_activity(session, user, dl_id, **kw):
    service = ActivityService(session)
    defaults = dict(
        detected_name="corrida",
        activity_type="cardio_run",
        duration_minutes=40,
        distance_km=None,
        intensity="moderate",
        confidence=0.9,
    )
    defaults.update(kw)
    envelope = _envelope(intent="log_activity", activity=defaults)
    result = await service.create_from_llm(
        user=user, day_log_id=dl_id, message_id=None, envelope=envelope
    )
    await session.commit()
    return result.record


async def test_patch_activity_updates_duration(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    user = await _admin_with_weight(db_session, admin_user, 78)
    dl = await _day_log(db_session, user)
    record = await _create_activity(db_session, user, dl.id)
    old_kcal = record.kcal_burned

    await _login(client)
    resp = await client.patch(f"/records/activity/{record.id}", json={"duration_minutes": 60})
    assert resp.status_code == 200
    body = resp.json()
    assert body["duration_minutes"] == 60.0
    # 8.3 × 78 × 60/60 = 647.40 (was 8.3 × 78 × 40/60 = 431.60)
    assert body["kcal"] == pytest.approx(647.40)

    await db_session.refresh(record)
    assert record.kcal_burned > old_kcal
    assert record.calc_method == "mets_body_weight"


async def test_patch_activity_updates_intensity(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    user = await _admin_with_weight(db_session, admin_user, 80)
    dl = await _day_log(db_session, user)
    record = await _create_activity(db_session, user, dl.id, intensity="moderate")
    # moderate: 8.3 × 80 × 40/60 = 442.67
    moderate_kcal = record.kcal_burned

    await _login(client)
    resp = await client.patch(f"/records/activity/{record.id}", json={"intensity": "light"})
    assert resp.status_code == 200
    body = resp.json()
    # light: 6.0 × 80 × 40/60 = 320.00
    assert body["kcal"] == pytest.approx(320.00)
    assert body["kcal"] < moderate_kcal


async def test_patch_activity_explicit_kcal_override(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    user = await _admin_with_weight(db_session, admin_user, 78)
    dl = await _day_log(db_session, user)
    record = await _create_activity(db_session, user, dl.id)

    await _login(client)
    resp = await client.patch(f"/records/activity/{record.id}", json={"kcal_burned": 500})
    assert resp.status_code == 200
    body = resp.json()
    assert body["kcal"] == 500.0

    await db_session.refresh(record)
    assert record.kcal_burned == Decimal("500")
    assert record.calc_method == "user_manual"
    assert record.met_value is None

    events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == record.id,
                    AuditEvent.action == "correct",
                )
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].after is not None
    assert events[0].after["calc_method"] == "user_manual"


async def test_patch_activity_closed_day_409(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    user = await _admin_with_weight(db_session, admin_user, 75)
    dl = await _day_log(db_session, user)
    record = await _create_activity(db_session, user, dl.id)
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    resp = await client.patch(f"/records/activity/{record.id}", json={"duration_minutes": 50})
    assert resp.status_code == 409


async def test_patch_activity_not_found(client: AsyncClient, admin_user, db_session: AsyncSession):
    await _login(client)
    import uuid

    resp = await client.patch(f"/records/activity/{uuid.uuid4()}", json={"duration_minutes": 30})
    assert resp.status_code == 404


async def test_patch_activity_audit_event(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    user = await _admin_with_weight(db_session, admin_user, 78)
    dl = await _day_log(db_session, user)
    record = await _create_activity(db_session, user, dl.id)

    await _login(client)
    await client.patch(f"/records/activity/{record.id}", json={"duration_minutes": 50})

    events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == record.id,
                    AuditEvent.action == "correct",
                )
            )
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].before is not None
    assert events[0].after is not None
    assert events[0].before["duration_minutes"] == 40.0
    assert events[0].after["duration_minutes"] == 50.0


# ---------------------------------------------------------------------------
# Bug fix: PATCH food_item with catalog_ref_id must NOT zero macros
# when normalized_name doesn't match aliases in nutrient_facts.
# ---------------------------------------------------------------------------


async def test_patch_food_item_with_catalog_ref_does_not_zero_macros(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """Bug: when catalog_ref_id is set, lookup by name could return None
    (normalized_name doesn't match aliases). The fix fetches the fact
    directly by ID, so macros are recomputed correctly."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)

    # Create a food item with a mismatched normalized_name that doesn't
    # match any alias/canonical_name in the TBCA seed, but has catalog_ref_id
    # pointing to a valid fact.
    from app.models import FoodItem, FoodRecord, NutrientFact

    fact = (
        await db_session.execute(
            select(NutrientFact).where(NutrientFact.canonical_name == "arroz_branco_cozido")
        )
    ).scalar_one()

    food_record = FoodRecord(
        user_id=admin_user.id,
        day_log_id=dl.id,
        meal_slot="lunch",
        occurred_at=datetime.now(UTC),
    )
    db_session.add(food_record)
    await db_session.flush()

    item = FoodItem(
        food_record_id=food_record.id,
        catalog_ref_id=fact.id,
        detected_name="arroz da vovó",
        normalized_name="arroz_da_vovo",  # does NOT match "arroz_branco_cozido"
        grams=Decimal("100"),
        ml=None,
        quantity=None,
        unit="g",
        source="catalog",
        confidence=Decimal("0.9"),
        is_estimate=False,
        needs_confirmation=False,
        kcal=Decimal("130.00"),
        protein_g=Decimal("2.5"),
        carbs_g=Decimal("28.00"),
        fat_g=Decimal("0.50"),
    )
    db_session.add(item)
    await db_session.commit()

    await _login(client)
    resp = await client.patch(f"/records/food-items/{item.id}", json={"grams": 200})
    assert resp.status_code == 200
    body = resp.json()
    # 200g arroz × 130 kcal/100g = 260 — NOT zero!
    assert body["kcal"] == pytest.approx(260.00)

    await db_session.refresh(item)
    assert item.kcal == Decimal("260.00")
    assert item.protein_g > 0
    assert item.carbs_g > 0
