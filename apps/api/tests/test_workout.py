"""T-B301 (SP-120/INV-15): schema de treino (workout_sessions,
workout_exercises, workout_sets) e invariante de sessão ativa única.

INV-N → integração com Postgres real (conftest aplica as migrations).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationAppError
from app.integrations.anthropic.tool_schema import RECORD_INTENT_INPUT_SCHEMA
from app.models import ActivityRecord, WorkoutExercise, WorkoutSession, WorkoutSet
from app.repositories.day_log import DayLogRepository
from app.schemas.llm import WorkoutSetIn
from app.services.workout import WorkoutService


async def _day_log(session: AsyncSession, user) -> object:
    return await DayLogRepository(session).get_or_create(
        user_id=user.id, log_date=datetime.now(UTC).date()
    )


async def _active_session(session: AsyncSession, user, day_log_id) -> WorkoutSession:
    ws = WorkoutSession(
        user_id=user.id,
        day_log_id=day_log_id,
        workout_type="push",
        detected_name="treino de push",
        started_at=datetime.now(UTC),
        status="active",
    )
    session.add(ws)
    await session.flush()
    return ws


async def test_workout_schema_tables_and_indexes(db_session: AsyncSession):
    """T-B301: 3 tabelas + índices de histórico/ordem criados pela migration."""
    tables = (
        (
            await db_session.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename IN "
                    "('workout_sessions','workout_exercises','workout_sets')"
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(tables) == {"workout_sessions", "workout_exercises", "workout_sets"}

    idx = (
        (
            await db_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename IN "
                    "('workout_sessions','workout_exercises','workout_sets')"
                )
            )
        )
        .scalars()
        .all()
    )
    assert "uq_workout_sessions_user_active" in idx
    assert "ix_workout_exercises_historical" in idx
    assert "ix_workout_exercises_session_seq" in idx
    assert "ix_workout_sets_exercise_seq" in idx


async def test_inv15_only_one_active_session_per_user(db_session: AsyncSession, admin_user):
    """INV-15: adicionar 2ª sessão ativa no mesmo user estoura no índice único
    parcial `(user_id) WHERE status='active'`."""
    dl = await _day_log(db_session, admin_user)
    await _active_session(db_session, admin_user, dl.id)
    await db_session.commit()

    ws2 = WorkoutSession(
        user_id=admin_user.id,
        day_log_id=dl.id,
        workout_type="legs",
        detected_name="treino de perna",
        started_at=datetime.now(UTC),
        status="active",
    )
    db_session.add(ws2)
    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_inv15_ended_session_does_not_block_new_active(db_session: AsyncSession, admin_user):
    """INV-15: sessão `ended` não conflita com uma nova `active`."""
    dl = await _day_log(db_session, admin_user)
    ws = await _active_session(db_session, admin_user, dl.id)
    ws.status = "ended"
    ws.ended_at = datetime.now(UTC)
    ws.end_reason = "user"
    await db_session.commit()

    ws2 = await _active_session(db_session, admin_user, dl.id)
    await db_session.commit()
    assert ws2.status == "active"


async def test_exercise_and_set_insert_with_cascade(db_session: AsyncSession, admin_user):
    """T-B301: inserção de exercise/set na cadeia e cascade de FK
    (apagar sessão remove exercises/sets)."""
    dl = await _day_log(db_session, admin_user)
    ws = await _active_session(db_session, admin_user, dl.id)

    ex = WorkoutExercise(
        user_id=admin_user.id,
        workout_session_id=ws.id,
        name="supino reto com barra",
        normalized_name="supino reto barra",
        sequence_index=0,
        started_at=datetime.now(UTC),
    )
    db_session.add(ex)
    await db_session.flush()

    st = WorkoutSet(
        workout_exercise_id=ex.id,
        sequence_index=0,
        weight_kg=60,
        reps=10,
    )
    db_session.add(st)
    await db_session.flush()
    await db_session.commit()

    await db_session.delete(ws)
    await db_session.commit()

    from sqlalchemy import func, select

    rem_sets = (await db_session.execute(select(func.count()).select_from(WorkoutSet))).scalar_one()
    rem_ex = (
        await db_session.execute(select(func.count()).select_from(WorkoutExercise))
    ).scalar_one()
    assert rem_sets == 0
    assert rem_ex == 0


def test_t302_intent_enum_includes_workout():
    """T-B302: enum de intents exposto pela tool contém os 5 intents de treino."""
    intents = RECORD_INTENT_INPUT_SCHEMA["properties"]["intent"]["enum"]
    assert "workout_start" in intents
    assert "workout_add_exercise" in intents
    assert "workout_log_set" in intents
    assert "workout_end" in intents
    assert "workout_history" in intents


def test_t302_envelope_validates_workout_payloads(make_envelope):
    """T-B302: LLMEnvelope aceita payloads de treino nos 5 intents."""
    env = make_envelope(
        intent="workout_start",
        workout_start={"workout_type": "push", "detected_name": "iniciando treino de push"},
    )
    assert env.workout_start is not None
    assert env.workout_start.workout_type == "push"

    env = make_envelope(
        intent="workout_add_exercise",
        workout_add_exercise={"exercise_name": "supino reto com barra"},
    )
    assert env.workout_add_exercise is not None
    assert env.workout_add_exercise.exercise_name == "supino reto com barra"

    env = make_envelope(
        intent="workout_log_set",
        workout_log_set={"weight_kg": 60, "reps": 10, "notes": "última série pesada"},
    )
    assert env.workout_log_set is not None
    assert env.workout_log_set.weight_kg == 60
    assert env.workout_log_set.reps == 10

    env = make_envelope(intent="workout_end", workout_end={})
    assert env.workout_end is not None

    env = make_envelope(
        intent="workout_history",
        workout_history={"exercise_name": "agachamento"},
    )
    assert env.workout_history is not None
    assert env.workout_history.exercise_name == "agachamento"


def test_t302_workout_set_empty_weight_defaults_to_none():
    """T-B302: `weight_kg` ausente vira None (backend assume barra olímpica)."""
    result = WorkoutSetIn.model_validate({"reps": 8})
    assert result.weight_kg is None
    assert result.reps == 8


# --------------------------------------------------------------------------
# T-B307 — regressões do núcleo de treino (SP-120..SP-127, INV-16/17).
# Complementa `test_workout_service.py` nos fluxos de fronteira entre o
# `WorkoutService` e o resto do sistema.
# --------------------------------------------------------------------------


async def _start(
    session: AsyncSession, user, *, workout_type: str = "push"
) -> tuple[WorkoutSession, object]:
    dl = await _day_log(session, user)
    svc = WorkoutService(session)
    ws, _ = await svc.start_session(user_id=user.id, day_log_id=dl.id, workout_type=workout_type)
    return ws, dl


async def test_sp122_multiple_sets_increment_sequence(db_session: AsyncSession, admin_user):
    """SP-122: duas séries na mesma sessão → sequence_index 0 e 1, ligadas ao
    mesmo exercício (INV-16)."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    ex, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto"
    )
    await db_session.flush()

    s0 = await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=10)
    s1 = await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=62.5, reps=8)
    await db_session.commit()

    assert s0.sequence_index == 0
    assert s1.sequence_index == 1
    assert s0.workout_exercise_id == ex.id
    assert s1.workout_exercise_id == ex.id


async def test_sp122_log_set_rejects_non_positive_values(db_session: AsyncSession, admin_user):
    """SP-122: backend só valida `weight_kg > 0` e `reps > 0` (parser pt-BR é
    da LLM); valores inválidos rejeitados com `workout_set_invalid_values`."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="agachamento")
    await db_session.flush()

    with pytest.raises(ValidationAppError) as exc:
        await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=0, reps=5)
    assert exc.value.code == "workout_set_invalid_values"

    with pytest.raises(ValidationAppError) as exc:
        await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=0)
    assert exc.value.code == "workout_set_invalid_values"


async def test_sp123_subsequent_sets_bind_to_last_exercise(db_session: AsyncSession, admin_user):
    """SP-123: adicionar exercício B após A encerra A implicitamente — série
    subsequente liga-se a B (o último por sequence_index), sem mudança de
    estado explícita em A."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="full_body")
    ex_a, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto"
    )
    ex_b, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="puxada aberta"
    )
    await db_session.flush()

    assert ex_a.sequence_index == 0
    assert ex_b.sequence_index == 1
    # Nenhum estado explícito de encerramento no exercício A
    assert ex_a.started_at is not None

    st = await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=50, reps=12)
    await db_session.commit()

    assert st.workout_exercise_id == ex_b.id

    exs = list(
        (
            await db_session.execute(
                select(WorkoutExercise)
                .where(WorkoutExercise.workout_session_id == ws.id)
                .order_by(WorkoutExercise.sequence_index)
            )
        ).scalars()
    )
    assert [(e.id, e.sequence_index) for e in exs] == [
        (ex_a.id, 0),
        (ex_b.id, 1),
    ]


async def test_sp125_end_active_session_consolidates_and_closes(
    db_session: AsyncSession, admin_user
):
    """SP-125: `end_active_session` encerra a sessão ativa com end_reason
    configurado e consolida em `activity_record` (fluxo close_day)."""
    admin_user.weight_kg = Decimal("80")
    await db_session.flush()

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto")
    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=10)
    await db_session.flush()

    ended = await svc.end_active_session(
        user_id=admin_user.id,
        end_reason="auto_close_day",
        ended_at=ws.started_at + timedelta(minutes=45),
    )
    assert ended is not None and ended.id == ws.id
    assert ended.status == "ended"
    assert ended.end_reason == "auto_close_day"

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()
    assert rec.calc_method == "workout_session"
    assert rec.activity_type == "strength"
    # 5.0 MET × 80 kg × 0.75h = 300 kcal
    assert rec.kcal_burned == Decimal("300.00")


async def test_sp125_end_active_session_noop_without_active(db_session: AsyncSession, admin_user):
    """SP-125: sem sessão ativa, `end_active_session` é no-op (None) e não
    grava activity_record."""
    svc = WorkoutService(db_session)
    result = await svc.end_active_session(user_id=admin_user.id, end_reason="auto_close_day")
    assert result is None

    count = (
        (
            await db_session.execute(
                select(ActivityRecord).where(ActivityRecord.user_id == admin_user.id)
            )
        )
        .scalars()
        .all()
    )
    assert count == []


async def test_inv16_log_set_binds_to_last_exercise_across_sessions_sets(
    db_session: AsyncSession, admin_user
):
    """INV-16 reforçado: após B, serie ainda liga-se a B mesmo com outra
    chamada (não há "volta" ao exercício A)."""
    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="legs")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="agachamento")
    ex_b, _ = await svc.add_exercise(
        user_id=admin_user.id, session_id=ws.id, exercise_name="leg press"
    )
    await db_session.flush()

    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=120, reps=10)
    st2 = await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=130, reps=8)
    await db_session.commit()

    assert st2.workout_exercise_id == ex_b.id


async def test_inv17_soft_delete_activity_record_keeps_session(
    db_session: AsyncSession, admin_user
):
    """INV-17: soft-delete do `activity_record` consolidado NÃO apaga
    `workout_sessions/exercises/sets` (referência reversa apenas)."""
    from datetime import UTC as _UTC

    svc = WorkoutService(db_session)
    ws, _ = await _start(db_session, admin_user, workout_type="push")
    await svc.add_exercise(user_id=admin_user.id, session_id=ws.id, exercise_name="supino reto")
    await svc.log_set(user_id=admin_user.id, session_id=ws.id, weight_kg=60, reps=10)
    await svc.end_session(
        user_id=admin_user.id, session_id=ws.id, ended_at=ws.started_at + timedelta(minutes=30)
    )
    await db_session.flush()

    rec = (
        await db_session.execute(
            select(ActivityRecord).where(ActivityRecord.workout_session_id == ws.id)
        )
    ).scalar_one()

    # soft-delete manual do activity_record
    rec.deleted_at = datetime.now(_UTC)
    await db_session.commit()

    session_rows = list((await db_session.execute(select(WorkoutSession))).scalars())
    assert len(session_rows) == 1
    assert session_rows[0].id == ws.id

    exercises = list((await db_session.execute(select(WorkoutExercise))).scalars())
    assert len(exercises) == 1

    sets = list((await db_session.execute(select(WorkoutSet))).scalars())
    assert len(sets) == 1
    assert sets[0].sequence_index == 0
