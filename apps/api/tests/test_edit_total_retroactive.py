"""SP-182..SP-185 — edição total no /day + registro retroativo.

Cobre:
- SP-182/INV-24: clone de fact canônico nunca muta o catálogo TBCA/USDA.
- SP-183: edição de metadados (detected_name, meal_slot, occurred_at).
- SP-184: registro retroativo via chat (`target_date`).
- SP-185/INV-25: criação estruturada em dia passado aberto; futuro/fechado rejeitado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    AuditEvent,
    DayLog,
    FoodItem,
    FoodRecord,
    NutrientFact,
    WaterRecord,
)
from app.repositories.day_log import DayLogRepository

pytestmark = pytest.mark.asyncio


async def _seed(db_session: AsyncSession) -> None:
    await seed_from_csv(db_session)
    await db_session.commit()


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login", json={"email": "admin@example.com", "password": "adminadmin"}
    )
    assert resp.status_code == 204


async def _make_food_item(db_session: AsyncSession, admin_user, *, catalog_ref_id=None) -> FoodItem:
    local_date = datetime.now(ZoneInfo(admin_user.timezone)).date()
    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=local_date
    )
    record = FoodRecord(
        user_id=admin_user.id,
        day_log_id=dl.id,
        meal_slot="lunch",
        occurred_at=datetime.now(UTC),
    )
    db_session.add(record)
    await db_session.flush()

    item = FoodItem(
        food_record_id=record.id,
        catalog_ref_id=catalog_ref_id,
        detected_name="arroz branco cozido",
        normalized_name="arroz_branco_cozido",
        grams=Decimal("100"),
        ml=None,
        quantity=None,
        unit="g",
        source="catalog",
        confidence=Decimal("0.9"),
        is_estimate=False,
        needs_confirmation=False,
        kcal=Decimal("130.00"),
        protein_g=Decimal("2.50"),
        carbs_g=Decimal("28.00"),
        fat_g=Decimal("0.50"),
    )
    db_session.add(item)
    await db_session.commit()
    return item


# ---------------------------------------------------------------------------
# SP-182 / INV-24 — clone de fact canônico
# ---------------------------------------------------------------------------


async def test_clone_canonical_fact_preserves_catalog(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    fact = (
        (await db_session.execute(select(NutrientFact).where(NutrientFact.source == "TBCA_2023")))
        .scalars()
        .first()
    )
    item = await _make_food_item(db_session, admin_user, catalog_ref_id=fact.id)
    original_kcal = fact.kcal

    await _login(client)
    resp = await client.post(f"/records/food-items/{item.id}/clone-fact")
    assert resp.status_code == 200
    new_fact_id = resp.json()["fact_id"]
    assert new_fact_id != str(fact.id)

    # INV-24: o fact canônico permanece intacto.
    await db_session.refresh(fact)
    assert fact.source == "TBCA_2023"
    assert fact.kcal == original_kcal
    assert fact.created_by is None

    new_fact = await db_session.get(NutrientFact, new_fact_id)
    assert new_fact.source == "manual"
    assert new_fact.created_by == admin_user.id
    assert new_fact.kcal == original_kcal

    await db_session.refresh(item)
    assert item.catalog_ref_id == new_fact.id


async def test_clone_fact_rejects_non_canonical(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    # Item sem catálogo → não clonável.
    item = await _make_food_item(db_session, admin_user, catalog_ref_id=None)

    await _login(client)
    resp = await client.post(f"/records/food-items/{item.id}/clone-fact")
    assert resp.status_code == 409
    assert resp.json()["code"] == "not_cloneable"


# ---------------------------------------------------------------------------
# SP-183 — edição de metadados
# ---------------------------------------------------------------------------


async def test_patch_food_record_meal_slot(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _make_food_item(db_session, admin_user)
    record = (await db_session.execute(select(FoodRecord))).scalars().first()

    await _login(client)
    resp = await client.patch(f"/records/food-records/{record.id}", json={"meal_slot": "dinner"})
    assert resp.status_code == 200
    assert resp.json()["meal_slot"] == "dinner"

    await db_session.refresh(record)
    assert record.meal_slot == "dinner"

    events = (
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == record.id, AuditEvent.action == "correct"
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(events) == 1


async def test_patch_food_item_detected_name(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    item = await _make_food_item(db_session, admin_user)

    await _login(client)
    resp = await client.patch(
        f"/records/food-items/{item.id}", json={"detected_name": "arroz integral"}
    )
    assert resp.status_code == 200

    await db_session.refresh(item)
    assert item.detected_name == "arroz integral"
    assert item.normalized_name == "arroz_integral"


# ---------------------------------------------------------------------------
# SP-185 / INV-25 — criação estruturada retroativa
# ---------------------------------------------------------------------------


def _yesterday(user) -> date:
    return datetime.now(ZoneInfo(user.timezone)).date() - timedelta(days=1)


async def test_create_water_retroactive(client: AsyncClient, admin_user, db_session: AsyncSession):
    yday = _yesterday(admin_user)

    await _login(client)
    resp = await client.post(
        "/records/water", json={"log_date": yday.isoformat(), "volume_ml": 500}
    )
    assert resp.status_code == 201

    record = (await db_session.execute(select(WaterRecord))).scalars().one()
    dl = await db_session.get(DayLog, record.day_log_id)
    assert dl.log_date == yday


async def test_create_water_future_date_rejected(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    future = datetime.now(ZoneInfo(admin_user.timezone)).date() + timedelta(days=1)

    await _login(client)
    resp = await client.post(
        "/records/water", json={"log_date": future.isoformat(), "volume_ml": 500}
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "future_date"


async def test_create_food_closed_day_409(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    yday = _yesterday(admin_user)
    dl = await DayLogRepository(db_session).get_or_create(user_id=admin_user.id, log_date=yday)
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    resp = await client.post(
        "/records/food",
        json={
            "log_date": yday.isoformat(),
            "meal_slot": "lunch",
            "items": [{"detected_name": "arroz", "grams": 100}],
        },
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict_closed_day"


# ---------------------------------------------------------------------------
# SP-184 — registro retroativo via chat (target_date)
# ---------------------------------------------------------------------------


async def test_chat_registration_retroactive_target_date(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _seed(db_session)
    yday = _yesterday(admin_user)

    envelope = make_envelope(
        intent="log_water",
        confidence=0.9,
        user_text_summary="Usuário registrou água ontem.",
        needs_clarification=False,
        target_date=yday,
        water={"volume_ml": 300, "confidence": 0.9},
    )
    fake_anthropic.queue(make_llm_result(envelope))

    await _login(client)
    resp = await client.post("/chat/messages", json={"text": "ontem bebi 300ml de água"})
    assert resp.status_code == 202

    record = (await db_session.execute(select(WaterRecord))).scalars().one()
    dl = await db_session.get(DayLog, record.day_log_id)
    assert dl.log_date == yday
