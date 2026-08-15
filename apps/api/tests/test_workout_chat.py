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
from decimal import Decimal

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


async def test_close_day_ends_active_session_before_recompute(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """SP-125: fechar o dia encerra a sessão de treino ativa (end_reason
    auto_close_day) ANTES do recompute — o activity_record consolidado entra
    no snapshot fechado."""
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
        text="encerrar o dia",
        intent="close_day",
    )

    db_session.expire_all()
    await db_session.refresh(session)

    assert session.status == "ended"
    assert session.end_reason == "auto_close_day"

    records = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert len(records) == 1
    assert records[0].calc_method == "workout_session"
    assert records[0].workout_session_id == session.id


async def test_workout_log_set_guided_recaps_last_workout_and_shows_button(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B319 (SP-178): sessão guiada (template_id) — a partir da 1ª série,
    a confirmação recapitula a última sessão do exercício e emite o
    marcador do botão "Ir para o próximo exercício"."""
    from app.repositories.day_log import DayLogRepository
    from app.schemas.llm import WorkoutTemplateIn
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    template = await svc.register_template(
        user_id=admin_user.id,
        template=WorkoutTemplateIn(
            name="Push guiado",
            workout_type="push",
            exercises=[{"exercise_name": "supino reto", "target_sets": 3, "target_reps": 10}],
        ),
    )

    # Sessão anterior encerrada com histórico do mesmo exercício.
    old_session, _ = await svc.start_session(
        user_id=admin_user.id, day_log_id=dl.id, workout_type="push"
    )
    await svc.add_exercise(
        user_id=admin_user.id, session_id=old_session.id, exercise_name="supino reto"
    )
    await svc.log_set(user_id=admin_user.id, session_id=old_session.id, weight_kg=55, reps=8)
    await svc.end_session(user_id=admin_user.id, session_id=old_session.id)

    session, _ = await svc.start_session(
        user_id=admin_user.id,
        day_log_id=dl.id,
        workout_type="push",
        template_id=template.id,
    )
    await svc.add_exercise(
        user_id=admin_user.id, session_id=session.id, exercise_name="supino reto"
    )
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="60 kg x 8",
        intent="workout_log_set",
        workout_log_set={"weight_kg": 60.0, "reps": 8},
    )

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_log_set"
    assert "Série **1**" in assistant.content
    assert "Da última vez você fez 55 kg × 8." in assistant.content
    assert "Ir para o próximo exercício" in assistant.content
    assert "<!-- workout-next-exercise -->" in assistant.content


async def test_workout_log_set_free_session_has_no_guided_button(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B319: sessão livre (sem template_id) não emite o marcador guiado."""
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
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="60 kg x 8",
        intent="workout_log_set",
        workout_log_set={"weight_kg": 60.0, "reps": 8},
    )

    assistant = await _get_assistant(db_session)
    assert "workout-next-exercise" not in assistant.content


async def test_workout_next_exercise_relists_template_plan(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B319 (SP-178): botão "Ir para o próximo exercício" → intent
    `workout_next_exercise` re-lista o plano do template (determinístico)."""
    from app.repositories.day_log import DayLogRepository
    from app.schemas.llm import WorkoutTemplateIn
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    template = await svc.register_template(
        user_id=admin_user.id,
        template=WorkoutTemplateIn(
            name="Push guiado",
            workout_type="push",
            exercises=[
                {"exercise_name": "Supino reto", "target_sets": 3, "target_reps": 10},
                {"exercise_name": "Desenvolvimento", "target_sets": 3, "target_reps": 12},
            ],
        ),
    )
    session, _ = await svc.start_session(
        user_id=admin_user.id,
        day_log_id=dl.id,
        workout_type="push",
        template_id=template.id,
    )
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="ir para o próximo exercício",
        intent="workout_next_exercise",
        workout_next_exercise={},
    )

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_next_exercise"
    assert "Supino reto" in assistant.content
    assert "Desenvolvimento" in assistant.content


async def test_workout_next_exercise_without_session_clarifies(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B319: sem sessão ativa, o botão pede pra iniciar o treino."""
    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="ir para o próximo exercício",
        intent="workout_next_exercise",
        workout_next_exercise={},
    )
    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "clarify"
    assert "Nenhum treino em andamento" in assistant.content


async def test_workout_next_exercise_free_session_clarifies(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B319 (INV-20): sessão livre (sem template) não tem sequência guiada
    — `workout_next_exercise` responde com `clarify`."""
    from app.repositories.day_log import DayLogRepository
    from app.services.workout import WorkoutService

    dl = await DayLogRepository(db_session).get_or_create(
        user_id=admin_user.id, log_date=datetime.now(UTC).date()
    )
    svc = WorkoutService(db_session)
    await svc.start_session(user_id=admin_user.id, day_log_id=dl.id, workout_type="legs")
    await db_session.commit()

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="ir para o próximo exercício",
        intent="workout_next_exercise",
        workout_next_exercise={},
    )
    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "clarify"


async def test_workout_register_template_routes_and_creates(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B313 (SP-171): intent workout_register_template via chat → template
    + exercícios criados com active=true; assistant confirma com o plano."""
    from app.models import WorkoutTemplate, WorkoutTemplateExercise

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="cadastrar treino de push",
        intent="workout_register_template",
        workout_template={
            "name": "Peito e tríceps",
            "workout_type": "push",
            "muscle_groups": ["peito", "ombro", "triceps"],
            "exercises": [
                {"exercise_name": "Supino reto", "target_sets": 3, "target_reps": 10},
                {"exercise_name": "Desenvolvimento", "target_sets": 3, "target_reps": 12},
            ],
        },
    )

    templates = list((await db_session.execute(select(WorkoutTemplate))).scalars())
    assert len(templates) == 1
    template = templates[0]
    assert template.name == "Peito e tríceps"
    assert template.active is True

    exercises = list((await db_session.execute(select(WorkoutTemplateExercise))).scalars())
    assert {e.exercise_name for e in exercises} == {"Supino reto", "Desenvolvimento"}

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "workout_register_template"
    assert "Cadastrei o treino" in assistant.content
    assert "3 × 10" in assistant.content


async def test_workout_register_template_clarifies_when_incomplete(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """T-B313 (SP-171): template sem plano de séries/reps → assistant emite
    clarify pedindo as séries e repetições; nenhum template é criado."""
    from app.models import WorkoutTemplate

    await _login(client)
    await _send(
        client,
        fake_anthropic,
        make_envelope,
        make_llm_result,
        text="cadastrar treino",
        intent="workout_register_template",
        workout_template={
            "name": "Sem plano",
            "workout_type": "pull",
            "exercises": [{"exercise_name": "Remada curvada"}],
        },
    )

    templates = list((await db_session.execute(select(WorkoutTemplate))).scalars())
    assert templates == []

    assistant = await _get_assistant(db_session)
    assert assistant.llm_intent == "clarify"
    assert "plano de cada exercício" in assistant.content
