"""WorkoutService — sessões de treino estruturado (sessão → exercícios → séries).

SP-120..127 (núcleo Bloco 3). Métodos autônomos — não dependem do
MessageProcessor; testáveis isoladamente com repo real (Postgres).

- INV-15: `start_session` auto-encerra a sessão ativa anterior
  (`end_reason='auto_new_session'`) e **consolida em `activity_record`**.
- INV-16: `log_set` liga a série ao último exercício da sessão ativa.
- SP-126: `end_session` / auto-close consolidam a sessão em 1
  `activity_record` (`calc_method='workout_session'`, MET fixo por tipo).
- `weight_kg=None` → barra olímpica (`DEFAULT_OLYMPIC_BAR_KG`).
- Auditoria (Const. Art. III §11) em toda criação/encerramento.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationAppError
from app.integrations.nutrition.normalize import normalize_name
from app.models import (
    ActivityRecord,
    WorkoutExercise,
    WorkoutSession,
    WorkoutSet,
    WorkoutTemplate,
)
from app.repositories.activity import ActivityRecordRepository
from app.repositories.food import AuditEventRepository
from app.repositories.user import UserRepository
from app.repositories.workout import WorkoutRepository
from app.schemas.llm import WorkoutTemplateIn

DEFAULT_OLYMPIC_BAR_KG = Decimal("20")

EndReason = Literal["user", "auto_new_session", "auto_close_day"]

# SP-126: kcal = MET fixo × weight_kg × horas. Macro por tipo de treino.
# `push/pull/upper` → 5.0; `legs/lower` → 6.0; `full_body` → 5.5.
# `cardio`/`other` não especificados → fallback conservador 5.0.
_WORKOUT_TYPE_MET: dict[str, Decimal] = {
    "push": Decimal("5.0"),
    "pull": Decimal("5.0"),
    "upper": Decimal("5.0"),
    "legs": Decimal("6.0"),
    "lower": Decimal("6.0"),
    "full_body": Decimal("5.5"),
    "cardio": Decimal("5.0"),
    "other": Decimal("5.0"),
}


@dataclass(slots=True)
class SetSummary:
    sequence_index: int
    weight_kg: Decimal
    reps: int
    notes: str | None


@dataclass(slots=True)
class ExerciseHistory:
    """Histórico de um exercício para SP-121/SP-127."""

    exercise_name: str
    sessions: list[SessionHistory] = field(default_factory=list)
    first_time: bool = False
    pr_weight_kg: Decimal | None = None
    pr_reps_at_weight: int | None = None
    pr_date: date | None = None


@dataclass(slots=True)
class SessionHistory:
    session_id: uuid.UUID
    workout_type: str
    ended_at: datetime | None
    sets: list[SetSummary] = field(default_factory=list)


class WorkoutService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = WorkoutRepository(session)
        self.audit = AuditEventRepository(session)
        self.activities = ActivityRecordRepository(session)
        self.users = UserRepository(session)

    async def start_session(
        self,
        *,
        user_id: uuid.UUID,
        day_log_id: uuid.UUID,
        workout_type: str,
        detected_name: str | None = None,
        message_id: uuid.UUID | None = None,
        started_at: datetime | None = None,
    ) -> tuple[WorkoutSession, WorkoutSession | None]:
        """SP-120. Cria sessão ativa; auto-encerra a anterior (INV-15) e a
        consolida em `activity_record` (fluxo SP-120 → SP-126).

        Retorna `(nova_sessão, sessão_encerrada_por_auto)`.
        """
        started = started_at or datetime.now(UTC)
        existing = await self.repo.get_active_session(user_id)
        closed_previous: WorkoutSession | None = None
        if existing is not None:
            closed_previous = await self.repo.end_session(
                existing,
                ended_at=started,
                end_reason="auto_new_session",
            )
            await self.audit.record(
                user_id=user_id,
                entity_type="workout_session",
                entity_id=existing.id,
                action="update",
                actor="user",
                message_id=message_id,
                after={
                    "status": "ended",
                    "ended_at": started.isoformat(),
                    "end_reason": "auto_new_session",
                },
            )
            await self.consolidate_to_activity(
                user_id=user_id,
                session_id=existing.id,
                message_id=message_id,
            )

        session = await self.repo.create_session(
            user_id=user_id,
            day_log_id=day_log_id,
            workout_type=workout_type,
            detected_name=detected_name or f"Treino de {workout_type}",
            started_at=started,
        )
        await self.audit.record(
            user_id=user_id,
            entity_type="workout_session",
            entity_id=session.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "workout_type": workout_type,
                "detected_name": session.detected_name,
                "started_at": session.started_at.isoformat(),
                "status": "active",
            },
        )
        return session, closed_previous

    async def add_exercise(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        exercise_name: str,
        message_id: uuid.UUID | None = None,
    ) -> tuple[WorkoutExercise, ExerciseHistory]:
        """SP-121. Adiciona exercício na sessão ativa e consulta histórico.

        `exercise_name` vazio → `ValidationAppError` (SP-121 não cria registro).
        """
        name = exercise_name.strip()
        if not name:
            raise ValidationAppError(
                "exercise_name is required",
                code="workout_exercise_name_required",
            )

        session = await self.repo.get_session(user_id, session_id)
        if session is None:
            raise NotFoundError("workout session not found", code="workout_session_not_found")
        if session.status != "active":
            raise ValidationAppError(
                "workout session is not active",
                code="workout_session_not_active",
            )

        normalized = normalize_name(name)
        index = await self.repo.next_exercise_index(session_id)
        exercise = await self.repo.create_exercise(
            user_id=user_id,
            workout_session_id=session_id,
            name=name,
            normalized_name=normalized,
            sequence_index=index,
            started_at=datetime.now(UTC),
        )
        await self.audit.record(
            user_id=user_id,
            entity_type="workout_exercise",
            entity_id=exercise.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "workout_session_id": str(session_id),
                "name": name,
                "normalized_name": normalized,
                "sequence_index": index,
            },
        )

        history = await self._history_for(user_id=user_id, normalized_name=normalized)
        history.exercise_name = name
        return exercise, history

    async def log_set(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        weight_kg: Decimal | None,
        reps: int,
        notes: str | None = None,
        message_id: uuid.UUID | None = None,
    ) -> WorkoutSet:
        """SP-122. Registra série no último exercício da sessão (INV-16).

        `weight_kg=None` → barra olímpica (20kg, SP-122 default). Sem
        exercício na sessão → erro (INV-16).
        """
        session = await self.repo.get_session(user_id, session_id)
        if session is None:
            raise NotFoundError("workout session not found", code="workout_session_not_found")
        if session.status != "active":
            raise ValidationAppError(
                "workout session is not active",
                code="workout_session_not_active",
            )

        exercise = await self.repo.last_exercise(session_id)
        if exercise is None:
            raise ValidationAppError(
                "no exercise in active session — add one first",
                code="workout_no_exercise",
            )

        resolved_weight = weight_kg if weight_kg is not None else DEFAULT_OLYMPIC_BAR_KG
        if resolved_weight <= 0 or reps <= 0:
            raise ValidationAppError(
                "weight_kg and reps must be positive",
                code="workout_set_invalid_values",
            )

        index = await self.repo.next_set_index(exercise.id)
        workout_set = await self.repo.create_set(
            workout_exercise_id=exercise.id,
            sequence_index=index,
            weight_kg=resolved_weight,
            reps=reps,
            notes=notes,
        )
        await self.audit.record(
            user_id=user_id,
            entity_type="workout_set",
            entity_id=workout_set.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "workout_exercise_id": str(exercise.id),
                "sequence_index": index,
                "weight_kg": float(resolved_weight),
                "reps": reps,
                "notes": notes,
            },
        )
        return workout_set

    async def end_session(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        end_reason: EndReason = "user",
        message_id: uuid.UUID | None = None,
        ended_at: datetime | None = None,
    ) -> WorkoutSession:
        """SP-124. Encerra sessão ativa e consolida em `activity_record`
        (SP-126)."""
        session = await self.repo.get_session(user_id, session_id)
        if session is None:
            raise NotFoundError("workout session not found", code="workout_session_not_found")
        if session.status != "active":
            raise ValidationAppError(
                "workout session is not active",
                code="workout_session_not_active",
            )

        ended = ended_at or datetime.now(UTC)
        session = await self.repo.end_session(
            session,
            ended_at=ended,
            end_reason=end_reason,
        )
        await self.audit.record(
            user_id=user_id,
            entity_type="workout_session",
            entity_id=session.id,
            action="update",
            actor="user",
            message_id=message_id,
            after={
                "status": "ended",
                "ended_at": ended.isoformat(),
                "end_reason": end_reason,
                "duration_minutes": _duration_minutes(session),
            },
        )
        await self.consolidate_to_activity(
            user_id=user_id,
            session_id=session.id,
            message_id=message_id,
        )
        return session

    async def end_active_session(
        self,
        *,
        user_id: uuid.UUID,
        end_reason: EndReason = "user",
        message_id: uuid.UUID | None = None,
        ended_at: datetime | None = None,
    ) -> WorkoutSession | None:
        """SP-125. Encerra a sessão ativa do usuário, se houver, consolidando
        em `activity_record`. Retorna `None` quando não há sessão ativa."""
        active = await self.repo.get_active_session(user_id)
        if active is None:
            return None
        return await self.end_session(
            user_id=user_id,
            session_id=active.id,
            end_reason=end_reason,
            message_id=message_id,
            ended_at=ended_at,
        )

    async def consolidate_to_activity(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        message_id: uuid.UUID | None = None,
    ) -> ActivityRecord:
        """SP-126. Cria/atualiza o `activity_record` da sessão encerrada.

        - `duration_minutes = ended_at - started_at`.
        - `kcal_burned = MET_fixo(workout_type) × weight_kg × horas`
          (`calc_method='workout_session'`, `activity_type='strength'`).
        - Sem `weight_kg` no perfil → `kcal_burned=NULL` + warning
          `weight_kg_required_for_kcal` (treino registrado, kcal pendente).
        - `notes` = JSON com `workout_session_id` e IDs de exercícios/séries
          (INV-17: somente referência reversa, sem FK atividade→exercício).
        - Idempotente: upsert por `workout_session_id` (não duplica em
          reconsoidação).
        """
        session = await self.repo.get_session(user_id, session_id)
        if session is None:
            raise NotFoundError("workout session not found", code="workout_session_not_found")
        if session.ended_at is None:
            raise ValidationAppError(
                "workout session is not ended",
                code="workout_session_not_ended",
            )

        duration = Decimal(str(_duration_minutes(session)))
        if duration <= 0:
            duration = Decimal("0.01")

        user = await self.users.get_by_id(user_id)
        weight_kg = user.weight_kg if user is not None else None

        met = _WORKOUT_TYPE_MET.get(session.workout_type, Decimal("5.0"))
        kcal_burned: Decimal | None
        warnings: list[dict[str, Any]] = []
        if weight_kg is not None:
            hours = duration / Decimal("60")
            kcal_burned = (met * weight_kg * hours).quantize(Decimal("0.01"))
        else:
            kcal_burned = None
            warnings.append({"code": "weight_kg_required_for_kcal"})

        exercises = await self.repo.exercises_with_sets(session_id)
        notes_payload = {
            "workout_session_id": str(session.id),
            "workout_type": session.workout_type,
            "exercises": [
                {
                    "exercise_id": str(ex.id),
                    "name": ex.name,
                    "normalized_name": ex.normalized_name,
                    "sequence_index": ex.sequence_index,
                    "sets": [
                        {
                            "set_id": str(st.id),
                            "sequence_index": st.sequence_index,
                            "weight_kg": float(st.weight_kg),
                            "reps": st.reps,
                        }
                        for st in sets
                    ],
                }
                for ex, sets in exercises
            ],
        }

        record = await self.activities.get_by_workout_session(session_id)
        if record is not None:
            # Reconsolidação (INV-17): atualiza o mesmo activity_record.
            record.detected_name = session.detected_name
            record.normalized_name = normalize_name(session.detected_name)
            record.activity_type = "strength"
            record.duration_minutes = duration
            record.met_value = met
            record.kcal_burned = kcal_burned
            record.notes = json.dumps(notes_payload)
            await self.session.flush()
            await self.audit.record(
                user_id=user_id,
                entity_type="activity_record",
                entity_id=record.id,
                action="update",
                actor="user",
                message_id=message_id,
                after={
                    "workout_session_id": str(session.id),
                    "duration_minutes": float(duration),
                    "kcal_burned": None if kcal_burned is None else float(kcal_burned),
                    "calc_method": "workout_session",
                },
            )
            return record

        record = await self.activities.create(
            user_id=user_id,
            day_log_id=session.day_log_id,
            message_id=message_id,
            occurred_at=session.started_at,
            detected_name=session.detected_name,
            normalized_name=normalize_name(session.detected_name),
            activity_type="strength",
            duration_minutes=duration,
            distance_km=None,
            intensity="unknown",
            met_value=met,
            kcal_burned=kcal_burned,
            calc_method="workout_session",
            confidence=None,
            notes=json.dumps(notes_payload),
            workout_session_id=session.id,
        )
        await self.audit.record(
            user_id=user_id,
            entity_type="activity_record",
            entity_id=record.id,
            action="create",
            actor="user",
            message_id=message_id,
            after={
                "workout_session_id": str(session.id),
                "duration_minutes": float(duration),
                "kcal_burned": None if kcal_burned is None else float(kcal_burned),
                "calc_method": "workout_session",
            },
        )
        return record

    async def history(
        self,
        *,
        user_id: uuid.UUID,
        exercise_name: str,
        limit: int = 3,
    ) -> ExerciseHistory:
        """SP-127. Histórico das últimas `limit` sessões + PR pessoal."""
        normalized = normalize_name(exercise_name)
        history = await self._history_for(
            user_id=user_id,
            normalized_name=normalized,
            session_limit=limit,
        )
        history.exercise_name = exercise_name.strip()
        return history

    async def _history_for(
        self,
        *,
        user_id: uuid.UUID,
        normalized_name: str,
        session_limit: int = 3,
    ) -> ExerciseHistory:
        """Agrupa rows do repo em `ExerciseHistory` (SESSÕES distintas,
        PR = maior peso × reps naquele peso)."""
        rows = await self.repo.exercise_history_rows(
            user_id=user_id,
            normalized_name=normalized_name,
            limit=session_limit,
        )
        result = ExerciseHistory(exercise_name=normalized_name)

        session_map: dict[uuid.UUID, SessionHistory] = {}
        pr_weight: Decimal | None = None
        pr_reps: int | None = None
        pr_date: date | None = None

        for session, _exercise, workout_set in rows:
            if session.id not in session_map:
                if len(session_map) >= session_limit:
                    continue
                session_map[session.id] = SessionHistory(
                    session_id=session.id,
                    workout_type=session.workout_type,
                    ended_at=session.ended_at,
                )
            if workout_set is not None:
                session_map[session.id].sets.append(
                    SetSummary(
                        sequence_index=workout_set.sequence_index,
                        weight_kg=workout_set.weight_kg,
                        reps=workout_set.reps,
                        notes=workout_set.notes,
                    )
                )
                if pr_weight is None or workout_set.weight_kg > pr_weight:
                    pr_weight = workout_set.weight_kg
                    pr_reps = workout_set.reps
                    pr_date = session.ended_at.date() if session.ended_at else None
                elif workout_set.weight_kg == pr_weight and (
                    pr_reps is None or workout_set.reps > pr_reps
                ):
                    pr_reps = workout_set.reps
                    pr_date = session.ended_at.date() if session.ended_at else None

        result.sessions = list(session_map.values())
        result.pr_weight_kg = pr_weight
        result.pr_reps_at_weight = pr_reps
        result.pr_date = pr_date
        result.first_time = pr_weight is None
        return result

    async def register_template(
        self,
        *,
        user_id: uuid.UUID,
        template: WorkoutTemplateIn,
        message_id: uuid.UUID | None = None,
    ) -> WorkoutTemplate:
        """SP-171. Cadastra treino reutilizável a partir do payload LLM.

        Validações semânticas (ambiguidade/insuficiência → `ValidationAppError`
        para o `MessageProcessor` converter em `clarify`):
        - `template.name` em branco → `workout_template_name_required`.
        - Zero exercícios → `workout_template_no_exercises`.
        - `target_sets`/`target_reps` ambos ausentes → `clarify` pedindo o
          plano (sem inventar séries/reps — Const. §3).
        - Exercício sem `target_sets`/`target_reps` → `clarify` pedindo o
          plano dele.

        Cria `workout_templates` (active=true) + `workout_template_exercises`
        com `normalized_name` derivado no backend. Auditoria em cada criação
        (Const. Art. III §11).
        """
        name = (template.name or "").strip()
        if not name:
            raise ValidationAppError(
                "template name is required",
                code="workout_template_name_required",
            )
        if not template.exercises:
            raise ValidationAppError(
                "template has no exercises",
                code="workout_template_no_exercises",
            )

        has_plan = any(
            (ex.target_sets is not None and ex.target_reps is not None)
            for ex in template.exercises
        )
        if not has_plan:
            raise ValidationAppError(
                "missing target plan — o plano de séries e repetições é "
                "obrigatório para cadastrar o treino (ex.: 3 séries de 8-12 rep)",
                code="workout_template_plan_missing",
            )
        exercises_missing_plan = [
            ex.exercise_name
            for ex in template.exercises
            if ex.target_sets is None or ex.target_reps is None
        ]
        if exercises_missing_plan:
            raise ValidationAppError(
                "missing target plan for exercises: "
                + ", ".join(exercises_missing_plan)
                + " — informe séries e repetições para todos os exercícios",
                code="workout_template_plan_missing",
            )

        created = await self.repo.create_template(
            user_id=user_id,
            name=name,
            workout_type=template.workout_type,
            muscle_groups=template.muscle_groups,
        )
        created_exercises = []
        for ex in template.exercises:
            exercise = await self.repo.create_template_exercise(
                template_id=created.id,
                exercise_name=ex.exercise_name,
                normalized_name=normalize_name(ex.exercise_name),
                target_sets=ex.target_sets,
                target_reps=ex.target_reps,
            )
            created_exercises.append(exercise)
            await self.audit.record(
                user_id=user_id,
                entity_type="workout_template_exercise",
                entity_id=exercise.id,
                action="create",
                actor="llm",
                message_id=message_id,
                after={
                    "template_id": str(created.id),
                    "exercise_name": ex.exercise_name,
                    "normalized_name": normalize_name(ex.exercise_name),
                    "target_sets": ex.target_sets,
                    "target_reps": ex.target_reps,
                },
            )

        await self.audit.record(
            user_id=user_id,
            entity_type="workout_template",
            entity_id=created.id,
            action="create",
            actor="llm",
            message_id=message_id,
            after={
                "name": name,
                "workout_type": template.workout_type,
                "muscle_groups": template.muscle_groups,
                "exercises": [ex.exercise_name for ex in created_exercises],
                "active": True,
            },
        )
        return created


def _duration_minutes(session: WorkoutSession) -> float | None:
    if session.started_at is None or session.ended_at is None:
        return None
    delta = session.ended_at - session.started_at
    return round(delta.total_seconds() / 60, 1)
