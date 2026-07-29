"""Cobertura dos endpoints /test/* + TestAnthropicClient (T-E02)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_reset_truncates_business_tables_and_recreates_admin(client, admin_user):
    # Pré-condição: admin_user fixture já criou o admin. Verifica que /test/reset
    # apaga e recria — o id novo é != do antigo, provando TRUNCATE + insert.
    original_admin_id = str(admin_user.id)

    response = await client.post("/test/reset")
    assert response.status_code == 204

    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert login.status_code == 204

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["id"] != original_admin_id


async def test_queue_llm_status_reflects_enqueued_counts(client, make_envelope):
    envelope = make_envelope()
    payload = {"kind": "record_intent", "envelope": envelope.model_dump(mode="json")}
    r1 = await client.post("/test/queue-llm-response", json=payload)
    assert r1.status_code == 204

    r2 = await client.post(
        "/test/queue-llm-response",
        json={"kind": "narrative", "text": "Bom dia! Você registrou..."},
    )
    assert r2.status_code == 204

    status = (await client.get("/test/queue-llm-status")).json()
    assert status == {"record_intent": 1, "narrative": 1, "weekly_narrative": 0}

    # Reset drena todas as filas.
    await client.post("/test/reset")
    cleared = (await client.get("/test/queue-llm-status")).json()
    assert cleared == {"record_intent": 0, "narrative": 0, "weekly_narrative": 0}


async def test_queue_record_intent_without_envelope_returns_422(client):
    response = await client.post(
        "/test/queue-llm-response",
        json={"kind": "record_intent"},
    )
    assert response.status_code == 422


async def test_test_anthropic_client_consumes_queue(make_envelope):
    """TestAnthropicClient devolve envelope enfileirado sem tocar HTTP.

    Cobre o consumo direto — os handlers /test/* já testados acima cobrem o
    write side. Este teste garante que o read side (call_record_intent)
    também funciona sem sobrescrita de deps.
    """
    from app.integrations.anthropic.test_client import (
        TestAnthropicClient,
        clear_all_queues,
        queue_record_intent,
    )

    clear_all_queues()
    envelope = make_envelope(intent="log_food", confidence=0.9, needs_clarification=False)
    queue_record_intent(envelope)

    tc = TestAnthropicClient()
    result = await tc.call_record_intent(user_text="150g de arroz")
    assert result.envelope is not None
    assert result.envelope.intent == "log_food"
    assert result.error is None

    # Segunda call sem enfileirar cai como no_queued_result.
    result2 = await tc.call_record_intent(user_text="qualquer")
    assert result2.envelope is None
    assert result2.error == "no_queued_result"
