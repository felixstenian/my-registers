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
from app.models import ActivityRecord, WorkoutExercise, WorkoutSession, WorkoutSet, WorkoutTemplate
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


async def test_t309_messages_via_column_and_index(db_session: AsyncSession):
    """T-B309 (SP-173): migration 0013 adiciona `messages.via` com default
    'food' (sem backfill) e o índice `idx_messages_user_via` que alimenta
    listagem/polling por user_id+via."""
    col = (
        await db_session.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name='messages' AND column_name='via'"
            )
        )
    ).scalar_one_or_none()
    assert col is not None
    assert "food" in (col or "")

    idx = (
        (
            await db_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename='messages' AND indexname='idx_messages_user_via'"
                )
            )
        )
        .scalars()
        .all()
    )
    assert idx == ["idx_messages_user_via"]


def test_t311_system_prompt_selected_by_via():
    """T-B311 (SP-173): `_load_system_prompt_for_via` devolve prompts
    distintos por `via` — `food` mantém o system_v2.md (alimentação),
    `workout` usa o system_workout_v2.md (treinos dedicados)."""
    from app.integrations.anthropic.client import _load_system_prompt_for_via

    food_prompt = _load_system_prompt_for_via("food")
    workout_prompt = _load_system_prompt_for_via("workout")
    assert food_prompt != workout_prompt
    assert "nutrição" in food_prompt or "macros" in food_prompt or "log_food" in food_prompt
    assert "workout_log_set" in workout_prompt
    assert "log_food" not in workout_prompt


async def test_t312_workout_templates_schema(db_session: AsyncSession):
    """T-B312 (SP-170/171/INV-18): migration 0014 cria as tabelas de
    templates reutilizáveis com índices de isolamento por usuário."""
    tables = (
        (
            await db_session.execute(
                text(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname='public' AND tablename IN "
                    "('workout_templates','workout_template_exercises')"
                )
            )
        )
        .scalars()
        .all()
    )
    assert set(tables) == {"workout_templates", "workout_template_exercises"}

    cols = (
        await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='workout_templates'"
            )
        )
    ).scalars()
    colset = set(cols)
    assert {"id", "user_id", "name", "workout_type", "muscle_groups", "active"} <= colset

    ex_cols = (
        await db_session.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='workout_template_exercises'"
            )
        )
    ).scalars()
    ex_colset = set(ex_cols)
    assert {
        "template_id",
        "exercise_name",
        "normalized_name",
        "target_sets",
        "target_reps",
    } <= ex_colset

    idx = (
        (
            await db_session.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename "
                    "IN ('workout_templates','workout_template_exercises')"
                )
            )
        )
        .scalars()
        .all()
    )
    assert "ix_workout_templates_user_active" in idx
    assert "ix_workout_template_exercises_template" in idx


async def test_t313_register_template_creates_template_and_exercises(
    db_session: AsyncSession, admin_user
):
    """T-B313 (SP-171): `register_template` cria `workout_templates`
    active=true + `workout_template_exercises` com o plano e auditoria."""
    from app.schemas.llm import WorkoutTemplateIn

    svc = WorkoutService(db_session)
    template = await svc.register_template(
        user_id=admin_user.id,
        template=WorkoutTemplateIn(
            name="Peito e tríceps",
            workout_type="push",
            muscle_groups=["peito", "ombro", "triceps"],
            exercises=[
                {
                    "exercise_name": "Supino reto com barra",
                    "target_sets": 3,
                    "target_reps": 10,
                },
                {
                    "exercise_name": "Elevação lateral",
                    "target_sets": 4,
                    "target_reps": 12,
                },
            ],
        ),
    )
    exercises = await svc.repo.list_template_exercises(template.id)
    assert template.user_id == admin_user.id
    assert template.active is True
    assert template.workout_type == "push"
    assert template.name == "Peito e tríceps"
    assert {e.exercise_name for e in exercises} == {
        "Supino reto com barra",
        "Elevação lateral",
    }
    assert all(e.normalized_name for e in exercises)
    assert {e.target_sets for e in exercises} == {3, 4}
    assert {e.target_reps for e in exercises} == {10, 12}

    templates = list(
        (
            await db_session.execute(
                select(WorkoutTemplate).where(WorkoutTemplate.user_id == admin_user.id)
            )
        ).scalars()
    )
    assert len(templates) == 1


async def test_t313_register_template_validations(db_session: AsyncSession, admin_user):
    """T-B313 (SP-171): ambiguidade/insuficiência vira `ValidationAppError`
    para o processor converter em `clarify` — nome vazio, sem exercícios e
    sem plano de séries/reps são rejeitados."""
    from app.schemas.llm import WorkoutTemplateIn

    svc = WorkoutService(db_session)

    with pytest.raises(ValidationAppError) as exc1:
        await svc.register_template(
            user_id=admin_user.id,
            template=WorkoutTemplateIn(name="   ", workout_type="push"),
        )
    assert exc1.value.code == "workout_template_name_required"

    with pytest.raises(ValidationAppError) as exc2:
        await svc.register_template(
            user_id=admin_user.id,
            template=WorkoutTemplateIn(name="Só nome", workout_type="push"),
        )
    assert exc2.value.code == "workout_template_no_exercises"

    with pytest.raises(ValidationAppError) as exc3:
        await svc.register_template(
            user_id=admin_user.id,
            template=WorkoutTemplateIn(
                name="Sem plano",
                workout_type="pull",
                exercises=[{"exercise_name": "Remada curvada"}],
            ),
        )
    assert exc3.value.code == "workout_template_plan_missing"

    # Nenhum template foi criado nas falhas acima.
    count = list((await db_session.execute(select(WorkoutTemplate))).scalars())
    assert count == []


async def _login(client) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _seed_template(session: AsyncSession, user, *, active: bool = True):
    from app.schemas.llm import WorkoutTemplateIn

    template = await WorkoutService(session).register_template(
        user_id=user.id,
        template=WorkoutTemplateIn(
            name="Peito e tríceps",
            workout_type="push",
            muscle_groups=["peito", "triceps"],
            exercises=[
                {"exercise_name": "Supino reto", "target_sets": 3, "target_reps": 10},
            ],
        ),
    )
    if not active:
        template.active = False
        await session.flush()
    await session.commit()
    return template


async def test_t314_list_templates_filters_by_active(client, admin_user, db_session: AsyncSession):
    """T-B314 (SP-170): GET /workouts/templates  devolve as abas — `?active=`
    filtra; sem filtro, tudo. Tem que ser user-scoped."""
    from app.schemas.llm import WorkoutTemplateIn

    svc = WorkoutService(db_session)
    await svc.register_template(
        user_id=admin_user.id,
        template=WorkoutTemplateIn(
            name="Treino A",
            workout_type="push",
            exercises=[{"exercise_name": "Supino", "target_sets": 3, "target_reps": 10}],
        ),
    )
    template_b = await svc.register_template(
        user_id=admin_user.id,
        template=WorkoutTemplateIn(
            name="Treino B",
            workout_type="pull",
            exercises=[{"exercise_name": "Remada", "target_sets": 4, "target_reps": 8}],
        ),
    )
    template_b.active = False
    await db_session.commit()

    await _login(client)
    resp = await client.get("/workouts/templates")
    assert resp.status_code == 200
    bodies = resp.json()
    assert {b["name"] for b in bodies} == {"Treino A", "Treino B"}

    resp_active = await client.get("/workouts/templates", params={"active": "true"})
    assert resp_active.status_code == 200
    assert {b["name"] for b in resp_active.json()} == {"Treino A"}

    resp_inactive = await client.get("/workouts/templates", params={"active": "false"})
    assert resp_inactive.status_code == 200
    assert {b["name"] for b in resp_inactive.json()} == {"Treino B"}


async def test_t314_get_template_detail_with_exercises(
    client, admin_user, db_session: AsyncSession
):
    """T-B314 (SP-170): GET /workouts/templates/{id} inclui exercícios-alvo."""
    template = await _seed_template(db_session, admin_user)

    await _login(client)
    resp = await client.get(f"/workouts/templates/{template.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Peito e tríceps"
    assert len(body["exercises"]) == 1
    assert body["exercises"][0]["target_sets"] == 3


async def test_t314_toggle_template_active(client, admin_user, db_session: AsyncSession):
    """T-B314 (SP-172): PATCH /workouts/templates/{id} com `{"active":false}`
    arquiva o template (movendo para a aba Inativos) e audita."""
    template = await _seed_template(db_session, admin_user, active=True)

    await _login(client)
    resp = await client.patch(f"/workouts/templates/{template.id}", json={"active": False})
    assert resp.status_code == 200
    assert resp.json()["active"] is False

    from app.models import AuditEvent

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    assert any(e.action == "update" for e in events)


async def test_t314_template_routes_are_user_scoped(client, admin_user, db_session: AsyncSession):
    """T-B314 (INV-18): usuário não enxerga template de outro usuário."""
    from app.core.security import hash_password
    from app.repositories.user import UserRepository

    other = await UserRepository(db_session).create(
        email="other@example.com",
        password_hash=hash_password("otheradmin"),
        display_name="Other",
    )
    await db_session.commit()
    template = await _seed_template(db_session, other)

    await _login(client)
    resp = await client.get(f"/workouts/templates/{template.id}")
    assert resp.status_code == 404
    resp_patch = await client.patch(f"/workouts/templates/{template.id}", json={"active": False})
    assert resp_patch.status_code == 404
