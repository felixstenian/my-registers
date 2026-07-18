"""set_profile — atualiza perfil corporal via chat (fecha SP-61 end-to-end)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityRecord, AuditEvent, Message, User
from app.schemas.llm import LLMEnvelope
from app.services.profile import ProfileService

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


def _envelope(**overrides) -> LLMEnvelope:
    base: dict = {
        "intent": "set_profile",
        "confidence": 0.95,
        "user_text_summary": "Usuário informou dado de perfil.",
        "needs_clarification": False,
    }
    base.update(overrides)
    return LLMEnvelope.model_validate(base)


# ---------------------------------------------------------------------------
# ProfileService (unit-ish com DB)
# ---------------------------------------------------------------------------


async def test_updates_weight_kg_and_logs_audit(
    db_session: AsyncSession, admin_user: User
):
    envelope = _envelope(profile_update={"weight_kg": 65})
    result = await ProfileService(db_session).update_from_llm(
        user=admin_user, envelope=envelope, message_id=None
    )
    await db_session.commit()

    assert admin_user.weight_kg == Decimal("65")
    assert "weight_kg" in result.changed_fields
    before, after = result.changed_fields["weight_kg"]
    assert before is None
    assert after == 65.0

    events = list((await db_session.execute(select(AuditEvent))).scalars())
    profile_events = [e for e in events if e.entity_type == "user"]
    assert len(profile_events) == 1
    assert profile_events[0].action == "update"
    assert profile_events[0].actor == "llm"
    assert profile_events[0].after == {"weight_kg": 65.0}


async def test_updates_multiple_fields_at_once(
    db_session: AsyncSession, admin_user: User
):
    from datetime import date

    envelope = _envelope(
        profile_update={
            "weight_kg": 70,
            "height_cm": 175,
            "birthdate": "1990-05-15",
            "sex": "m",
        }
    )
    result = await ProfileService(db_session).update_from_llm(
        user=admin_user, envelope=envelope, message_id=None
    )
    await db_session.commit()

    assert admin_user.weight_kg == Decimal("70")
    assert admin_user.height_cm == Decimal("175")
    assert admin_user.birthdate == date(1990, 5, 15)
    assert admin_user.sex == "m"
    assert set(result.changed_fields.keys()) == {
        "weight_kg",
        "height_cm",
        "birthdate",
        "sex",
    }


async def test_raises_when_no_new_values(
    db_session: AsyncSession, admin_user: User
):
    """profile_update com valor igual ao atual → nada muda, service rejeita."""
    from app.core.exceptions import ValidationAppError

    admin_user.weight_kg = Decimal("65")
    await db_session.flush()

    envelope = _envelope(profile_update={"weight_kg": 65})
    with pytest.raises(ValidationAppError) as exc:
        await ProfileService(db_session).update_from_llm(
            user=admin_user, envelope=envelope, message_id=None
        )
    assert exc.value.code == "profile_no_change"


async def test_pydantic_rejects_absurd_weight(
    db_session: AsyncSession, admin_user: User
):
    """Weight fora de [0, 500] falha na validação do Pydantic."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMEnvelope.model_validate(
            {
                "intent": "set_profile",
                "confidence": 0.9,
                "user_text_summary": ".",
                "needs_clarification": False,
                "profile_update": {"weight_kg": 999},
            }
        )


# ---------------------------------------------------------------------------
# End-to-end: chat pega "peso 65 kg" e atualiza perfil
# ---------------------------------------------------------------------------


async def test_end_to_end_set_weight_via_chat(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="set_profile",
                confidence=0.95,
                user_text_summary="Usuário informou peso de 65 kg.",
                needs_clarification=False,
                profile_update={"weight_kg": 65},
            )
        )
    )
    resp = await client.post("/chat/messages", json={"text": "peso 65 kg"})
    assert resp.status_code == 202

    # Refresh admin from DB
    updated = (
        await db_session.execute(select(User).where(User.id == admin_user.id))
    ).scalar_one()
    await db_session.refresh(updated)
    assert updated.weight_kg == Decimal("65")

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert assistant.llm_intent == "set_profile"
    assert "65" in assistant.content
    assert "peso" in assistant.content.lower()


# ---------------------------------------------------------------------------
# SP-61 fluxo completo: activity → weight → activity retry
# ---------------------------------------------------------------------------


async def test_sp61_full_flow_activity_then_weight_then_activity(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Cenário do usuário: 'corri 40 min' → clarify pedindo peso → 'peso 65 kg'
    → perfil atualiza → 'corri 40 min' de novo → registra corretamente."""
    await _login(client)

    # 1) log_activity sem peso
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_activity",
                confidence=0.9,
                user_text_summary="Corrida.",
                needs_clarification=False,
                activity={
                    "detected_name": "corrida",
                    "activity_type": "cardio_run",
                    "duration_minutes": 40,
                    "distance_km": None,
                    "intensity": "moderate",
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "corri 40 min moderado"})

    activity_rows = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert activity_rows == []
    assistants = [
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    ]
    assert len(assistants) == 1
    assert "peso" in assistants[0].content.lower()

    # 2) set_profile weight_kg=65
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="set_profile",
                confidence=0.95,
                user_text_summary="Usuário informou peso.",
                needs_clarification=False,
                profile_update={"weight_kg": 65},
            )
        )
    )
    await client.post("/chat/messages", json={"text": "peso 65 kg"})

    updated = (
        await db_session.execute(select(User).where(User.id == admin_user.id))
    ).scalar_one()
    await db_session.refresh(updated)
    assert updated.weight_kg == Decimal("65")

    # 3) log_activity de novo
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="log_activity",
                confidence=0.9,
                user_text_summary="Corrida.",
                needs_clarification=False,
                activity={
                    "detected_name": "corrida",
                    "activity_type": "cardio_run",
                    "duration_minutes": 40,
                    "distance_km": None,
                    "intensity": "moderate",
                    "confidence": 0.9,
                },
            )
        )
    )
    await client.post("/chat/messages", json={"text": "corri 40 min moderado"})

    activity_rows = list((await db_session.execute(select(ActivityRecord))).scalars())
    assert len(activity_rows) == 1
    # 8.3 × 65 × 40/60 = 359.67
    assert activity_rows[0].kcal_burned == Decimal("359.67")
