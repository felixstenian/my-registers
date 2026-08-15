"""T-B303 (SP-120..124, SP-127; INV-15/16): como os modelos foram validados
via migration no T-B301, este bloco adiciona testes do `WorkoutService`
contra o Postgres real (SP-XX must → integração).

Regressões: usa `db_session` (conftest) já com PostgreSQL de teste.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.models import AuditEvent, WorkoutSession
from app.repositories.day_log import DayLogRepository
from app.services.workout import DEFAULT_OLYMPIC_BAR_KG, WorkoutService


async def _day_log(session: AsyncSession, user) -> object:
    return await DayLogRepository(session).get_or_create(
        user_id=user.id, log_date=datetime.now(UTC).date()
    )


async def _start(
    session: AsyncSession, user, *, workout_type: str = "push", detected: str | None = None
) -> tuple[WorkoutSession, object]:
    dl = await _day_log(session, user)
    svc = WorkoutService(session)
    ws, prev = await svc.start_session(
        user_id=user.id,
        day_log_id=dl.id,
        workout_type=workout_type,
        detected_name=detected,
    )
    return ws, dl


async def test_sp120_start_session_creates_active(db_session: AsyncSession, admin_user):
    """SP-120: sessão `active` com start, sem encerrar anterior (não havia)."""
    svc = WorkoutService(db_session)
    dl = await _day_log(db_session, admin_user)
    ws, prev = await svc.start_session(
        user_id=admin_user.id,
        day_log_id=dl.id,
        workout_type="legs",
        detected_name="treino de perna",
    )
    assert ws.status == "active"
    assert ws.workout_type == "legs"
    assert prev is None
    await db_session.commit()


async def test_inv15_start_auto_ends_previous(db_session: AsyncSession, admin_user):
    """INV-15: novo `workout_start` encerra a sessão ativa anterior com
    `end_reason='auto_new_session'`."""
    ws1, dl = await _start(db_session, admin_user, workout_type="push")
    await db_session.commit()

    svc = WorkoutService(db_session)
    ws2, prev = await svc.start_session(
        user_id=admin_user.id,
        day_log_id=dl.id,
        workout_type="pull",
    )
    await db_session.flush()

    assert prev is not None and prev.id == ws1.id
    assert prev.status == "ended"
    assert prev.end_reason == "auto_new_session"
    await db_session.commit()

    active = await WorkoutService(db_session).repo.get_active_session(admin_user.id)
    assert active is not None and active.id == ws2.id


async def test_sp121_add_exercise_first_time(db_session: AsyncSession, admin_user):
    """SP-121: primeira vez do exercício → `first_time`, sem PR."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    ex, hist = await svc.add_exercise(
        user_id=admin_user.id,
        session_id=ws.id,
        exercise_name="supino reto com barra",
    )
    assert ex.normalized_name == "supino_reto_com_barra"
    assert ex.sequence_index == 0
    assert hist.first_time is True
    await db_session.commit()


async def test_sp121_history_shows_last_session_and_pr(db_session: AsyncSession, admin_user):
    """SP-121/127: após série, histórico lista a última sessão com o
    exercício e o PR (maior peso × maior reps naquele peso)."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    ex, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto"
    )
    await db_session.flush()

    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=10)
    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=8)
    await db_session.commit()
    # encerra para aparecer no histórico (só sessões ended)
    await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()

    hist = await svc.history(user_id=admin_user.id, exercise_name="supino reto")
    assert hist.pr_weight_kg == 60
    assert hist.pr_reps_at_weight == 10
    assert len(hist.sessions) == 1
    assert [(s.weight_kg, s.reps) for s in hist.sessions[0].sets] == [(60, 10), (60, 8)]

    # histórico do ExerciseHistory pelo service add_exercise (outra sessão)
    ws2, _ = await _start(db_session, admin_user, workout_type="push")
    ex2, hist2 = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws2.id, exercise_name="supino reto"
    )
    assert hist2.first_time is False
    assert hist2.pr_weight_kg == 60
    await db_session.commit()


async def test_sp122_log_set_defaults_olympic_bar(db_session: AsyncSession, admin_user):
    """SP-122: `weight_kg=None` → barra olímpica 20kg; série no último
    exercício (INV-16)."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    ex, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="agachamento"
    )
    await db_session.flush()
    st = await svc.log_set(
        user_id=admin_user.id, session_id=ws.id, weight_kg=None, reps=5, notes="só a barra"
    )
    assert st.weight_kg == DEFAULT_OLYMPIC_BAR_KG
    assert st.workout_exercise_id == ex.id
    assert st.sequence_index == 0
    await db_session.commit()


async def test_sp122_log_set_requires_exercise(db_session: AsyncSession, admin_user):
    """INV-16: sem exercício na sessão, log_set falha com `workout_no_exercise`."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    with pytest.raises(ValidationAppError) as exc:
        await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=40, reps=10)
    assert exc.value.code == "workout_no_exercise"


async def test_sp122_log_set_on_inactive_session_fails(db_session: AsyncSession, admin_user):
    """INV-16: sessão encerrada não aceita novas séries."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()
    with pytest.raises(ValidationAppError) as exc:
        await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=40, reps=10)
    assert exc.value.code == "workout_session_not_active"


async def test_sp124_end_session_sets_reason(db_session: AsyncSession, admin_user):
    """SP-124: end marca ended/ended_at/end_reason='user'."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="full_body")
    ended = await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    assert ended.status == "ended"
    assert ended.ended_at is not None
    assert ended.end_reason == "user"
    await db_session.commit()


async def test_audit_events_written_for_workout_mutations(db_session: AsyncSession, admin_user):
    """Const. §11: cada mutação (start/add/log_set/end) grava audit."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto")
    await db_session.flush()
    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=8)
    await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()

    events = list(
        (
            await db_session.execute(select(AuditEvent).where(AuditEvent.user_id == admin_user.id))
        ).scalars()
    )
    actions = sorted(e.action for e in events)
    # 4 mutações de treino + 1 activity_record de consolidação (SP-126)
    assert actions == ["create", "create", "create", "create", "update"]


async def test_sp126_consolidate_met_by_type(db_session: AsyncSession, admin_user):
    """SP-126: end_session consolida em activity_record com MET fixo do
    `workout_type` (push→5.0) × weight_kg × horas, calc_method
    'workout_session' e activity_type 'strength'."""
    from decimal import Decimal

    from app.models import ActivityRecord

    weight = Decimal("80")
    admin_user.weight_kg = weight
    await db_session.flush()

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto")
    await db_session.flush()
    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=10)
    await db_session.flush()

    await svc.end_session(
        user_id=admin_user.id,
        session_id=ws.id,
        ended_at=ws.started_at + timedelta(hours=1),
    )
    await db_session.flush()

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()
    assert rec.calc_method == "workout_session"
    assert rec.activity_type == "strength"
    assert rec.met_value == Decimal("5.0")
    # 5.0 MET × 80 kg × 1h = 400 kcal
    assert rec.kcal_burned == Decimal("400.00")
    assert rec.detected_name == "Treino de push"


async def test_sp126_consolidate_without_weight_kcal_null(db_session: AsyncSession, admin_user):
    """SP-126: sem weight_kg no perfil → activity_record criado com
    `kcal_burned=NULL` (treino registrado, kcal pendente)."""
    from app.models import ActivityRecord

    assert admin_user.weight_kg is None

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="legs")
    await svc.end_session(
        user_id=admin_user.id,
        session_id=ws.id,
        ended_at=ws.started_at + timedelta(minutes=30),
    )
    await db_session.flush()

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()
    assert rec.calc_method == "workout_session"
    assert rec.kcal_burned is None
    assert rec.met_value is not None


async def test_sp126_consolidate_notes_json_exercise_and_set_ids(
    db_session: AsyncSession, admin_user
):
    """SP-126: `notes` guarda JSON com IDs dos exercícios e séries
    (INV-17: somente referência reversa)."""
    import json as json_lib

    from app.models import ActivityRecord

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="full_body")
    ex, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="agachamento livre"
    )
    await db_session.flush()
    st = await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=80, reps=5)
    await db_session.flush()
    await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()
    payload = json_lib.loads(rec.notes)
    assert payload["workout_session_id"] == str(ws.id)
    assert len(payload["exercises"]) == 1
    assert payload["exercises"][0]["exercise_id"] == str(ex.id)
    assert [s["set_id"] for s in payload["exercises"][0]["sets"]] == [str(st.id)]


async def test_sp126_consolidate_idempotent(db_session: AsyncSession, admin_user):
    """INV-17: reconsoidação não duplica activity_record (upsert por
    workout_session_id)."""
    from sqlalchemy import func

    from app.models import ActivityRecord

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="pull")
    await svc.end_session(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()
    await svc.consolidate_to_activity(user_id=admin_user.id, session_id=ws.id)
    await db_session.flush()

    count = (
        await db_session.execute(
            select(func.count())
            .select_from(ActivityRecord)
            .where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()
    assert count == 1


async def test_inv15_auto_close_consolidates_previous(db_session: AsyncSession, admin_user):
    """INV-15 + SP-126: auto-encerrar a sessão anterior consolida em
    activity_record (fluxo start_session → SP-126)."""
    from decimal import Decimal

    from app.models import ActivityRecord

    admin_user.weight_kg = Decimal("70")
    await db_session.flush()

    svc = WorkoutService(db_session)
    ws1, _ = await _start(db_session, admin_user, workout_type="push")
    await db_session.flush()

    ws2, prev = await svc.start_session(
        user_id=admin_user.id,
        day_log_id=ws1.day_log_id,
        workout_type="pull",
    )
    await db_session.flush()
    assert prev is not None and prev.id == ws1.id

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws1.id)
        )
    ).scalar_one()
    assert rec is not None and rec.calc_method == "workout_session"
