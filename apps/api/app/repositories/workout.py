"""WorkoutRepository — acesso a DB de sessões/exercícios/séries de treino.

SP-120..127. Toda query é filtrada por `user_id` (Const. Art. V §21).
Retorna tuples brutos; agrupamento/histórico é feito no `WorkoutService`.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkoutExercise, WorkoutSession, WorkoutSet

# `workout_set` é `WorkoutSet | None` por conta do LEFT JOIN em
# `exercise_history_rows` (sessões com exercício mas ainda sem séries).
HistoryRow = tuple[WorkoutSession, WorkoutExercise, WorkoutSet | None]


class WorkoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active_session(self, user_id: uuid.UUID) -> WorkoutSession | None:
        """INV-15: no máximo uma sessão `active` por usuário (enforce no DB)."""
        stmt = (
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "active",
            )
            .order_by(WorkoutSession.started_at.desc())
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_session(self, user_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession | None:
        stmt = select(WorkoutSession).where(
            WorkoutSession.id == session_id,
            WorkoutSession.user_id == user_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_session(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID,
        workout_type: str,
        detected_name: str,
        started_at: datetime,
    ) -> WorkoutSession:
        session = WorkoutSession(
            user_id=user_id,
            day_log_id=day_log_id,
            workout_type=workout_type,
            detected_name=detected_name,
            started_at=started_at,
            status="active",
        )
        self.session.add(session)
        await self.session.flush()
        return session

    async def end_session(
        self,
        session: WorkoutSession,
        *,
        ended_at: datetime,
        end_reason: str,
    ) -> WorkoutSession:
        session.status = "ended"
        session.ended_at = ended_at
        session.end_reason = end_reason
        return session

    async def next_exercise_index(self, session_id: uuid.UUID) -> int:
        stmt = select(WorkoutExercise.sequence_index).where(
            WorkoutExercise.workout_session_id == session_id
        )
        indexes = list((await self.session.execute(stmt)).scalars())
        return max(indexes, default=-1) + 1

    async def create_exercise(
        self,
        *,
        user_id: uuid.UUID,
        workout_session_id: uuid.UUID,
        name: str,
        normalized_name: str,
        sequence_index: int,
        started_at: datetime,
    ) -> WorkoutExercise:
        exercise = WorkoutExercise(
            user_id=user_id,
            workout_session_id=workout_session_id,
            name=name,
            normalized_name=normalized_name,
            sequence_index=sequence_index,
            started_at=started_at,
        )
        self.session.add(exercise)
        await self.session.flush()
        return exercise

    async def last_exercise(self, session_id: uuid.UUID) -> WorkoutExercise | None:
        """INV-16: último exercício da sessão (por `sequence_index`)."""
        stmt = (
            select(WorkoutExercise)
            .where(WorkoutExercise.workout_session_id == session_id)
            .order_by(WorkoutExercise.sequence_index.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def next_set_index(self, exercise_id: uuid.UUID) -> int:
        stmt = select(WorkoutSet.sequence_index).where(
            WorkoutSet.workout_exercise_id == exercise_id
        )
        indexes = list((await self.session.execute(stmt)).scalars())
        return max(indexes, default=-1) + 1

    async def create_set(
        self,
        *,
        workout_exercise_id: uuid.UUID,
        sequence_index: int,
        weight_kg: Decimal,
        reps: int,
        notes: str | None,
    ) -> WorkoutSet:
        workout_set = WorkoutSet(
            workout_exercise_id=workout_exercise_id,
            sequence_index=sequence_index,
            weight_kg=weight_kg,
            reps=reps,
            notes=notes,
        )
        self.session.add(workout_set)
        await self.session.flush()
        return workout_set

    async def exercise_history_rows(
        self,
        *,
        user_id: uuid.UUID,
        normalized_name: str,
        limit: int,
    ) -> list[HistoryRow]:
        """Rows (sessão, exercício, série) de sessões **encerradas** cujo
        exercício tem `normalized_name` com prefixo igual ao passado
        (SP-121 fuzzy: "supino_reto" casa com "supino_reto_barra"). LEFT
        JOIN em sets para cobrir histórico sem séries. Ordenado por
        `ended_at` desc, série asc.

        `limit` aplica no número de *sessões* — o service agrupa/trunca.
        """
        stmt = (
            select(WorkoutSession, WorkoutExercise, WorkoutSet)
            .join(WorkoutExercise, WorkoutExercise.workout_session_id == WorkoutSession.id)
            .join(WorkoutSet, WorkoutSet.workout_exercise_id == WorkoutExercise.id, isouter=True)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "ended",
                WorkoutExercise.normalized_name.like(f"{normalized_name}%"),
            )
            .order_by(WorkoutSession.ended_at.desc(), WorkoutExercise.sequence_index.asc())
            # limite generoso: o agrupamento por sessão trunca para `limit`
            .limit(limit * 50)
        )
        rows = list((await self.session.execute(stmt)).all())
        return [(s, e, st) for s, e, st in rows]

    async def exercises_with_sets(
        self,
        session_id: uuid.UUID,
    ) -> list[tuple[WorkoutExercise, list[WorkoutSet]]]:
        """Todos os exercícios da sessão com suas séries (para SP-126).

        Ordenado por `sequence_index` do exercício e da série — o service
        monta o `notes` JSON com os IDs (INV-17: só referência, sem FK de
        atividade → exercício).
        """
        stmt = (
            select(WorkoutExercise, WorkoutSet)
            .join(
                WorkoutSet,
                WorkoutSet.workout_exercise_id == WorkoutExercise.id,
                isouter=True,
            )
            .where(WorkoutExercise.workout_session_id == session_id)
            .order_by(
                WorkoutExercise.sequence_index.asc(),
                WorkoutSet.sequence_index.asc(),
            )
        )
        rows = list((await self.session.execute(stmt)).all())
        grouped: dict[uuid.UUID, WorkoutExercise] = {}
        sets_by_exercise: dict[uuid.UUID, list[WorkoutSet]] = {}
        order: list[uuid.UUID] = []
        for exercise, workout_set in rows:
            if exercise.id not in grouped:
                grouped[exercise.id] = exercise
                sets_by_exercise[exercise.id] = []
                order.append(exercise.id)
            if workout_set is not None:
                sets_by_exercise[exercise.id].append(workout_set)
        return [(grouped[eid], sets_by_exercise[eid]) for eid in order]

    async def list_sessions_ended(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[WorkoutSession]:
        stmt = (
            select(WorkoutSession)
            .where(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "ended",
            )
            .order_by(WorkoutSession.ended_at.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())
