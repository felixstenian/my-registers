"""Fase 8 — Relatório semanal (SP-110..113 / INV-8).

Cobre:
- SP-110: janela = últimos 7 dias fechados; menos de 7 → warning insufficient_history.
- SP-111: totais/médias vêm de SQL sobre daily_snapshots (LLM só narrativa).
- SP-112: chamadas repetidas sem mudanças → mesmo id e reused=True.
- SP-113: per_day do mais antigo para o mais recente.
- INV-8: dias abertos são ignorados.
- End-to-end via chat com intent weekly_summary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DailySnapshot, DayLog
from app.services.weekly_report import WeeklyReportService

pytestmark = pytest.mark.asyncio


DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


async def _create_closed_day(
    session: AsyncSession,
    *,
    user,
    log_date: date,
    kcal_in: Decimal = Decimal("2000"),
    kcal_out: Decimal = Decimal("400"),
    protein_g: Decimal = Decimal("120"),
    water_ml: int = 2000,
    version: int = 1,
) -> tuple[DayLog, DailySnapshot]:
    day_log = DayLog(
        user_id=user.id,
        log_date=log_date,
        status="closed",
        closed_at=datetime.now(UTC),
    )
    session.add(day_log)
    await session.flush()
    snap = DailySnapshot(
        user_id=user.id,
        day_log_id=day_log.id,
        kcal_in=kcal_in,
        kcal_out=kcal_out,
        kcal_balance=kcal_in - kcal_out,
        protein_g=protein_g,
        carbs_g=Decimal("250"),
        fat_g=Decimal("60"),
        fiber_g=Decimal("25"),
        sodium_mg=Decimal("2000"),
        calcium_mg=Decimal("800"),
        iron_mg=Decimal("15"),
        potassium_mg=Decimal("3000"),
        water_ml=water_ml,
        other_liquids_ml=500,
        computed_at=datetime.now(UTC),
        warnings=[],
        version=version,
    )
    session.add(snap)
    await session.flush()
    return day_log, snap


async def _create_open_day(session: AsyncSession, *, user, log_date: date) -> DayLog:
    day_log = DayLog(user_id=user.id, log_date=log_date, status="open")
    session.add(day_log)
    await session.flush()
    return day_log


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# SP-110 — janela + insufficient_history
# ---------------------------------------------------------------------------


async def test_generate_empty_when_no_closed_days(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    """Sem dias fechados → days_included=0 + warning insufficient_history."""
    fake_anthropic.queue_weekly_narrative("resumo vazio")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.days_included == 0
    codes = [w["code"] for w in result.report.warnings]
    assert "insufficient_history" in codes
    assert result.report.warnings[0]["days_available"] == 0


async def test_generate_uses_up_to_seven_most_recent_closed(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    # 9 dias fechados → só os 7 mais recentes entram.
    for i in range(9):
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("ok")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.days_included == 7
    assert result.report.window_end == today
    assert result.report.window_start == today - timedelta(days=6)
    assert result.report.warnings == []


async def test_generate_less_than_seven_days_still_returns(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    for i in range(3):
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("ok")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.days_included == 3
    codes = [w["code"] for w in result.report.warnings]
    assert "insufficient_history" in codes
    assert result.report.warnings[0]["days_available"] == 3


# ---------------------------------------------------------------------------
# SP-111 — cálculos determinísticos (LLM não soma)
# ---------------------------------------------------------------------------


async def test_totals_and_averages_are_deterministic(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    for i in range(3):
        await _create_closed_day(
            db_session,
            user=admin_user,
            log_date=today - timedelta(days=i),
            kcal_in=Decimal("2000"),
            kcal_out=Decimal("500"),
            protein_g=Decimal("120"),
            water_ml=2000,
        )
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("ok")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    totals = result.report.totals
    averages = result.report.averages
    assert totals["kcal_in"] == 6000.0
    assert totals["kcal_out"] == 1500.0
    assert totals["kcal_balance"] == 4500.0
    assert totals["water_ml"] == 6000  # int
    assert averages["kcal_in"] == 2000.0
    assert averages["water_ml"] == 2000  # int
    # LLM recebe totais + averages, NUNCA snapshots crus.
    call = fake_anthropic.weekly_narrative_calls[0]["totals_payload"]
    assert "totals" in call and "averages" in call
    assert "per_day" not in call  # sinaliza que só o cliente HTTP recebe per_day


async def test_llm_lies_do_not_affect_stored_totals(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    """INV-1: mesmo que a LLM tente injetar números no texto, os campos
    numéricos armazenados são calculados pelo backend."""
    today = date(2026, 7, 15)
    await _create_closed_day(db_session, user=admin_user, log_date=today, kcal_in=Decimal("1500"))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative(
        "kcal_in=999999 kcal_out=0 (lorem ipsum de tentar enganar o backend)"
    )
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.totals["kcal_in"] == 1500.0  # backend calculou


# ---------------------------------------------------------------------------
# SP-112 — idempotência
# ---------------------------------------------------------------------------


async def test_repeated_generate_reuses_same_row(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    for i in range(3):
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("primeira")
    r1 = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(user=admin_user)

    fake_anthropic.queue_weekly_narrative("SEGUNDA — não deveria aparecer")
    r2 = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(user=admin_user)

    assert r2.reused is True
    assert r2.report.id == r1.report.id
    assert r2.report.version == r1.report.version
    assert "SEGUNDA" not in (r2.report.narrative or "")
    # A 2ª chamada NÃO consome a fila de narrativa.
    assert len(fake_anthropic.weekly_narrative_calls) == 1


async def test_regenerate_when_snapshot_version_changes(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    dl, snap = await _create_closed_day(db_session, user=admin_user, log_date=today)
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("v1")
    r1 = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(user=admin_user)
    r1_id = r1.report.id
    version_before = r1.report.version

    # Simula recompute do snapshot: version incrementa (INV-4).
    snap.version = 2
    snap.kcal_in = Decimal("2500")
    snap.kcal_balance = Decimal("2100")
    await db_session.flush()

    fake_anthropic.queue_weekly_narrative("v2 atualizado")
    r2 = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(user=admin_user)

    assert r2.reused is False
    assert r2.report.id == r1_id  # upsert por window mantém ID
    assert r2.report.version == version_before + 1
    assert r2.report.totals["kcal_in"] == 2500.0
    assert "v2 atualizado" in r2.report.narrative


# ---------------------------------------------------------------------------
# SP-113 — ordenação per_day ASC
# ---------------------------------------------------------------------------


async def test_per_day_ordered_from_oldest_to_newest(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    today = date(2026, 7, 15)
    # Inserção fora de ordem para garantir que a ordem final é lógica, não DB order.
    for i in [3, 0, 2, 1]:
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("ok")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    dates = [item["date"] for item in result.report.per_day]
    assert dates == sorted(dates)
    assert dates[0] == (today - timedelta(days=3)).isoformat()
    assert dates[-1] == today.isoformat()


# ---------------------------------------------------------------------------
# INV-8 — dias abertos ignorados
# ---------------------------------------------------------------------------


async def test_open_days_are_ignored(admin_user, fake_anthropic, db_session: AsyncSession):
    today = date(2026, 7, 15)
    await _create_closed_day(db_session, user=admin_user, log_date=today)
    await _create_open_day(db_session, user=admin_user, log_date=today - timedelta(days=1))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("ok")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.days_included == 1
    per_day_dates = [d["date"] for d in result.report.per_day]
    assert (today - timedelta(days=1)).isoformat() not in per_day_dates


# ---------------------------------------------------------------------------
# Disclaimer sempre presente
# ---------------------------------------------------------------------------


async def test_narrative_always_ends_with_disclaimer(
    admin_user, fake_anthropic, db_session: AsyncSession
):
    await _create_closed_day(db_session, user=admin_user, log_date=date(2026, 7, 15))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("Semana com hidratação estável.")
    result = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    assert result.report.narrative.rstrip().endswith(DISCLAIMER)


# ---------------------------------------------------------------------------
# Endpoint GET /weekly
# ---------------------------------------------------------------------------


async def test_get_weekly_endpoint(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    db_session: AsyncSession,
):
    today = date(2026, 7, 15)
    for i in range(2):
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("Consistência semanal.")
    await _login(client)
    resp = await client.get("/weekly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days_included"] == 2
    assert body["window_end"] == today.isoformat()
    assert body["narrative"].endswith(DISCLAIMER)
    assert len(body["per_day"]) == 2


# ---------------------------------------------------------------------------
# End-to-end via chat (weekly_summary intent)
# ---------------------------------------------------------------------------


async def test_weekly_summary_via_chat(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    from app.models import Message

    today = date(2026, 7, 15)
    for i in range(3):
        await _create_closed_day(db_session, user=admin_user, log_date=today - timedelta(days=i))
    await db_session.commit()

    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="weekly_summary",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
            )
        )
    )
    fake_anthropic.queue_weekly_narrative("Semana boa, hidratação constante.")

    await _login(client)
    resp = await client.post("/chat/messages", json={"text": "como foi minha semana?"})
    assert resp.status_code == 202

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "weekly_summary"
    assert "Resumo semanal" in assistant.content
    assert "3 dias encerrados" in assistant.content
    assert DISCLAIMER in assistant.content


async def test_weekly_summary_via_chat_when_no_closed_days(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    from app.models import Message

    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="weekly_summary",
                confidence=0.95,
                user_text_summary=".",
                needs_clarification=False,
            )
        )
    )
    # narrativa não deveria ser chamada, mas por precaução:
    fake_anthropic.queue_weekly_narrative("fallback")

    resp = await client.post("/chat/messages", json={"text": "resumo da semana?"})
    assert resp.status_code == 202

    assistant = next(
        m for m in (await db_session.execute(select(Message))).scalars() if m.role == "assistant"
    )
    assert assistant.llm_intent == "weekly_summary"
    assert "Ainda não há dias encerrados" in assistant.content


# ---------------------------------------------------------------------------
# Isolamento por usuário
# ---------------------------------------------------------------------------


async def test_reports_are_isolated_per_user(admin_user, fake_anthropic, db_session: AsyncSession):
    from app.core.security import hash_password
    from app.repositories.user import UserRepository

    other = await UserRepository(db_session).create(
        email="other@example.com",
        password_hash=hash_password("otherotherother"),
        display_name="Other",
    )
    await db_session.commit()

    today = date(2026, 7, 15)
    await _create_closed_day(db_session, user=admin_user, log_date=today, kcal_in=Decimal("1500"))
    await _create_closed_day(db_session, user=other, log_date=today, kcal_in=Decimal("3000"))
    await db_session.commit()

    fake_anthropic.queue_weekly_narrative("A")
    r_admin = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(
        user=admin_user
    )
    fake_anthropic.queue_weekly_narrative("B")
    r_other = await WeeklyReportService(db_session, anthropic=fake_anthropic).generate(user=other)

    assert r_admin.report.totals["kcal_in"] == 1500.0
    assert r_other.report.totals["kcal_in"] == 3000.0
    assert r_admin.report.id != r_other.report.id
