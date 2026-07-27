"""SP-20 end-to-end via /chat/messages: LLM devolve log_food → MealService
persiste → DailyRecompute atualiza snapshot → assistant message resume.

Const. Art. II §5 (INV-1): AnthropicClient é fake devolvendo lixo em kcal;
o cálculo vem do catálogo/calculator, não do envelope."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.seed import seed_from_csv
from app.models import DailySnapshot, FoodItem, FoodRecord, Message

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


async def test_log_food_end_to_end_persists_and_recomputes(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _seed(db_session)
    await _login(client)

    envelope = make_envelope(
        intent="log_food",
        confidence=0.92,
        user_text_summary="Almoço: arroz e frango.",
        needs_clarification=False,
        meal_slot="lunch",
        food_items=[
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
                "detected_name": "peito de frango grelhado",
                "normalized_name": "peito_de_frango_grelhado",
                "quantity": 180,
                "unit": "g",
                "grams_estimate": 180,
                "confidence": 0.94,
                "is_estimate": False,
            },
        ],
    )
    fake_anthropic.queue(make_llm_result(envelope))

    resp = await client.post(
        "/chat/messages",
        json={"text": "almoço: 150g de arroz e 180g de frango"},
    )
    assert resp.status_code == 202

    records = list((await db_session.execute(select(FoodRecord))).scalars())
    items = list((await db_session.execute(select(FoodItem))).scalars())
    snapshots = list((await db_session.execute(select(DailySnapshot))).scalars())
    assert len(records) == 1
    assert len(items) == 2
    assert len(snapshots) == 1
    # arroz 150g × 130 = 195; frango 180g × 165 = 297 → 492.00
    assert snapshots[0].kcal_in.compare(Decimal("492.00")) == 0

    # assistant response includes summary + disclaimer
    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    # SP-118: formato tabular. Item names ficam na estrutura (raw dispatch),
    # não no texto — apenas o cabeçalho + tabelas + disclaimer aparecem.
    assert "Registrei" in assistant.content
    assert "Total da refeição — Almoço" in assistant.content
    assert "Total acumulado —" in assistant.content
    assert "kcal" in assistant.content
    assert "acompanhamento médico" in assistant.content
    assert assistant.llm_intent == "log_food"


async def test_llm_kcal_lies_ignored_backend_calculates(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """INV-1 / Const. §5: se a LLM manda lixo, o total do dia vem do
    calculator determinístico, não do envelope. O envelope não tem kcal
    de qualquer forma (schema não expõe), mas o teste garante que o
    resultado é EXATAMENTE o do catálogo × grams."""
    await _seed(db_session)
    await _login(client)

    envelope = make_envelope(
        intent="log_food",
        confidence=0.9,
        user_text_summary="Registro.",
        needs_clarification=False,
        meal_slot="dinner",
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
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "100g de arroz"})

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    # 100g × 130kcal/100 = exatamente 130.00; sem influência da LLM
    assert snap.kcal_in.compare(130) == 0


async def test_unknown_food_creates_zero_kcal_with_warning(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-23 fluxo completo: alimento sem catálogo → kcal=0 + warning
    exposto no snapshot; item flagado como needs_confirmation."""
    await _seed(db_session)
    await _login(client)

    envelope = make_envelope(
        intent="log_food",
        confidence=0.85,
        user_text_summary="Registro.",
        needs_clarification=False,
        meal_slot="snack",
        food_items=[
            {
                "detected_name": "sushi ninja special",
                "normalized_name": "sushi_ninja_special",
                "grams_estimate": 200,
                "confidence": 0.85,
                "is_estimate": False,
            }
        ],
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "comi um sushi ninja"})

    item = (await db_session.execute(select(FoodItem))).scalar_one()
    assert item.kcal == 0
    assert item.needs_confirmation is True

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    codes = {w["code"] for w in snap.warnings}
    assert "no_catalog_hit" in codes
    assert "needs_confirmation" in codes
