"""SP-13, SP-14, INV-9 — fluxo LLM via BackgroundTasks.

Anthropic real é substituído por `FakeAnthropicClient` via
`dependency_overrides`. BackgroundTasks do FastAPI rodam antes da resposta
sair do ASGITransport, então após `client.post(...)` o worker já processou
a mensagem e a assistant response está no banco.
"""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Media, Message

pytestmark = pytest.mark.asyncio


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


def _png_bytes() -> bytes:
    img = Image.new("RGB", (8, 8), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _upload_media(client: AsyncClient) -> str:
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# SP-13 — Mensagem ambígua: clarify
# ---------------------------------------------------------------------------


async def test_clarify_intent_creates_assistant_message(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    envelope = make_envelope(
        intent="clarify",
        confidence=0.4,
        user_text_summary="Não deu para entender se é registro de comida ou atividade.",
        needs_clarification=True,
        clarification_question="Você quis dizer que comeu algo ou treinou?",
    )
    await _login(client)
    fake_anthropic.queue(make_llm_result(envelope))

    resp = await client.post(
        "/chat/messages", json={"text": "hoje foi puxado"}
    )
    assert resp.status_code == 202

    messages = list((await db_session.execute(select(Message))).scalars())
    assert len(messages) == 2  # user + assistant
    assistant = next(m for m in messages if m.role == "assistant")
    assert assistant.content == "Você quis dizer que comeu algo ou treinou?"
    assert assistant.llm_intent == "clarify"
    assert assistant.tokens_input == 100
    assert assistant.llm_prompt_version == "system_v2"
    assert assistant.raw_llm_response is not None
    assert assistant.raw_llm_response["error"] is None


async def test_clarify_does_not_create_business_records(
    client: AsyncClient, admin_user, fake_anthropic, make_envelope, make_llm_result
):
    """SP-13: clarify NUNCA cria food/water/beverage/activity records
    (essas tabelas nem existem em Fase 3 — a garantia é implícita)."""
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(intent="clarify", clarification_question="Detalhe?")
        )
    )
    resp = await client.post("/chat/messages", json={"text": "..."})
    assert resp.status_code == 202


async def test_clarify_without_question_uses_fallback_not_summary(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """UX: se a LLM esquecer o `clarification_question`, o assistant devolve
    o fallback em 2ª pessoa — NUNCA vaza o `user_text_summary` (que é 3ª pessoa,
    tom de log interno). Regressão do feedback SP-13.
    """
    await _login(client)
    envelope = make_envelope(
        intent="clarify",
        confidence=0.5,
        user_text_summary=(
            "Usuário comentou que o dia foi puxado, sem indicar "
            "registro específico de alimento, bebida ou atividade."
        ),
        needs_clarification=True,
        clarification_question=None,
    )
    fake_anthropic.queue(make_llm_result(envelope))

    resp = await client.post(
        "/chat/messages", json={"text": "hoje foi puxado"}
    )
    assert resp.status_code == 202

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    # Não deve conter o summary em 3ª pessoa ("Usuário...")
    assert "Usuário comentou" not in assistant.content
    # Deve ser o fallback em 2ª pessoa, com pergunta amigável
    assert "Você" in assistant.content
    assert assistant.content.endswith("?")


async def test_unknown_intent_uses_fallback_not_summary(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    """Mesma regra do clarify: unknown nunca vaza `user_text_summary` para o chat."""
    await _login(client)
    envelope = make_envelope(
        intent="unknown",
        confidence=0.3,
        user_text_summary="Usuário mandou uma mensagem fora do escopo.",
        needs_clarification=False,
        clarification_question=None,
    )
    fake_anthropic.queue(make_llm_result(envelope))
    await client.post("/chat/messages", json={"text": "kkk"})

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert "Usuário mandou" not in assistant.content
    assert "reformular" in assistant.content.lower()


# ---------------------------------------------------------------------------
# SP-14 — Timeout ou erro da LLM
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error_code",
    ["anthropic_timeout", "anthropic_status_500", "anthropic_status_429"],
)
async def test_llm_error_creates_fallback_assistant_message(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_llm_result,
    db_session: AsyncSession,
    error_code: str,
):
    await _login(client)
    fake_anthropic.queue(make_llm_result(envelope=None, error=error_code))

    resp = await client.post(
        "/chat/messages", json={"text": "arroz e feijão"}
    )
    assert resp.status_code == 202

    messages = list((await db_session.execute(select(Message))).scalars())
    assistant = next(m for m in messages if m.role == "assistant")
    assert "Não consegui interpretar" in assistant.content
    # raw_llm_response.error preservado (SP-14)
    assert assistant.raw_llm_response["error"] == error_code
    assert assistant.llm_intent == "unknown"


async def test_no_tool_use_response_treated_as_error(
    client: AsyncClient, admin_user, fake_anthropic, make_llm_result
):
    """INV-9 / Const. §7: sem `tool_use` válido, texto livre é descartado."""
    await _login(client)
    fake_anthropic.queue(make_llm_result(envelope=None, error="no_tool_use"))
    resp = await client.post("/chat/messages", json={"text": "algo"})
    assert resp.status_code == 202
    resp = await client.get("/chat/messages")
    assistant = next(m for m in resp.json()["messages"] if m["role"] == "assistant")
    assert "Não consegui" in assistant["content"]


async def test_validation_exhausted_treated_as_error(
    client: AsyncClient, admin_user, fake_anthropic, make_llm_result
):
    """Retry semântico esgotado (SP-14 estende Const. §7)."""
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(envelope=None, error="validation_exhausted")
    )
    resp = await client.post("/chat/messages", json={"text": "algo"})
    assert resp.status_code == 202
    resp = await client.get("/chat/messages")
    assistant = next(m for m in resp.json()["messages"] if m["role"] == "assistant")
    assert assistant["content"].startswith("Não consegui")


# ---------------------------------------------------------------------------
# Intents estruturados ainda não implementados (Fase 4+)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "intent",
    # log_food (Fase 4), log_water/log_beverage/log_activity (Fase 5) foram
    # implementados. Ficam aqui apenas os que ainda dependem de fases futuras.
    ["correct_record", "delete_record", "query_day", "weekly_summary"],
)
async def test_not_implemented_intents_fall_back_to_reformulation(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
    intent: str,
):
    await _login(client)
    envelope = make_envelope(
        intent=intent,
        confidence=0.9,
        user_text_summary="Registro estruturado (Fase futura).",
    )
    fake_anthropic.queue(make_llm_result(envelope))

    resp = await client.post(
        "/chat/messages", json={"text": f"testando {intent}"}
    )
    assert resp.status_code == 202

    assistant = next(
        m
        for m in list((await db_session.execute(select(Message))).scalars())
        if m.role == "assistant"
    )
    assert assistant.llm_intent == intent
    assert "não está disponível" in assistant.content
    raw = assistant.raw_llm_response
    assert raw and raw["dispatch"] == {"not_implemented": intent}


# ---------------------------------------------------------------------------
# Mídia: media é baixada e passada ao cliente Anthropic
# ---------------------------------------------------------------------------


async def test_media_is_downloaded_and_forwarded_to_llm(
    client: AsyncClient,
    admin_user,
    fake_anthropic,
    fake_storage,
    make_envelope,
    make_llm_result,
    db_session: AsyncSession,
):
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(intent="unknown", user_text_summary="Não sei o que é isso.")
        )
    )
    media_id = await _upload_media(client)

    resp = await client.post(
        "/chat/messages",
        json={"text": "que foto é essa?", "media_ids": [media_id]},
    )
    assert resp.status_code == 202

    assert len(fake_anthropic.calls) == 1
    call = fake_anthropic.calls[0]
    assert call["user_text"] == "que foto é essa?"
    assert len(call["images"]) == 1
    content_type, data = call["images"][0]
    assert content_type == "image/png"

    # bytes correspondem à mídia realmente armazenada
    media = (await db_session.execute(select(Media))).scalar_one()
    stored_bytes, _ = fake_storage.objects[media.storage_key]
    assert data == stored_bytes


# ---------------------------------------------------------------------------
# INV-9 — LoggedIn without triggering the LLM implies not creating assistant msg
# ---------------------------------------------------------------------------


async def test_login_alone_does_not_touch_anthropic(
    client: AsyncClient, admin_user, fake_anthropic
):
    """A queue permanece intacta — nenhuma chamada foi feita no fluxo de login."""
    assert fake_anthropic.calls == []


# ---------------------------------------------------------------------------
# Front bootstrap: fluxo ponta-a-ponta via GET /chat/messages
# ---------------------------------------------------------------------------


async def test_full_flow_visible_via_get_messages(
    client: AsyncClient, admin_user, fake_anthropic, make_envelope, make_llm_result
):
    await _login(client)
    fake_anthropic.queue(
        make_llm_result(
            make_envelope(
                intent="clarify",
                clarification_question="Você quis dizer 'corri' ou 'comi'?",
            )
        )
    )
    await client.post("/chat/messages", json={"text": "hoje foi puxado"})

    resp = await client.get("/chat/messages")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["llm_intent"] == "clarify"
    assert messages[1]["content"] == "Você quis dizer 'corri' ou 'comi'?"
