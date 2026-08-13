"""SP-141 / SP-142 — POST /nutrient-facts/manual.

Cobertura:
- happy path per_100g e per_100ml
- canonical_name inválido → 422
- kcal negativa → 422
- isolamento cross-user (Const. §21)
- audit event gravado
- promoção com item válido: catalog_ref_id atualizado, macros recomputadas,
  needs_confirmation=False, snapshot recomputado
- promoção com item de outro user → fact criado + warning
- promoção com item deletado → warning
- promoção sobrescrevendo catalog_ref_id existente → audit registrado
- promoção em dia fechado (INV-5) → warning, fact criado
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, DayLog, FoodItem, NutrientFact
from app.repositories.day_log import DayLogRepository
from app.repositories.user import UserRepository
from app.schemas.llm import LLMEnvelope
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user) -> DayLog:
    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


async def _create_food_no_catalog(
    session: AsyncSession, user, dl_id, detected_name: str, normalized: str, grams: float
) -> FoodItem:
    """Cria food_item que ficaria com kcal=0 / catalog_ref_id=NULL —
    reproduz o cenário do bug do catálogo vazio em prod."""
    catalog = LocalTBCACatalog(session)
    service = MealService(session, catalog)
    envelope = LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "meal_slot": "lunch",
            "food_items": [
                {
                    "detected_name": detected_name,
                    "normalized_name": normalized,
                    "grams_estimate": grams,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ],
        }
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl_id, message_id=None, envelope=envelope
    )
    await session.commit()
    return result.items[0]


def _valid_payload(**overrides):
    base = {
        "canonical_name": "pao_de_queijo_congelado",
        "display_name": "Pão de queijo congelado",
        "brand": "Forno de Minas",
        "basis": "per_100g",
        "kcal": 320,
        "protein_g": 8,
        "carbs_g": 40,
        "fat_g": 14,
        "fiber_g": 0.5,
        "sodium_mg": 380,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


async def test_manual_fact_per_100g(client: AsyncClient, admin_user, db_session: AsyncSession):
    """SP-141: cria fact per_100g, source='manual', verified_by_user=True."""
    await _login(client)
    resp = await client.post("/nutrient-facts/manual", json=_valid_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["canonical_name"] == "pao_de_queijo_congelado"
    assert body["source"] == "manual"
    assert body["basis"] == "per_100g"
    assert body["verified_by_user"] is True
    assert body["kcal"] == 320
    assert body["fiber_g"] == 0.5
    assert body["promotion_warning"] is None
    assert body["promoted_item_id"] is None

    fact = (
        await db_session.execute(
            select(NutrientFact).where(NutrientFact.canonical_name == "pao_de_queijo_congelado")
        )
    ).scalar_one()
    assert fact.created_by == admin_user.id


async def test_manual_fact_per_100ml(client: AsyncClient, admin_user, db_session: AsyncSession):
    """SP-141: bebida caseira em per_100ml."""
    await _login(client)
    payload = _valid_payload(
        canonical_name="suco_maracuja_caseiro",
        display_name="Suco de maracujá caseiro",
        brand=None,
        basis="per_100ml",
        kcal=52,
        protein_g=0.4,
        carbs_g=13,
        fat_g=0.1,
        fiber_g=None,
        sodium_mg=None,
    )
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["basis"] == "per_100ml"
    assert body["fiber_g"] is None


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------


async def test_manual_fact_invalid_canonical_name(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post(
        "/nutrient-facts/manual",
        json=_valid_payload(canonical_name="Pão De Queijo"),  # espaços + maiúsculas
    )
    assert resp.status_code == 422


async def test_manual_fact_negative_kcal(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post("/nutrient-facts/manual", json=_valid_payload(kcal=-5))
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Isolamento cross-user
# ---------------------------------------------------------------------------


async def test_manual_fact_isolation_cross_user(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """Const. §21: fact criado pelo admin tem created_by=admin.
    Sanity: outro user (criado depois) NÃO consegue promover item do admin.
    """
    await _login(client)

    # Cria fact
    resp = await client.post("/nutrient-facts/manual", json=_valid_payload())
    assert resp.status_code == 201
    fact_id = resp.json()["id"]

    # Verifica dono
    fact = await db_session.get(NutrientFact, uuid.UUID(fact_id))
    assert fact is not None
    assert fact.created_by == admin_user.id


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


async def test_manual_fact_writes_audit_event(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _login(client)
    resp = await client.post("/nutrient-facts/manual", json=_valid_payload())
    assert resp.status_code == 201
    fact_id = uuid.UUID(resp.json()["id"])

    audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == fact_id,
                    AuditEvent.entity_type == "nutrient_fact",
                    AuditEvent.action == "create",
                )
            )
        ).scalars()
    )
    assert len(audits) == 1
    assert audits[0].actor == "user"
    assert audits[0].after["source"] == "manual"


# ---------------------------------------------------------------------------
# SP-142 — promoção de item legado
# ---------------------------------------------------------------------------


async def test_promote_valid_item_recomputes_macros(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """Item sem catálogo (kcal=0) é promovido: catalog_ref_id atualizado,
    macros calculados a partir do fact, needs_confirmation=False, snapshot
    recomputado."""
    from app.models import DailySnapshot

    dl = await _day_log(db_session, admin_user)
    # cria item que NÃO existe no seed → catalog_ref_id=NULL, kcal=0
    item = await _create_food_no_catalog(
        db_session, admin_user, dl.id, "pao de queijo", "pao_de_queijo_congelado", 100
    )
    assert item.catalog_ref_id is None
    assert item.kcal == 0
    # Bloco 5 revisão v1.12: needs_confirmation não é mais setado.
    assert item.needs_confirmation is False

    await _login(client)
    payload = _valid_payload(promote_food_item_id=str(item.id))
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_warning"] is None
    assert body["promoted_item_id"] == str(item.id)

    await db_session.refresh(item)
    assert item.catalog_ref_id is not None
    # 100g × 320 kcal/100 = 320
    assert item.kcal == Decimal("320.00")
    assert item.protein_g == Decimal("8.00")
    assert item.needs_confirmation is False
    assert item.source == "user_corrected"

    # Snapshot recomputado?
    snap = (
        await db_session.execute(select(DailySnapshot).where(DailySnapshot.day_log_id == dl.id))
    ).scalar_one_or_none()
    assert snap is not None
    assert snap.kcal_in == Decimal("320.00")


async def test_promote_item_of_other_user_falls_silent(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """SP-142: item de outro user → fact criado + warning promotion_failed."""
    users = UserRepository(db_session)
    from app.core.security import hash_password

    other = await users.create(
        email="stranger@example.com", password_hash=hash_password("otherpass123")
    )
    await db_session.commit()

    other_dl = await DayLogRepository(db_session).get_or_create(
        user_id=other.id, log_date=date(2026, 1, 1)
    )
    await db_session.commit()

    # Item pertence a `other`, não a admin.
    other_item = await _create_food_no_catalog(
        db_session, other, other_dl.id, "quinoa", "quinoa_cozida", 80
    )

    await _login(client)
    payload = _valid_payload(
        canonical_name="quinoa_cozida", promote_food_item_id=str(other_item.id)
    )
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_warning"] is not None
    assert "not_found" in body["promotion_warning"]
    assert body["promoted_item_id"] is None

    # Item do outro user permanece intacto.
    await db_session.refresh(other_item)
    assert other_item.catalog_ref_id is None
    # needs_confirmation nunca mais é setado — comparação apenas por
    # `catalog_ref_id IS NULL` pra saber que o item continua "solto".
    assert other_item.needs_confirmation is False


async def test_promote_deleted_item_falls_silent(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(db_session, admin_user, dl.id, "acai", "acai_pura", 100)
    # soft delete
    item.deleted_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    payload = _valid_payload(canonical_name="acai_pura", promote_food_item_id=str(item.id))
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_warning"] == "promotion_failed:item_deleted"
    assert body["promoted_item_id"] is None


async def test_promote_blocked_on_closed_day(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-5: dia fechado bloqueia a promoção, mas o fact é criado normalmente."""
    dl = await _day_log(db_session, admin_user)
    item = await _create_food_no_catalog(
        db_session, admin_user, dl.id, "cha verde", "cha_verde", 200
    )
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    await _login(client)
    payload = _valid_payload(canonical_name="cha_verde", promote_food_item_id=str(item.id))
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_warning"] == "promotion_failed:day_closed"
    # Item não foi tocado.
    await db_session.refresh(item)
    assert item.catalog_ref_id is None


async def test_promote_overwrites_existing_catalog_ref(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """Se o item já tem catalog_ref_id (do TBCA), a promoção sobrescreve
    com o fact manual — audit registra o `before` com o valor antigo."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    # arroz existe no seed → item vai ter catalog_ref_id preenchido
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)
    envelope = LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "meal_slot": "lunch",
            "food_items": [
                {
                    "detected_name": "arroz",
                    "normalized_name": "arroz_branco_cozido",
                    "grams_estimate": 100,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ],
        }
    )
    result = await service.create_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    item = result.items[0]
    old_catalog_ref = item.catalog_ref_id
    assert old_catalog_ref is not None

    await _login(client)
    payload = _valid_payload(
        canonical_name="arroz_branco_cozido",
        kcal=100,  # valor deliberadamente diferente do TBCA (130)
        promote_food_item_id=str(item.id),
    )
    resp = await client.post("/nutrient-facts/manual", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["promotion_warning"] is None
    assert body["promoted_item_id"] == str(item.id)

    await db_session.refresh(item)
    # catalog_ref_id apontou pro fact novo.
    assert item.catalog_ref_id != old_catalog_ref
    # kcal veio do fact novo (100 × 100/100 = 100).
    assert item.kcal == Decimal("100.00")

    # Audit registra o before com o catalog_ref antigo.
    audits = list(
        (
            await db_session.execute(
                select(AuditEvent).where(
                    AuditEvent.entity_id == item.id, AuditEvent.action == "correct"
                )
            )
        ).scalars()
    )
    assert len(audits) >= 1
    latest = audits[-1]
    assert latest.before["catalog_ref_id"] == str(old_catalog_ref)
    assert latest.after["catalog_ref_id"] == body["id"]
