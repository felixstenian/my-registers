"""T-B301 (SP-120/INV-15): schema de treino (workout_sessions,
workout_exercises, workout_sets) e invariante de sessão ativa única.

INV-N → integração com Postgres real (conftest aplica as migrations).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkoutExercise, WorkoutSession, WorkoutSet
from app.repositories.day_log import DayLogRepository


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
