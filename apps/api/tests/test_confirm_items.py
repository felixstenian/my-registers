"""SP-24 chat-side — intent confirm_items.

Cobre:
- Scope='all' confirma todos os food_items/beverage_records pendentes do dia.
- Scope='specific' usa TargetMatcher; unmatched hints não bloqueiam.
- Sem itens pendentes → clarify (`no_pending_confirmation`).
- Dia fechado → clarify (`conflict_closed_day`).
- Nenhum hint bateu → clarify (`confirmation_no_match`) sem confirmar nada.
- Audit event `action='confirm'` por entidade confirmada (INV-10).
- Confirmação NÃO recomputa snapshot (macros não mudam).
- End-to-end via chat resolve o loop reportado pelo teste manual do café.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, DailySnapshot, FoodItem, Message
from app.schemas.llm import LLMEnvelope
from app.services.confirmation import ConfirmationService, NoPendingConfirmation
from app.services.correction import DayClosedError
from app.services.daily_recompute import DailyRecomputeService
from app.services.day_close import DayCloseService
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user):
    from app.repositories.day_log import DayLogRepository

    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


async def _create_pending_food(session: AsyncSession, user, dl_id, name, normalized, grams):
    catalog = LocalTBCACatalog(session)
    service = MealService(session, catalog)
    envelope = LLMEnvelope.model_validate(
        {
            "intent": "log_food",
            "confidence": 0.4,  # baixa → needs_confirmation
            "user_text_summary": ".",
            "needs_clarification": False,
            "meal_slot": "breakfast",
            "food_items": [
                {
                    "detected_name": name,
                    "normalized_name": normalized,
                    "grams_estimate": grams,
                    "confidence": 0.4,
                    "is_estimate": True,
                }
            ],
        }
    )
    result = await service.create_from_llm(
        user=user, day_log_id=dl_id, message_id=None, envelope=envelope
    )
    await session.commit()
    return result.items[0]


def _confirm_envelope(*, scope="all", target_hints=None) -> LLMEnvelope:
    return LLMEnvelope.model_validate(
        {
            "intent": "confirm_items",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "confirmation": {
                "scope": scope,
                "target_hints": target_hints or [],
                "confidence": 0.9,
            },
        }
    )


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# ConfirmationService (unit-ish)
# ---------------------------------------------------------------------------


async def test_confirm_all_flags_pending_items(admin_user, db_session: AsyncSession):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    a = await _create_pending_food(db_session, admin_user, dl.id, "pao ceda", "pao_frances", 45)
    b = await _create_pending_food(
        db_session,
        admin_user,
        dl.id,
        "queijo prato",
        "queijo_prato",
        22,
    )
    assert a.needs_confirmation is True
    assert b.needs_confirmation is True

    outcome = await ConfirmationService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_confirm_envelope(scope="all"),
    )
    assert len(outcome.confirmed) == 2
    assert outcome.unmatched_hints == []
    await db_session.refresh(a)
    await db_session.refresh(b)
    assert a.needs_confirmation is False
    assert b.needs_confirmation is False


async def test_confirm_specific_targets_only_named_items(admin_user, db_session: AsyncSession):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    pao = await _create_pending_food(db_session, admin_user, dl.id, "pao ceda", "pao_frances", 45)
    queijo = await _create_pending_food(
        db_session,
        admin_user,
        dl.id,
        "queijo prato",
        "queijo_prato",
        22,
    )

    outcome = await ConfirmationService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_confirm_envelope(scope="specific", target_hints=["pao"]),
    )
    assert len(outcome.confirmed) == 1
    assert outcome.confirmed[0].entity_id == pao.id
    await db_session.refresh(pao)
    await db_session.refresh(queijo)
    assert pao.needs_confirmation is False
    assert queijo.needs_confirmation is True


async def test_confirm_specific_records_unmatched_hints(admin_user, db_session: AsyncSession):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_pending_food(db_session, admin_user, dl.id, "pao ceda", "pao_frances", 45)

    outcome = await ConfirmationService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_confirm_envelope(scope="specific", target_hints=["mocotó", "pao"]),
    )
    assert len(outcome.confirmed) == 1
    assert "mocotó" in outcome.unmatched_hints


async def test_confirm_no_pending_raises(admin_user, db_session: AsyncSession):
    await _seed(db_session)
    await _day_log(db_session, admin_user)
    with pytest.raises(NoPendingConfirmation):
        await ConfirmationService(db_session).apply_from_llm(
            user=admin_user,
            day_log_id=(await _day_log(db_session, admin_user)).id,
            message_id=None,
            envelope=_confirm_envelope(scope="all"),
        )


async def test_confirm_blocked_on_closed_day(admin_user, fake_anthropic, db_session: AsyncSession):
    """INV-5: dia fechado bloqueia confirmação (mesmo comportamento de
    correction/deletion)."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_pending_food(db_session, admin_user, dl.id, "pao", "pao_frances", 45)
    fake_anthropic.queue_narrative("ok")
    await DayCloseService(db_session, anthropic=fake_anthropic).close_today(user=admin_user)
    await db_session.commit()

    with pytest.raises(DayClosedError):
        await ConfirmationService(db_session).apply_from_llm(
            user=admin_user,
            day_log_id=dl.id,
            message_id=None,
            envelope=_confirm_envelope(scope="all"),
        )


# ---------------------------------------------------------------------------
# Snapshot & audit
# ---------------------------------------------------------------------------


async def test_confirmation_does_not_recompute_snapshot(admin_user, db_session: AsyncSession):
    """Macros não mudam com confirmação → snapshot version não incrementa."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_pending_food(db_session, admin_user, dl.id, "pao", "pao_frances", 45)
    r0 = await DailyRecomputeService(db_session).recompute(dl.id)
    version_before = r0.snapshot.version
    kcal_before = r0.snapshot.kcal_in
    await db_session.commit()

    await ConfirmationService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_confirm_envelope(scope="all"),
    )
    await db_session.flush()

    snap = (await db_session.execute(select(DailySnapshot))).scalar_one()
    await db_session.refresh(snap)
    assert snap.version == version_before
    assert snap.kcal_in == kcal_before


async def test_confirmation_records_audit_events(admin_user, db_session: AsyncSession):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    a = await _create_pending_food(db_session, admin_user, dl.id, "pao", "pao_frances", 45)
    b = await _create_pending_food(
        db_session,
        admin_user,
        dl.id,
        "queijo prato",
        "queijo_prato",
        22,
    )
    await ConfirmationService(db_session).apply_from_llm(
        user=admin_user,
        day_log_id=dl.id,
        message_id=None,
        envelope=_confirm_envelope(scope="all"),
    )
    await db_session.flush()

    events = list(
        (
            await db_session.execute(select(AuditEvent).where(AuditEvent.action == "confirm"))
        ).scalars()
    )
    ids = {e.entity_id for e in events}
    assert {a.id, b.id}.issubset(ids)
    for e in events:
        assert e.before == {"needs_confirmation": True}
        assert e.after == {"needs_confirmation": False}


# ---------------------------------------------------------------------------
# End-to-end via chat (o bug do feedback do café)
# ---------------------------------------------------------------------------


async def test_confirmation_via_chat_ends_the_loop(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    db_session: AsyncSession,
):
    """Reproduz o feedback: usuário confirma no chat, backend NÃO cria
    nenhum log_food novo — só remove o `needs_confirmation`."""
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_pending_food(db_session, admin_user, dl.id, "pao ceda", "pao_frances", 45)
    await _create_pending_food(
        db_session,
        admin_user,
        dl.id,
        "queijo prato",
        "queijo_prato",
        22,
    )

    await _login(client)
    fake_anthropic.queue(_fake_llm_result(_confirm_envelope(scope="all")))
    await client.post("/chat/messages", json={"text": "confirmo os itens"})

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "confirm_items"
    assert "Confirmei 2 itens" in assistant.content

    # Nenhum FoodItem novo foi criado — só temos os 2 originais.
    items = list((await db_session.execute(select(FoodItem))).scalars())
    assert len(items) == 2
    assert all(i.needs_confirmation is False for i in items)


async def test_confirmation_with_no_pending_falls_to_clarify(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    db_session: AsyncSession,
):
    await _seed(db_session)
    await _day_log(db_session, admin_user)
    await _login(client)
    fake_anthropic.queue(_fake_llm_result(_confirm_envelope(scope="all")))
    await client.post("/chat/messages", json={"text": "confirmo"})

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "clarify"
    assert "pendente" in assistant.content.lower()


async def test_confirmation_specific_no_match_falls_to_clarify(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    db_session: AsyncSession,
):
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    await _create_pending_food(db_session, admin_user, dl.id, "pao", "pao_frances", 45)
    await _login(client)
    fake_anthropic.queue(
        _fake_llm_result(_confirm_envelope(scope="specific", target_hints=["mocotó"]))
    )
    await client.post("/chat/messages", json={"text": "confirma o mocotó"})

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "clarify"
    # Nenhum item foi confirmado.
    items = list((await db_session.execute(select(FoodItem))).scalars())
    assert all(i.needs_confirmation is True for i in items)


def _fake_llm_result(envelope):
    """Helper local (o conftest não expõe este por fixture — usamos direto)."""
    from app.integrations.anthropic.client import LLMCallResult

    return LLMCallResult(
        envelope=envelope,
        raw_tool_input=envelope.model_dump(mode="json"),
        tokens_input=50,
        tokens_output=20,
        model="fake-model",
        prompt_version="system_v2",
        error=None,
    )
