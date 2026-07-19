"""Fase 7 — Consulta e fechamento do dia.

Cobre SP-90 (GET /days/today), SP-91 (GET /days/{date}), SP-92 (timezone),
SP-100 (close_day intent), SP-101 (idempotência), SP-102 (recompute pré-close),
SP-103 (narrative baseada em snapshot já calculado), SP-104 (disclaimer),
INV-5 (dia fechado é imutável).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.nutrition.local_tbca import LocalTBCACatalog
from app.integrations.nutrition.seed import seed_from_csv
from app.models import AuditEvent, DayLog, Message
from app.schemas.llm import LLMEnvelope
from app.services.correction import CorrectionService, DayClosedError
from app.services.daily_recompute import DailyRecomputeService
from app.services.day_close import DayCloseService
from app.services.day_query import DayQueryService
from app.services.deletion import DeletionService
from app.services.meal import MealService

pytestmark = pytest.mark.asyncio


DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed(session: AsyncSession) -> None:
    await seed_from_csv(session)
    await session.commit()


async def _day_log(session: AsyncSession, user):
    from app.repositories.day_log import DayLogRepository

    local_date = datetime.now(ZoneInfo(user.timezone)).date()
    dl = await DayLogRepository(session).get_or_create(user_id=user.id, log_date=local_date)
    await session.commit()
    return dl


async def _create_food(session: AsyncSession, user, day_log_id, name, normalized, grams):
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
                    "detected_name": name,
                    "normalized_name": normalized,
                    "grams_estimate": grams,
                    "confidence": 0.9,
                    "is_estimate": False,
                }
            ],
        }
    )
    result = await service.create_from_llm(
        user=user, day_log_id=day_log_id, message_id=None, envelope=envelope
    )
    await session.commit()
    return result.items[0]


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# SP-90 — GET /days/today
# ---------------------------------------------------------------------------


async def test_get_today_returns_empty_snapshot_when_no_records(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.get("/days/today")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "open"
    assert body["totals"]["kcal_in"] == 0.0
    assert body["totals"]["water_ml"] == 0
    assert body["narrative"] is None
    assert body["records"]["food"] == []
    assert body["records"]["water"] == []


async def test_get_today_reflects_registered_food(
    client: AsyncClient, admin_user, db_session: AsyncSession
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
    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    await _login(client)
    resp = await client.get("/days/today")
    assert resp.status_code == 200
    body = resp.json()
    # 150 × 159/100 = 238.50 kcal
    assert body["totals"]["kcal_in"] == pytest.approx(238.50)
    assert len(body["records"]["food"]) == 1
    assert body["records"]["food"][0]["items"][0]["detected_name"] == "frango"


# ---------------------------------------------------------------------------
# SP-91 — GET /days/{date}
# ---------------------------------------------------------------------------


async def test_get_by_date_not_found_returns_404(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.get("/days/2020-01-01")
    assert resp.status_code == 404
    assert resp.json()["code"] == "day_not_found"


async def test_get_by_date_open_day_returns_status_open(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    dl = await _day_log(db_session, admin_user)
    await _login(client)
    resp = await client.get(f"/days/{dl.log_date.isoformat()}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"


# ---------------------------------------------------------------------------
# SP-92 — timezone (usa users.timezone)
# ---------------------------------------------------------------------------


async def test_get_today_uses_user_timezone_not_utc(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """SP-92: mensagem enviada 23:30 local pertence ao dia LOCAL, não UTC.

    Não simulamos a hora, mas garantimos que o day_log criado bate com
    `local_today(user.timezone)` e não com `datetime.utcnow().date()`.
    """
    await _login(client)
    resp = await client.get("/days/today")
    body = resp.json()
    expected = datetime.now(ZoneInfo(admin_user.timezone)).date().isoformat()
    assert body["date"] == expected


# ---------------------------------------------------------------------------
# SP-100 — Fechamento por chat
# ---------------------------------------------------------------------------


async def test_close_day_via_chat_intent(
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
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="close_day",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
            )
        )
    )
    fake_anthropic.queue_narrative(
        "Dia com boa distribuição de proteínas, hidratação abaixo do usual."
    )

    resp = await client.post("/chat/messages", json={"text": "encerrar dia"})
    assert resp.status_code == 202

    await db_session.commit()
    dl_after = (await db_session.execute(select(DayLog).where(DayLog.id == dl.id))).scalar_one()
    await db_session.refresh(dl_after)
    assert dl_after.status == "closed"
    assert dl_after.closed_at is not None

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "close_day"
    assert "encerrado" in assistant.content.lower()
    assert DISCLAIMER in assistant.content
    assert "distribuição de proteínas" in assistant.content


# ---------------------------------------------------------------------------
# SP-101 — Idempotência
# ---------------------------------------------------------------------------


async def test_close_day_idempotent_second_call_does_not_change_state(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
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
    await _login(client)

    # 1ª chamada REST fecha o dia.
    fake_anthropic.queue_narrative("Primeiro fechamento — proteínas ok.")
    resp1 = await client.post(f"/days/{dl.log_date.isoformat()}/close")
    assert resp1.status_code == 200
    body1 = resp1.json()
    assert body1["status"] == "closed"
    assert body1["was_already_closed"] is False
    closed_at_first = body1["closed_at"]
    version_first = body1["snapshot_version"]
    narrative_first = body1["narrative"]

    # 2ª chamada: mesmo endpoint, mesma data. Idempotente.
    fake_anthropic.queue_narrative("SEGUNDA narrativa — não deveria aparecer.")
    resp2 = await client.post(f"/days/{dl.log_date.isoformat()}/close")
    assert resp2.status_code == 200
    body2 = resp2.json()
    assert body2["status"] == "closed"
    assert body2["was_already_closed"] is True
    # closed_at não muda, snapshot version não incrementa por causa do close.
    assert body2["closed_at"] == closed_at_first
    assert body2["snapshot_version"] == version_first
    assert body2["narrative"] == narrative_first
    # A segunda narrativa enfileirada NÃO foi consumida.
    assert "SEGUNDA narrativa" not in body2["narrative"]


# ---------------------------------------------------------------------------
# SP-102 — Recompute pré-fechamento
# ---------------------------------------------------------------------------


async def test_close_forces_recompute_before_freezing(
    admin_user,
    fake_anthropic,
    db_session: AsyncSession,
):
    """Registro adicionado DEPOIS do último recompute deve ser refletido no
    snapshot congelado pelo close (Const. Art. III §10 / INV-4).
    """
    await _seed(db_session)
    dl = await _day_log(db_session, admin_user)
    # Cria item, recomputa uma vez.
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "frango",
        "peito_de_frango_grelhado",
        100,
    )
    r1 = await DailyRecomputeService(db_session).recompute(dl.id)
    kcal_after_first = r1.snapshot.kcal_in

    # Adiciona MAIS um item; NÃO recomputa manualmente.
    await _create_food(
        db_session,
        admin_user,
        dl.id,
        "arroz",
        "arroz_branco_cozido",
        100,
    )
    await db_session.commit()

    fake_anthropic.queue_narrative("Ok.")
    result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )

    assert result.day_log.status == "closed"
    assert result.snapshot.kcal_in > kcal_after_first


# ---------------------------------------------------------------------------
# SP-103 — narrative alimentada por totais calculados
# ---------------------------------------------------------------------------


async def test_narrative_receives_precomputed_totals(
    admin_user, fake_anthropic, db_session: AsyncSession
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
    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    fake_anthropic.queue_narrative("resumo textual.")
    await DayCloseService(db_session, anthropic=fake_anthropic).close_today(user=admin_user)

    assert len(fake_anthropic.narrative_calls) == 1
    payload = fake_anthropic.narrative_calls[0]["totals_payload"]
    # SP-103: LLM recebe TOTALS já calculados (Const. Art. II §5, INV-1).
    assert payload["kcal_in"] == pytest.approx(238.50)
    assert "protein_g" in payload
    assert "warning_codes" in payload
    # Não vazamos IDs de entidades no payload da narrativa.
    assert "food_records" not in payload
    assert "items" not in payload


# ---------------------------------------------------------------------------
# SP-104 — Disclaimer sempre presente
# ---------------------------------------------------------------------------


async def test_narrative_always_ends_with_disclaimer(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    await _seed(db_session)
    await _day_log(db_session, admin_user)

    fake_anthropic.queue_narrative("Dia leve, poucos itens registrados.")
    result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )
    assert result.narrative.rstrip().endswith(DISCLAIMER)


async def test_narrative_disclaimer_present_even_on_llm_error(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    """Se a LLM falhar, disclaimer + fallback ainda são entregues."""
    await _seed(db_session)
    await _day_log(db_session, admin_user)

    # Nenhuma narrativa enfileirada → FakeAnthropic devolve text=None +
    # error='empty_narrative'.
    result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )
    assert DISCLAIMER in result.narrative
    assert result.day_log.status == "closed"


async def test_disclaimer_not_duplicated_if_llm_returns_it(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    await _seed(db_session)
    await _day_log(db_session, admin_user)
    fake_anthropic.queue_narrative(f"Resumo curto. {DISCLAIMER}")
    result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )
    # Aparece só uma vez, mesmo que o modelo tenha incluído por conta.
    assert result.narrative.count(DISCLAIMER) == 1


# ---------------------------------------------------------------------------
# INV-5 — dia fechado é imutável
# ---------------------------------------------------------------------------


async def test_closed_day_blocks_new_food_correction(
    admin_user, fake_anthropic, db_session: AsyncSession
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
    fake_anthropic.queue_narrative("ok")
    await DayCloseService(db_session, anthropic=fake_anthropic).close_today(user=admin_user)
    await db_session.commit()

    envelope = LLMEnvelope.model_validate(
        {
            "intent": "correct_record",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "correction": {
                "target_hint": "frango",
                "changes": {"grams": 250},
                "confidence": 0.9,
            },
        }
    )
    with pytest.raises(DayClosedError):
        await CorrectionService(db_session).apply_from_llm(
            user=admin_user,
            day_log_id=dl.id,
            message_id=None,
            envelope=envelope,
        )


async def test_closed_day_blocks_deletion(admin_user, fake_anthropic, db_session: AsyncSession):
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
    fake_anthropic.queue_narrative("ok")
    await DayCloseService(db_session, anthropic=fake_anthropic).close_today(user=admin_user)
    await db_session.commit()

    envelope = LLMEnvelope.model_validate(
        {
            "intent": "delete_record",
            "confidence": 0.9,
            "user_text_summary": ".",
            "needs_clarification": False,
            "deletion": {"target_hint": "frango", "confidence": 0.9},
        }
    )
    with pytest.raises(DayClosedError):
        await DeletionService(db_session).apply_from_llm(
            user=admin_user,
            day_log_id=dl.id,
            message_id=None,
            envelope=envelope,
        )


async def test_closed_day_snapshot_reads_are_frozen(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    """INV-5: leitura de dia fechado NÃO dispara recompute mesmo se
    novos records aparecerem — snapshot é fonte de verdade."""
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
    fake_anthropic.queue_narrative("ok")
    close_result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )
    frozen_kcal = close_result.snapshot.kcal_in
    frozen_version = close_result.snapshot.version
    await db_session.commit()

    # 2ª leitura via DayQueryService — sem recomputar.
    payload = await DayQueryService(db_session).get_today(user=admin_user)
    assert payload.status == "closed"
    assert payload.snapshot_version == frozen_version
    assert Decimal(str(payload.totals["kcal_in"])) == frozen_kcal


# ---------------------------------------------------------------------------
# Audit — INV-10
# ---------------------------------------------------------------------------


async def test_close_records_audit_event(admin_user, fake_anthropic, db_session: AsyncSession):
    await _seed(db_session)
    await _day_log(db_session, admin_user)
    fake_anthropic.queue_narrative("ok")
    result = await DayCloseService(db_session, anthropic=fake_anthropic).close_today(
        user=admin_user
    )
    await db_session.commit()

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    close_events = [e for e in events if e.entity_type == "day_log" and e.action == "close"]
    assert len(close_events) == 1
    event = close_events[0]
    assert event.entity_id == result.day_log.id
    assert event.before == {"status": "open"}
    assert event.after["status"] == "closed"


# ---------------------------------------------------------------------------
# query_day intent (SP-90 via chat)
# ---------------------------------------------------------------------------


async def test_query_day_intent_returns_totals_via_chat(
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
    await DailyRecomputeService(db_session).recompute(dl.id)
    await db_session.commit()

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="query_day",
                confidence=0.9,
                user_text_summary=".",
                needs_clarification=False,
            )
        )
    )
    await client.post("/chat/messages", json={"text": "como foi o dia hoje?"})

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "query_day"
    # 238 kcal aparece no resumo (int truncado).
    assert "238" in assistant.content
    assert DISCLAIMER in assistant.content
