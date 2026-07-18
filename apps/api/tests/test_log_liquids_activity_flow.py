"""SP-40..64 end-to-end via /chat/messages para água, bebida e atividade.

Verifica também INV-2/INV-3 no snapshot: água só em water_ml, bebida
calórica em kcal_in + other_liquids_ml (nunca em water_ml)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    ActivityRecord,
    BeverageRecord,
    DailySnapshot,
    Message,
    WaterRecord,
)

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _seed(db_session: AsyncSession) -> None:
    await seed_from_csv(db_session)
    await db_session.commit()


async def test_log_water_end_to_end(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _login(client)
    envelope = make_envelope(
        intent="log_water",
        confidence=0.95,
        user_text_summary="Registro de água.",
        needs_clarification=False,
        water={"volume_ml": 500, "confidence": 0.95},
    )
    fake_anthropic.queue(make_llm_result(envelope))
    resp = await client.post("/chat/messages", json={"text": "500 ml de água"})
    assert resp.status_code == 202

    rows = list((await db_session.execute(select(WaterRecord))).scalars())
    assert len(rows) == 1
    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    assert snap.water_ml == 500
    # INV-2: água pura NUNCA contribui para kcal_in nem other_liquids_ml
    assert snap.kcal_in == Decimal("0")
    assert snap.other_liquids_ml == 0


async def test_log_water_rejected_when_summary_hints_coffee(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-41: log_water com café no resumo → assistant faz clarify amigável."""
    await _login(client)
    envelope = make_envelope(
        intent="log_water",
        confidence=0.9,
        user_text_summary="Usuário tomou um cafezinho.",
        needs_clarification=False,
        water={"volume_ml": 50, "confidence": 0.9},
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "café"})

    # Nada persistido em water_records
    rows = list((await db_session.execute(select(WaterRecord))).scalars())
    assert rows == []

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert assistant.llm_intent == "clarify"
    assert "café" in assistant.content.lower() or "bebida" in assistant.content.lower()


async def test_log_beverage_end_to_end_with_catalog(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-50 / INV-3: bebida com kcal → kcal_in + other_liquids_ml, NUNCA water_ml."""
    await _seed(db_session)
    await _login(client)
    envelope = make_envelope(
        intent="log_beverage",
        confidence=0.9,
        user_text_summary="Café da manhã com leite.",
        needs_clarification=False,
        beverage={
            "detected_name": "leite integral",
            "brand": None,
            "volume_ml": 200,
            "beverage_kind": "other",
            "confidence": 0.9,
        },
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "200 ml de leite"})

    beverage_rows = list((await db_session.execute(select(BeverageRecord))).scalars())
    assert len(beverage_rows) == 1

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    # leite 200ml × 61 kcal/100ml = 122
    assert snap.kcal_in == Decimal("122.00")
    assert snap.other_liquids_ml == 200
    assert snap.water_ml == 0  # nunca!


async def test_log_activity_end_to_end(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-60/SP-64 end-to-end: activity → kcal_out no snapshot."""
    admin_user.weight_kg = Decimal("78")
    await db_session.commit()

    await _login(client)
    envelope = make_envelope(
        intent="log_activity",
        confidence=0.9,
        user_text_summary="Corrida.",
        needs_clarification=False,
        activity={
            "detected_name": "corrida",
            "activity_type": "cardio_run",
            "duration_minutes": 40,
            "distance_km": None,
            "intensity": "moderate",
            "confidence": 0.9,
        },
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "corri 40 min moderado"})

    activity_rows = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert len(activity_rows) == 1

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    # 8.3 × 78 × 40/60 = 431.60
    assert snap.kcal_out == Decimal("431.60")
    assert snap.kcal_balance == -snap.kcal_out  # sem kcal_in


async def test_log_activity_without_weight_triggers_clarify(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-61: user sem weight_kg → assistant pede o peso, sem persistir."""
    await _login(client)
    envelope = make_envelope(
        intent="log_activity",
        confidence=0.9,
        user_text_summary="Corrida.",
        needs_clarification=False,
        activity={
            "detected_name": "corrida",
            "activity_type": "cardio_run",
            "duration_minutes": 30,
            "distance_km": None,
            "intensity": "moderate",
            "confidence": 0.9,
        },
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "corri 30 min"})

    rows = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert rows == []

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert assistant.llm_intent == "clarify"
    assert "peso" in assistant.content.lower()


async def test_snapshot_mixes_food_beverage_activity_water(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Mistura 4 registros no mesmo dia — snapshot combina tudo com kcal_out."""
    admin_user.weight_kg = Decimal("78")
    await _seed(db_session)
    await db_session.commit()
    await _login(client)

    # 1) arroz 100g → 124 kcal
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_food",
                confidence=0.9,
                user_text_summary=".",
                needs_clarification=False,
                meal_slot="lunch",
                food_items=[
                    {
                        "detected_name": "arroz",
                        "normalized_name": "arroz_branco_cozido",
                        "grams_estimate": 100,
                        "confidence": 0.9,
                        "is_estimate": False,
                    }
                ],
            )
        )
    )
    await client.post("/chat/messages", json={"text": "100g de arroz"})

    # 2) café 200ml → 4 kcal
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_beverage",
                confidence=0.9,
                user_text_summary=".",
                needs_clarification=False,
                beverage={
                    "detected_name": "cafe coado sem acucar",
                    "brand": None,
                    "volume_ml": 200,
                    "beverage_kind": "other",
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "200ml café"})

    # 3) 750ml de água
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_water",
                confidence=0.95,
                user_text_summary="Água pura.",
                needs_clarification=False,
                water={"volume_ml": 750, "confidence": 0.95},
            )
        )
    )
    await client.post("/chat/messages", json={"text": "750ml de água"})

    # 4) caminhada 30 min light → 2.8 × 78 × 0.5 = 109.2
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_activity",
                confidence=0.9,
                user_text_summary="Caminhada.",
                needs_clarification=False,
                activity={
                    "detected_name": "caminhada",
                    "activity_type": "cardio_walk",
                    "duration_minutes": 30,
                    "distance_km": None,
                    "intensity": "light",
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "caminhei 30 min leves"})

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    # kcal_in = 124 (arroz) + 4 (café 200ml × 2/100)
    assert snap.kcal_in == Decimal("128.00")
    # kcal_out = 2.8 × 78 × 30/60 = 109.20
    assert snap.kcal_out == Decimal("109.20")
    assert snap.kcal_balance == Decimal("18.80")
    assert snap.water_ml == 750
    assert snap.other_liquids_ml == 200
    # 4 recomputes (uma por chat post)
    assert snap.version == 4
