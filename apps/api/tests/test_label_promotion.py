"""SP-143 / T-B521 / T-B522 — foto de rótulo + promoção acoplada.

Cenários (item por item, seguindo o gate do Bloco 5 reformulado):

1. Foto de rótulo válido + item válido → promoção completa (macros
   recomputados, snapshot atualizado, audit `promoted_from=label_ocr`).
2. Foto de rótulo + item de outro user → fact criado, promoção falha
   silenciosa (`promotion_failed:item_not_found`), audit `promotion_failed`.
3. Foto de rótulo + item deletado → warning `promotion_failed:item_deleted`.
4. Foto de rótulo + dia fechado → warning `promotion_failed:day_closed`
   (INV-5), fact criado normalmente.
5. Foto **não** de rótulo (LLM devolve `clarify`) → `promote_food_item_id`
   ignorado silenciosamente; nenhum audit de promoção.
6. Foto de rótulo **sem** `promote_food_item_id` → comportamento
   pré-Bloco 5 inalterado (fact criado, sem promoção).
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
from app.models import AuditEvent, DailySnapshot, FoodItem, Message, NutrientFact
from app.repositories.day_log import DayLogRepository
from app.repositories.user import UserRepository
from app.schemas.llm import LLMEnvelope, NutritionLabelIn
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _day_log(session: AsyncSession, user):
    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


def _label_payload(**overrides) -> dict:
    """`NutritionLabelIn` que o backend cria como fact `label_ocr`."""
    base = dict(
        product_name="Pão de Queijo Congelado",
        brand="Forno de Minas",
        barcode="7891234567890",
        basis="per_100g",
        kcal=320.0,
        protein_g=8.0,
        carbs_g=40.0,
        fat_g=14.0,
        fiber_g=0.5,
        sodium_mg=380.0,
    )
    base.update(overrides)
    return NutritionLabelIn.model_validate(base).model_dump(mode="json")


async def _create_food_no_catalog(
    session: AsyncSession, user, dl_id, detected: str, normalized: str, grams: float
) -> FoodItem:
    """Cria food_item que ficaria com kcal=0 / catalog_ref_id=NULL —
    reproduz o cenário do card recovery do Bloco 5."""
    envelope = LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "meal_slot": "lunch",
            "food_items": [
                {
                    "detected_name": detected,
                    "normalized_name": normalized,
                    "grams_estimate": grams,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ],
        }
    )
    result = await MealService(session, LocalTBCACatalog(session)).create_from_llm(
        user=user, day_log_id=dl_id, message_id=None, envelope=envelope
    )
    await session.commit()
    return result.items[0]


# ---------------------------------------------------------------------------
# Cenário 1 — happy path: label + item válido → promoção completa
# ---------------------------------------------------------------------------


async def test_valid_label_with_valid_item_promotes(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(
        db_session, admin_user, dl.id, "pao de queijo", "pao_de_queijo_congelado", 100
    )
    assert item.catalog_ref_id is None
    assert item.kcal == 0

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label_payload(),
            )
        )
    )
    resp = await client.post(
        "/chat/messages",
        json={"text": "foto do rótulo", "promote_food_item_id": str(item.id)},
    )
    assert resp.status_code == 202

    # Fact criado?
    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    label_facts = [f for f in facts if f.source == "label_ocr"]
    assert len(label_facts) == 1
    fact = label_facts[0]

    # Item promovido: catalog_ref_id atualizado, macros recomputados,
    # source = user_corrected.
    await db_session.refresh(item)
    assert item.catalog_ref_id == fact.id
    # 100g × 320 kcal/100 = 320
    assert item.kcal == Decimal("320.00")
    assert item.protein_g == Decimal("8.00")
    assert item.source == "user_corrected"

    # Snapshot recomputado?
    snap = (
        await db_session.execute(select(DailySnapshot).where(DailySnapshot.day_log_id == dl.id))
    ).scalar_one_or_none()
    assert snap is not None
    assert snap.kcal_in == Decimal("320.00")

    # Audit com promoted_from=label_ocr no after.
    correct_audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == item.id, AuditEvent.action == "correct"
                )
            )
        ).scalars()
    )
    assert len(correct_audits) == 1
    assert correct_audits[0].after["promoted_from"] == "label_ocr"


# ---------------------------------------------------------------------------
# Cenário 2 — item de outro user → falha silenciosa + audit promotion_failed
# ---------------------------------------------------------------------------


async def test_valid_label_with_item_of_other_user_falls_silent(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    from app.core.security import hash_password

    # Cria outro user com um item legado seu.
    other = await UserRepository(db_session).create(
        email="stranger@example.com",
        password_hash=hash_password("otherotherother"),
    )
    await db_session.commit()
    other_dl = await DayLogRepository(db_session).get_or_create(
        user_id=other.id,
        log_date=datetime.now(ZoneInfo(other.timezone)).date(),
    )
    await db_session.commit()
    other_item = await _create_food_no_catalog(
        db_session, other, other_dl.id, "quinoa", "quinoa_cozida", 80
    )

    # Admin (autenticado) tenta enviar rótulo apontando pro item de outro.
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label_payload(product_name="Quinoa", barcode="0000000000001"),
            )
        )
    )
    resp = await client.post(
        "/chat/messages",
        json={"text": "foto", "promote_food_item_id": str(other_item.id)},
    )
    assert resp.status_code == 202

    # T-B520: ChatService valida ownership no post_user_message e descarta
    # o campo silenciosamente ANTES de armazenar em raw. MessageProcessor
    # nem chega a chamar `try_promote_food_item`. Item de outro user
    # permanece intacto.
    await db_session.refresh(other_item)
    assert other_item.catalog_ref_id is None
    assert other_item.kcal == 0

    # Nenhum audit de promotion_failed (validação silenciosa aconteceu
    # antes do processador chegar a rodar).
    failed_audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action == "promotion_failed")
            )
        ).scalars()
    )
    assert failed_audits == []

    # Fact do rótulo AINDA foi criado — o cadastro do rótulo pertence ao
    # admin (autenticado); só a promoção que foi ignorada.
    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert any(f.source == "label_ocr" for f in facts)


# ---------------------------------------------------------------------------
# Cenário 3 — item deletado → warning promotion_failed:item_deleted
# ---------------------------------------------------------------------------


async def test_valid_label_with_deleted_item_falls_silent(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B520: ChatService valida `deleted_at IS NULL` já no envio.
    Item deletado é descartado antes de virar metadata."""
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(db_session, admin_user, dl.id, "acai", "acai_pura", 100)
    item.deleted_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label_payload(product_name="Acai", barcode="0000000000002"),
            )
        )
    )
    resp = await client.post(
        "/chat/messages",
        json={"text": "foto", "promote_food_item_id": str(item.id)},
    )
    assert resp.status_code == 202

    # Item deletado permanece com kcal=0 e sem catalog_ref_id.
    await db_session.refresh(item)
    assert item.catalog_ref_id is None

    # Fact do rótulo foi criado normalmente pelo admin.
    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert any(f.source == "label_ocr" for f in facts)


# ---------------------------------------------------------------------------
# Cenário 4 — dia fechado → falha silenciosa (INV-5), fact criado
# ---------------------------------------------------------------------------


async def test_valid_label_with_closed_day_falls_silent(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """INV-5: dia fechado bloqueia mutação em food_item. A promoção deve
    falhar com warning `day_closed` E gravar audit `promotion_failed`.
    Fact criado sem afetar snapshot congelado."""
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(
        db_session, admin_user, dl.id, "cha verde", "cha_verde_produto_novo", 200
    )
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label_payload(product_name="Cha Verde", barcode="0000000000003"),
            )
        )
    )
    resp = await client.post(
        "/chat/messages",
        json={"text": "foto do rótulo", "promote_food_item_id": str(item.id)},
    )
    assert resp.status_code == 202

    # Item continua zerado (INV-5).
    await db_session.refresh(item)
    assert item.catalog_ref_id is None
    assert item.kcal == 0

    # Audit `promotion_failed` gravado com reason=day_closed.
    failed = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == item.id,
                    AuditEvent.action == "promotion_failed",
                )
            )
        ).scalars()
    )
    assert len(failed) == 1
    assert failed[0].after["reason"] == "promotion_failed:day_closed"
    assert failed[0].after["promoted_from"] == "label_ocr"

    # Fact criado normalmente.
    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert any(f.source == "label_ocr" for f in facts)


# ---------------------------------------------------------------------------
# Cenário 5 — foto não é rótulo (LLM devolve `clarify`) → ignora promote_id
# ---------------------------------------------------------------------------


async def test_non_label_photo_ignores_promote_id(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Se a LLM interpreta a foto como não-rótulo (clarify), a promoção
    nem chega a ser tentada porque `_handle_log_nutrition_label` não roda.
    Item continua zerado, sem audit de promotion."""
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(
        db_session, admin_user, dl.id, "misterio", "produto_misterioso", 50
    )

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="clarify",
                confidence=0.4,
                user_text_summary="foto não parece rótulo",
                needs_clarification=True,
            )
        )
    )
    resp = await client.post(
        "/chat/messages",
        json={"text": "não sei o que é isso", "promote_food_item_id": str(item.id)},
    )
    assert resp.status_code == 202

    # Nenhum audit relacionado à promoção — fluxo do rótulo nem começou.
    audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == item.id,
                    AuditEvent.action.in_(("correct", "promotion_failed")),
                )
            )
        ).scalars()
    )
    assert audits == []

    await db_session.refresh(item)
    assert item.catalog_ref_id is None
    assert item.kcal == 0


# ---------------------------------------------------------------------------
# Cenário 6 — foto de rótulo SEM promote_food_item_id → fluxo original
# ---------------------------------------------------------------------------


async def test_label_without_promote_id_leaves_flow_untouched(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Backward-compat: fluxo Fase 4.b puro (usuário anexou rótulo mas
    sem contexto de item legado). Fact criado; nenhuma promoção acontece;
    dispatch NÃO tem `promoted_item_id`."""
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_nutrition_label",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
                nutrition_label=_label_payload(product_name="Novo Item", barcode="0000000000004"),
            )
        )
    )
    resp = await client.post("/chat/messages", json={"text": "só um rótulo"})
    assert resp.status_code == 202

    facts = list((await db_session.execute(select(NutrientFact))).scalars())
    assert any(f.source == "label_ocr" for f in facts)

    # Assistant message existe; dispatch NÃO contém promoção.
    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    dispatch = (assistant.raw_llm_response or {}).get("dispatch") or {}
    assert "promoted_item_id" not in dispatch
    assert "promotion_warning" not in dispatch

    # Zero audit de promoção.
    audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(AuditEvent.action.in_(("correct", "promotion_failed")))
            )
        ).scalars()
    )
    # `correct` só existe se veio de PATCH/promoção — aqui não deveria ter.
    assert audits == []
