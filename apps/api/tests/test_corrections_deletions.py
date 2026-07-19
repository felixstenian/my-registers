"""Fase 6 — Correções e remoções.

Cobertura: SP-70/71/72 (correção não ambígua, ambígua, qualificada),
SP-73/82 (dia fechado bloqueia), SP-74 (audit trail), SP-80/81
(remoção via chat e REST idempotente), INV-4 (recompute), INV-5
(imutabilidade de dia fechado), INV-10 (audit em toda mutação).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import (
    AuditEvent,
    DailySnapshot,
    FoodItem,
    Message,
)
from app.schemas.llm import LLMEnvelope
from app.services.correction import CorrectionService, DayClosedError
from app.services.correction_matcher import (
    AmbiguousTarget,
    NoTargetFound,
    TargetMatcher,
)
from app.services.deletion import DeletionService
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user):
    """Cria day_log usando a data LOCAL do user (mesmo cálculo do ChatService).

    Antes usava UTC e batia diferente do que o ChatService cria via
    `local_today(user.timezone)` — sob America/Sao_Paulo à noite, o UTC
    date já é o dia seguinte e o day_log ficava divergente.
    """
    from zoneinfo import ZoneInfo

    from app.repositories.day_log import DayLogRepository

    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


def _log_food_envelope(items: list[dict], meal_slot="lunch") -> LLMEnvelope:
    return LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "meal_slot": meal_slot,
            "food_items": items,
        }
    )


def _correction(target_hint: str, changes: dict) -> LLMEnvelope:
    return LLMEnvelope.model_validate(
        {
            "intent": "correct_record",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "correction": {
                "target_hint": target_hint,
                "changes": changes,
                "confidence": 0.9,
            },
        }
    )


def _deletion(target_hint: str) -> LLMEnvelope:
    return LLMEnvelope.model_validate(
        {
            "intent": "delete_record",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "deletion": {"target_hint": target_hint, "confidence": 0.9},
        }
    )


async def _create_food(db_session, user, dl_id, name, normalized, grams, meal_slot="lunch"):
    catalog = LocalTBCACatalog(db_session)
    service = MealService(db_session, catalog)
    envelope = _log_food_envelope(
        [
            {
                "detected_name": name,
                "normalized_name": normalized,
                "grams_estimate": grams,
                "confidence": 0.9,
                "is_estimate": False,
            }
        ],
        meal_slot=meal_slot,
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl_id, message_id=None, envelope=envelope
    )
    await db_session.commit()
    return result.items[0]


# ---------------------------------------------------------------------------
# TargetMatcher (unit-ish)
# ---------------------------------------------------------------------------


async def test_matcher_unambiguous_food_hit(db_session: AsyncSession, admin_user):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito de frango",
        "peito_de_frango_grelhado",
        150,
    )
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "arroz branco",
        "arroz_branco_cozido",
        100,
    )
    matcher = TargetMatcher(db_session)
    candidate = await matcher.resolve(day_log_id=dl.id, target_hint="frango")
    assert candidate.entity.normalized_name == "peito_de_frango_grelhado"


async def test_matcher_ambiguous_raises(db_session: AsyncSession, admin_user):
    """SP-71: dois 'frangos' no dia sem qualificador → AmbiguousTarget."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito frango almoço",
        "peito_de_frango_grelhado",
        150,
        meal_slot="lunch",
    )
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "coxa frango jantar",
        "coxa_de_frango_cozida",
        200,
        meal_slot="dinner",
    )
    matcher = TargetMatcher(db_session)
    with pytest.raises(AmbiguousTarget) as exc:
        await matcher.resolve(day_log_id=dl.id, target_hint="frango")
    assert len(exc.value.candidates) == 2


async def test_matcher_qualified_by_meal_slot(db_session: AsyncSession, admin_user):
    """SP-72: 'frango do almoço' desambigua por meal_slot."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    lunch_item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito de frango",
        "peito_de_frango_grelhado",
        150,
        meal_slot="lunch",
    )
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "coxa de frango",
        "coxa_de_frango_cozida",
        200,
        meal_slot="dinner",
    )
    matcher = TargetMatcher(db_session)
    candidate = await matcher.resolve(day_log_id=dl.id, target_hint="frango do almoço")
    assert candidate.entity_id == lunch_item.id


async def test_matcher_no_target_raises(db_session: AsyncSession, admin_user):
    dl = await _day_log(db_session, admin_user)
    matcher = TargetMatcher(db_session)
    with pytest.raises(NoTargetFound):
        await matcher.resolve(day_log_id=dl.id, target_hint="pizza")


# ---------------------------------------------------------------------------
# CorrectionService — SP-70, SP-74, INV-4, INV-10
# ---------------------------------------------------------------------------


async def test_correction_updates_grams_and_recomputes_macros(db_session: AsyncSession, admin_user):
    """SP-70: corrigir grams do frango recalcula macros pelo catálogo."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito de frango",
        "peito_de_frango_grelhado",
        150,
    )
    old_kcal = item.kcal

    envelope = _correction("peito de frango", {"grams": 220})
    result = await CorrectionService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=envelope,
    )
    await db_session.commit()

    await db_session.refresh(item)
    assert item.grams == Decimal("220")
    assert item.kcal != old_kcal
    # 220 × 159 / 100 = 349.80
    assert item.kcal == Decimal("349.80")
    assert item.source == "user_corrected"
    assert "grams" in result.changed_fields


async def test_correction_grava_audit_event(db_session: AsyncSession, admin_user):
    """SP-74: audit_event(before/after/actor='llm') gravado."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito de frango",
        "peito_de_frango_grelhado",
        150,
    )
    envelope = _correction("frango", {"grams": 200})
    await CorrectionService(db_session).apply_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    events = list(
        (
            await db_session.execute(select(AuditEvent).where(AuditEvent.action == "correct"))
        ).scalars()
    )
    assert len(events) == 1
    e = events[0]
    assert e.entity_type == "food_item"
    assert e.entity_id == item.id
    assert e.before["grams"] == 150.0
    assert e.after["grams"] == 200.0


async def test_correction_ambiguous_does_not_persist(db_session: AsyncSession, admin_user):
    """SP-71: correção ambígua não altera nada (LLM path via CorrectionService)."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito de frango",
        "peito_de_frango_grelhado",
        150,
        meal_slot="lunch",
    )
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "coxa de frango",
        "coxa_de_frango_cozida",
        200,
        meal_slot="dinner",
    )
    envelope = _correction("frango", {"grams": 220})
    with pytest.raises(AmbiguousTarget):
        await CorrectionService(db_session).apply_from_llm(
            user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
        )


async def test_correction_on_closed_day_blocks(db_session: AsyncSession, admin_user):
    """SP-73/INV-5: correção em dia fechado → DayClosedError."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    dl.status = "closed"
    dl.closed_at = datetime.now(UTC)
    await db_session.commit()

    envelope = _correction("frango", {"grams": 200})
    with pytest.raises(DayClosedError):
        await CorrectionService(db_session).apply_from_llm(
            user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
        )


# ---------------------------------------------------------------------------
# DeletionService — SP-80, SP-82, INV-10
# ---------------------------------------------------------------------------


async def test_deletion_soft_deletes_and_audits(db_session: AsyncSession, admin_user):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )

    envelope = _deletion("frango")
    await DeletionService(db_session).apply_from_llm(
        user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
    )
    await db_session.commit()

    await db_session.refresh(item)
    assert item.deleted_at is not None

    events = list(
        (
            await db_session.execute(select(AuditEvent).where(AuditEvent.action == "delete"))
        ).scalars()
    )
    assert len(events) == 1
    assert events[0].after is None


async def test_deletion_closed_day_blocks(db_session: AsyncSession, admin_user):
    """SP-82: deleção em dia fechado → DayClosedError."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    dl.status = "closed"
    await db_session.commit()

    envelope = _deletion("frango")
    with pytest.raises(DayClosedError):
        await DeletionService(db_session).apply_from_llm(
            user=admin_user, day_log_id=dl.id, message_id=None, envelope=envelope
        )


# ---------------------------------------------------------------------------
# REST endpoints — SP-81
# ---------------------------------------------------------------------------


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def test_delete_food_item_endpoint(client: AsyncClient, admin_user, db_session: AsyncSession):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    await _login(client)

    resp = await client.delete(f"/records/food-items/{item.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "food"
    assert body["already_deleted"] is False


async def test_delete_endpoint_idempotent(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """SP-81: DELETE 2ª chamada retorna 200 com already_deleted=True."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    await _login(client)

    r1 = await client.delete(f"/records/food-items/{item.id}")
    assert r1.status_code == 200 and r1.json()["already_deleted"] is False

    r2 = await client.delete(f"/records/food-items/{item.id}")
    assert r2.status_code == 200
    assert r2.json()["already_deleted"] is True


async def test_delete_endpoint_closed_day_returns_409(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    dl.status = "closed"
    await db_session.commit()
    await _login(client)

    resp = await client.delete(f"/records/food-items/{item.id}")
    assert resp.status_code == 409
    assert resp.json()["code"] == "conflict_closed_day"


async def test_patch_food_item_recomputes_macros(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    item = await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    await _login(client)

    resp = await client.patch(f"/records/food-items/{item.id}", json={"grams": 250})
    assert resp.status_code == 200
    body = resp.json()
    # 250 × 159 / 100 = 397.50
    assert body["kcal"] == pytest.approx(397.50)


# ---------------------------------------------------------------------------
# INV-4 — recompute pós correção/deleção
# ---------------------------------------------------------------------------


async def test_snapshot_recomputes_after_correction(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    from app.services.daily_recompute import DailyRecomputeService

    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    snap_before = (await db_session.execute(select(DailySnapshot))).scalar_one()
    kcal_before = snap_before.kcal_in
    version_before = snap_before.version

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="correct_record",
                confidence=0.9,
                user_text_summary="Ajuste.",
                needs_clarification=False,
                correction={
                    "target_hint": "frango",
                    "changes": {"grams": 250},
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "corrija frango 250g"})

    await db_session.refresh(snap_before)
    # 250 × 159/100 = 397.50 (era 238.50 = 150×159/100)
    assert snap_before.kcal_in > kcal_before
    assert snap_before.kcal_in == Decimal("397.50")
    assert snap_before.version > version_before


async def test_snapshot_recomputes_after_deletion(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        150,
    )
    from app.services.daily_recompute import DailyRecomputeService

    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="delete_record",
                confidence=0.9,
                user_text_summary="Remoção.",
                needs_clarification=False,
                deletion={"target_hint": "frango", "confidence": 0.9},
            )
        )
    )
    await client.post("/chat/messages", json={"text": "remova o frango"})

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    await db_session.refresh(snap)
    assert snap.kcal_in == Decimal("0")


# ---------------------------------------------------------------------------
# End-to-end via chat: ambiguidade vira clarify
# ---------------------------------------------------------------------------


async def test_ambiguous_correction_via_chat_returns_clarify(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "peito frango",
        "peito_de_frango_grelhado",
        150,
        meal_slot="lunch",
    )
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "coxa frango",
        "coxa_de_frango_cozida",
        200,
        meal_slot="dinner",
    )
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="correct_record",
                confidence=0.9,
                user_text_summary=".",
                needs_clarification=False,
                correction={
                    "target_hint": "frango",
                    "changes": {"grams": 220},
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "corrija o frango"})

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert assistant.llm_intent == "clarify"
    assert "mais de um registro" in assistant.content.lower() or "qual" in assistant.content.lower()

    # nada foi alterado
    items = list((await db_session.execute(select(FoodItem))).scalars())
    assert all(i.grams != Decimal("220") for i in items)
