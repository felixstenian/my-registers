"""Fase 4.b — Cadastro de nutrient_facts por foto de rótulo.

Cobre:
- SP-30 upsert cria fact `label_ocr` a partir de `NutritionLabelIn`.
- SP-31 `also_consumed` gera food_record + food_item apontando pro fact.
- SP-32 `per_serving` sem serving_size já é bloqueado pelo Pydantic
  (regressão do validator).
- SP-33 `PATCH /nutrient-facts/{id}` marca `verified_by_user=true`.
- SP-34 warning `micros_missing_for_product` quando Ca/Fe/K são None.
- SP-35 precedência do LocalTBCACatalog respeitando source e verified.
- SP-32 normalização determinística: `per_serving` de 34g → per_100g.
- Idempotência: reupload do mesmo barcode atualiza o fact.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.catalog import LookupQuery
from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, FoodItem, FoodRecord, Message, NutrientFact
from app.schemas.llm import NutritionLabelIn
from app.services.label_catalog import LabelCatalogService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.repositories.day_log import DayLogRepository

    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


def _label(**overrides) -> NutritionLabelIn:
    base = dict(
        product_name="Barra de Cereal XYZ",
        brand="Marca X",
        barcode="7891234567890",
        basis="per_100g",
        kcal=380.0,
        protein_g=8.0,
        carbs_g=60.0,
        fat_g=12.0,
        fiber_g=3.5,
        sodium_mg=250.0,
    )
    base.update(overrides)
    return NutritionLabelIn.model_validate(base)


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# SP-30 — upsert cria/atualiza NutrientFact source=label_ocr
# ---------------------------------------------------------------------------


async def test_upsert_creates_fact_with_source_label_ocr(admin_user, db_session: AsyncSession):
    result = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=_label(), label_media_id=None, message_id=None
    )
    assert result.fact.source == "label_ocr"
    assert result.fact.verified_by_user is False
    assert result.fact.basis == "per_100g"
    assert float(result.fact.kcal) == 380.0


async def test_upsert_updates_existing_on_repeat_barcode(admin_user, db_session: AsyncSession):
    """SP-30: mesmo barcode → atualiza, não duplica."""
    s = LabelCatalogService(db_session)
    r1 = await s.upsert_from_label(
        user=admin_user, label=_label(kcal=380.0), label_media_id=None, message_id=None
    )
    await db_session.commit()

    r2 = await s.upsert_from_label(
        user=admin_user, label=_label(kcal=400.0), label_media_id=None, message_id=None
    )

    assert r1.fact.id == r2.fact.id
    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert len(facts) == 1
    await db_session.refresh(r2.fact)
    assert float(r2.fact.kcal) == 400.0


async def test_upsert_preserves_verified_flag_on_reupload(admin_user, db_session: AsyncSession):
    """Se o usuário já verificou, um reupload NÃO rebaixa `verified_by_user`."""
    s = LabelCatalogService(db_session)
    r1 = await s.upsert_from_label(
        user=admin_user, label=_label(), label_media_id=None, message_id=None
    )
    r1.fact.verified_by_user = True
    await db_session.commit()

    await s.upsert_from_label(
        user=admin_user, label=_label(kcal=395.0), label_media_id=None, message_id=None
    )
    await db_session.refresh(r1.fact)
    assert r1.fact.verified_by_user is True


# ---------------------------------------------------------------------------
# SP-32 — normalização per_serving → per_100g|ml
# ---------------------------------------------------------------------------


async def test_upsert_normalizes_per_serving_to_per_100g(admin_user, db_session: AsyncSession):
    label = _label(
        basis="per_serving",
        serving_size_g=34.0,
        kcal=129.0,
        protein_g=2.7,
        carbs_g=20.4,
        fat_g=4.1,
        fiber_g=1.2,
        sodium_mg=85.0,
        barcode="9998887771111",
    )
    result = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=label, label_media_id=None, message_id=None
    )
    assert result.fact.basis == "per_100g"
    # 129 * (100/34) = 379.41
    assert float(result.fact.kcal) == pytest.approx(379.41, abs=0.05)
    assert float(result.fact.carbs_g) == pytest.approx(60.0, abs=0.1)


async def test_per_serving_without_size_rejected_by_schema():
    """SP-32 no nível de schema — LLM validator já bloqueia."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        NutritionLabelIn.model_validate(
            {
                "product_name": "X",
                "basis": "per_serving",
                "kcal": 100.0,
            }
        )


# ---------------------------------------------------------------------------
# SP-34 — micros ausentes viram warning
# ---------------------------------------------------------------------------


async def test_missing_micros_produces_warning(admin_user, db_session: AsyncSession):
    """SP-34: rótulos brasileiros geralmente omitem Ca/Fe/K; warning emitido."""
    result = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=_label(), label_media_id=None, message_id=None
    )
    codes = [w["code"] for w in result.warnings]
    assert "micros_missing_for_product" in codes
    warn = next(w for w in result.warnings if w["code"] == "micros_missing_for_product")
    assert set(warn["missing"]) == {"calcium_mg", "iron_mg", "potassium_mg"}


async def test_complete_micros_no_warning(admin_user, db_session: AsyncSession):
    result = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user,
        label=_label(calcium_mg=50.0, iron_mg=2.0, potassium_mg=100.0),
        label_media_id=None,
        message_id=None,
    )
    assert result.warnings == []


# ---------------------------------------------------------------------------
# SP-31 — also_consumed cria food_record + food_item
# ---------------------------------------------------------------------------


async def test_also_consumed_creates_food_record(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _login(client)
    envelope = make_envelope(
        intent="log_nutrition_label",
        confidence=0.95,
        user_text_summary=".",
        needs_clarification=False,
        nutrition_label={
            "product_name": "Iogurte Zero XYZ",
            "brand": "Marca Z",
            "barcode": "7891122334455",
            "basis": "per_100g",
            "kcal": 45.0,
            "protein_g": 4.5,
            "carbs_g": 6.0,
            "fat_g": 0.1,
            "sodium_mg": 50.0,
            "also_consumed": {"quantity": 170, "unit": "g", "grams": 170},
        },
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "comi esse pote todo (170g)"})

    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert len(facts) == 1
    fact = facts[0]
    items = list((await db_session.execute(select(FoodItem))).scalars())
    assert len(items) == 1
    item = items[0]
    assert item.catalog_ref_id == fact.id
    # 170 * 45 / 100 = 76.5 kcal
    assert float(item.kcal) == pytest.approx(76.5, abs=0.05)


# ---------------------------------------------------------------------------
# SP-33 — PATCH /nutrient-facts/{id} marca verified
# ---------------------------------------------------------------------------


async def test_patch_nutrient_fact_sets_verified(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    r = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=_label(), label_media_id=None, message_id=None
    )
    await db_session.commit()
    fid = str(r.fact.id)

    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fid}", json={"kcal": 390.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verified_by_user"] is True
    assert body["kcal"] == 390.0

    events = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_type == "nutrient_fact",
                    AuditEvent.action == "update",
                )
            )
        ).scalars()
    )
    assert len(events) >= 1


async def test_patch_nutrient_fact_refuses_tbca_source(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """SP-35: fact do catálogo canônico não é editável via PATCH."""
    await _seed(db_session)
    fact = (
        (await db_session.execute(select(NutrientFact).where(NutrientFact.source == "TBCA_2023")))
        .scalars()
        .first()
    )
    assert fact is not None
    await _login(client)
    resp = await client.patch(f"/nutrient-facts/{fact.id}", json={"kcal": 999.0})
    assert resp.status_code == 422
    assert resp.json()["code"] == "not_editable"


async def test_patch_nutrient_fact_not_found(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.patch(
        "/nutrient-facts/00000000-0000-0000-0000-000000000000",
        json={"kcal": 100.0},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SP-35 — precedência (marca > TBCA > label_ocr > manual > mais recente)
# ---------------------------------------------------------------------------


async def test_catalog_prefers_tbca_over_label_ocr(admin_user, db_session: AsyncSession):
    """TBCA_2023 (seed) tem precedência sobre um label_ocr sem verified."""
    await _seed(db_session)
    # Cria um label_ocr com mesmo canonical_name que 'arroz' do TBCA.
    label = _label(
        product_name="arroz",
        brand=None,
        barcode=None,
        basis="per_100g",
        kcal=999.0,
    )
    await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=label, label_media_id=None, message_id=None
    )
    await db_session.commit()

    hit = await LocalTBCACatalog(db_session).lookup(LookupQuery(name="arroz"))
    assert hit is not None
    # 130 kcal do arroz TBCA (seed arroz_branco_cozido), NÃO 999 do label_ocr.
    assert float(hit.kcal) == pytest.approx(130.0, abs=0.5)


async def test_catalog_prefers_label_ocr_when_verified(admin_user, db_session: AsyncSession):
    """`verified_by_user=true` empata com TBCA em precedência de source (ambos
    são 'confiáveis'); com verified true vs verified false do TBCA (que nunca
    é rebaixado), o TBCA ainda vence a menos que a marca seja passada."""
    await _seed(db_session)
    label = _label(product_name="Barra XYZ", brand="MarcaX", barcode="000")
    result = await LabelCatalogService(db_session).upsert_from_label(
        user=admin_user, label=label, label_media_id=None, message_id=None
    )
    result.fact.verified_by_user = True
    await db_session.commit()

    hit = await LocalTBCACatalog(db_session).lookup(LookupQuery(name="Barra XYZ", brand="MarcaX"))
    assert hit is not None
    # Deve casar com o label_ocr (não existe barra XYZ no TBCA).
    assert float(hit.kcal) == pytest.approx(380.0, abs=0.5)


# ---------------------------------------------------------------------------
# End-to-end via chat
# ---------------------------------------------------------------------------


async def test_log_nutrition_label_via_chat_creates_fact_only(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Foto de rótulo sem `also_consumed` → só cadastra, NÃO cria food_record."""
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label().model_dump(mode="json"),
            )
        )
    )
    await client.post("/chat/messages", json={"text": "veja esse rótulo"})

    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    label_facts = [f for f in facts if f.source == "label_ocr"]
    assert len(label_facts) == 1

    food_records = list((await db_session.execute(select(FoodRecord))).scalars())
    assert food_records == []

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "log_nutrition_label"
    assert "Cadastrei" in assistant.content


async def test_message_out_exposes_nutrient_fact_id(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.9,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label().model_dump(mode="json"),
            )
        )
    )
    await client.post("/chat/messages", json={"text": "cadastre"})

    resp = await client.get("/chat/messages")
    body = resp.json()["messages"]
    label_msg = next(m for m in body if m["llm_intent"] == "log_nutrition_label")
    assert label_msg["nutrient_fact_id"] is not None


async def test_non_label_message_has_no_nutrient_fact_id(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
):
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="clarify",
                clarification_question="Detalhe?",
            )
        )
    )
    await client.post("/chat/messages", json={"text": "?"})

    resp = await client.get("/chat/messages")
    body = resp.json()["messages"]
    for m in body:
        assert m.get("nutrient_fact_id") is None
