"""T-B305 — handlers de treino no chat (SP-120..127 via /chat/messages).

End-to-end pelo pipeline real: POST /chat/messages → fake_anthropic devolve
envelope workout_* → MessageProcessor roteia para `_handle_workout_*` →
persiste → assistant message.

SP-122 parser de peso pt-BR e SP-123 encerramento implícito ficam no
T-B307 (testes de service + fluxo); aqui validamos o roteamento e a
formatação dos 5 intents.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord, Message, WorkoutExercise, WorkoutSession, WorkoutSet

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _send(
    client: AsyncClient,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    *,
    text: str,
    **envelope_overrides,
) -> None:
    envelope = make_envelope(**envelope_overrides)
    fake_anthropic.queue(make_llm_result(envelope))
    resp = await client.post("/chat/messages", json={"text": text})
    assert resp.status_code == 202


async def _get_assistant(db_session: AsyncSession) -> Message:
    messages = list((await db_session.execute(select(Message))).scalars())
    return next(m for m in messages if m.role == "assistant")


async def test_workout_start_routes_and_creates_active_session(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-120: intent workout_start → sessão active criada; assistant com
    cabeçalho + dica do primeiro exercício."""
    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="iniciar treino de push",
        intent="workout_start",
        workout_start={"workout_type": "push"},
    )

    sessions = list((await db_session.execute(select(WorkoutSession))).scalars())
    assert len(sessions) == 1
    assert sessions[0].status == "active"
    assert sessions[0].workout_type == "push"

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_start"
    assert "Iniciei seu treino" in assistant.content
    assert "Nenhum exercício ainda" in assistant.content


async def test_workout_start_auto_ends_previous(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """INV-15: novo start encerra a sessão anterior e avisa na resposta."""
    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    first, _ = await svc.start_session(user_id=admin_user.id, day_log_id=dl.id, workout_type="legs")
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="iniciar treino de pull",
        intent="workout_start",
        workout_start={"workout_type": "pull"},
    )

    # Recarrega o objeto `first` que o background atualizou (identity map
    # da db_session estava com o snapshot antigo).
    db_session.expire_all()
    sessions = list((await db_session.execute(select(WorkoutSession))).scalars())
    assert len(sessions) == 2
    ended_prev = next(s for s in sessions if s.id == first.id)
    assert ended_prev.status == "ended"
    assert ended_prev.end_reason == "auto_new_session"

    assistant = await _get_assistant(db_session)
    assert "Encerrei o treino anterior automaticamente" in assistant.content


async def test_workout_add_exercise_first_time(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-121: add_exercise cria exercício e responde 'Primeira vez'."""
    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    session, _ = await WorkoutService(db_session).start_session(
        user_id=admin_user.id, day_log_id=dl.id, workout_type="push"
    )
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="supino reto",
        intent="workout_add_exercise",
        workout_add_exercise={"exercise_name": "supino reto"},
    )

    exercises = list((await db_session.execute(select(WorkoutExercise))).scalars())
    assert len(exercises) == 1
    assert exercises[0].name == "supino reto"
    assert exercises[0].normalized_name == "supino_reto"

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_add_exercise"
    assert "Registrei o exercício" in assistant.content
    assert "Primeira vez registrando esse exercício." in assistant.content


async def test_workout_add_exercise_without_session_clarifies(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-121: sem sessão ativa, pede pra iniciar treino primeiro."""
    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="supino reto",
        intent="workout_add_exercise",
        workout_add_exercise={"exercise_name": "supino reto"},
    )

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "clarify"
    assert "Nenhum treino em andamento" in assistant.content


async def test_workout_log_set_registers_and_confirms(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-122: log_set cria série no último exercício (INV-16) e confirma."""
    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    session, _ = await svc.start_session(
        user_id=admin_user.id, day_log_id=dl.id, workout_type="full_body"
    )
    await svc.add_exercise(
        user_id=admin_user.id, session_id=session.id, exercise_name="agachamento livre"
    )
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="80 kg x 5",
        intent="workout_log_set",
        workout_log_set={"weight_kg": 80.0, "reps": 5},
    )

    sets = list((await db_session.execute(select(WorkoutSet))).scalars())
    assert len(sets) == 1
    assert sets[0].weight_kg == 80
    assert sets[0].reps == 5
    assert sets[0].sequence_index == 0

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_log_set"
    assert "Série **1**" in assistant.content
    assert "80 kg × 5" in assistant.content


async def test_workout_end_consolidates_activity_record(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-124+126: workout_end encerra sessão, consolida activity_record
    (calc_method='workout_session') e responde resumo."""
    from decimal import Decimal

    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    admin_user.weight_kg = Decimal("80")
    await db_session.flush()

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    session, _ = await svc.start_session(
        user_id=admin_user.id, day_log_id=dl.id, workout_type="push"
    )
    await svc.add_exercise(
        user_id=admin_user.id, session_id=session.id, exercise_name="supino reto"
    )
    await svc.log_set(user_id=admin_user.id, session_id=session.id, weight_kg=60, reps=10)
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="finalizar treino",
        intent="workout_end",
        workout_end={},
    )

    db_session.expire_all()
    sessions = list((await db_session.execute(select(WorkoutSession))).scalars())
    assert sessions[0].status == "ended"
    assert sessions[0].end_reason == "user"

    records = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert len(records) == 1
    assert records[0].calc_method == "workout_session"
    assert records[0].activity_type == "strength"
    assert records[0].workout_session_id == session.id
    assert records[0].kcal_burned is not None

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_end"
    assert "encerrado" in assistant.content
    assert "1 exercício(s) · 1 série(s)" in assistant.content


async def test_workout_end_without_session_clarifies(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-124: sem sessão ativa → clarify."""
    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="finalizar treino",
        intent="workout_end",
        workout_end={},
    )
    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "clarify"
    assert "Não há treino em andamento" in assistant.content


async def test_workout_history_returns_pr(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-127: workout_history consulta histórico sem criar registro."""
    from datetime import timedelta

    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    session, _ = await svc.start_session(
        user_id=admin_user.id, day_log_id=dl.id, workout_type="push"
    )
    await svc.add_exercise(
        user_id=admin_user.id, session_id=session.id, exercise_name="supino reto"
    )
    await svc.log_set(user_id=admin_user.id, session_id=session.id, weight_kg=60, reps=10)
    await svc.end_session(
        user_id=admin_user.id,
        session_id=session.id,
        ended_at=session.started_at + timedelta(minutes=45),
    )
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="qual peso fiz no supino?",
        intent="workout_history",
        workout_history={"exercise_name": "supino reto"},
    )

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_history"
    assert "Histórico de" in assistant.content
    assert "60 kg" in assistant.content
    assert "PR pessoal" in assistant.content
