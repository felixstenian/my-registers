"""SP-10, SP-12, SP-92 — chat: envio, listagem, timezone do dia."""

from __future__ import annotations

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DayLog, Message, MessageMedia

pytestmark = pytest.mark.asyncio


def _png_bytes() -> bytes:
    img = Image.new("RGB", (8, 8), color=(0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def _upload_media(client: AsyncClient) -> str:
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# SP-10 — POST /chat/messages só texto → 202
# ---------------------------------------------------------------------------


async def test_post_text_only_returns_202(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post(
        "/chat/messages",
        json={"text": "Café da manhã: pão com café."},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "processing"
    assert body["message_id"]


async def test_post_requires_auth(client: AsyncClient):
    resp = await client.post("/chat/messages", json={"text": "olá"})
    assert resp.status_code == 401


async def test_post_rejects_empty_message(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post("/chat/messages", json={"text": "  "})
    assert resp.status_code == 422
    assert resp.json()["code"] == "empty_message"


# ---------------------------------------------------------------------------
# SP-11 — POST /chat/messages com media_ids liga corretamente
# ---------------------------------------------------------------------------


async def test_post_with_media_links_them(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _login(client)
    m1 = await _upload_media(client)
    m2 = await _upload_media(client)

    resp = await client.post(
        "/chat/messages",
        json={"text": "meu almoço", "media_ids": [m1, m2]},
    )
    assert resp.status_code == 202
    assert resp.json()["message_id"]

    rows = list((await db_session.execute(select(MessageMedia))).scalars())
    assert len(rows) == 2


async def test_post_rejects_more_than_four_media(client: AsyncClient, admin_user):
    await _login(client)
    media_ids = [await _upload_media(client) for _ in range(5)]
    resp = await client.post(
        "/chat/messages",
        json={"text": "spam", "media_ids": media_ids},
    )
    # Limite validado pelo Pydantic (max_length=4) → 422
    assert resp.status_code == 422


async def test_post_rejects_media_from_other_user(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """Const. §21: isolamento por user_id — media de outro user não pode ser
    referenciada."""

    from app.core.security import hash_password
    from app.repositories.media import MediaRepository
    from app.repositories.user import UserRepository

    other = await UserRepository(db_session).create(
        email="other@example.com", password_hash=hash_password("otherother")
    )
    other_media = await MediaRepository(db_session).create(
        user_id=other.id,
        storage_key="users/other/media/2026/07/xyz.png",
        content_type="image/png",
        size_bytes=100,
        width=8,
        height=8,
        checksum_sha256="a" * 64,
    )
    await db_session.commit()

    await _login(client)
    resp = await client.post(
        "/chat/messages",
        json={"text": "roubando media", "media_ids": [str(other_media.id)]},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "unknown_media"


# ---------------------------------------------------------------------------
# SP-12 — histórico e paginação
# ---------------------------------------------------------------------------


async def test_list_returns_chronological(client: AsyncClient, admin_user):
    await _login(client)
    for i in range(3):
        r = await client.post("/chat/messages", json={"text": f"msg {i}"})
        assert r.status_code == 202

    resp = await client.get("/chat/messages")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) == 3
    assert [m["content"] for m in messages] == ["msg 0", "msg 1", "msg 2"]
    assert all(m["role"] == "user" for m in messages)


async def test_list_after_returns_newer(client: AsyncClient, admin_user):
    await _login(client)
    ids = []
    for i in range(4):
        r = await client.post("/chat/messages", json={"text": f"msg {i}"})
        ids.append(r.json()["message_id"])

    resp = await client.get(f"/chat/messages?after={ids[1]}")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert [m["content"] for m in messages] == ["msg 2", "msg 3"]


async def test_list_before_returns_older(client: AsyncClient, admin_user):
    await _login(client)
    ids = []
    for i in range(4):
        r = await client.post("/chat/messages", json={"text": f"msg {i}"})
        ids.append(r.json()["message_id"])

    resp = await client.get(f"/chat/messages?before={ids[3]}&limit=2")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    # 2 mais recentes antes de ids[3] → msg 1, msg 2 (em ordem cronológica)
    assert [m["content"] for m in messages] == ["msg 1", "msg 2"]


async def test_list_media_urls_returned(client: AsyncClient, admin_user):
    await _login(client)
    mid = await _upload_media(client)
    r = await client.post("/chat/messages", json={"text": "foto", "media_ids": [mid]})
    assert r.status_code == 202

    resp = await client.get("/chat/messages")
    assert resp.status_code == 200
    messages = resp.json()["messages"]
    assert len(messages) == 1
    assert len(messages[0]["media"]) == 1
    media_ref = messages[0]["media"][0]
    assert media_ref["id"] == mid
    assert media_ref["content_type"] == "image/png"
    assert media_ref["url"].startswith("https://fake-minio.test/")


# ---------------------------------------------------------------------------
# SP-92 — day_log usa timezone do usuário
# ---------------------------------------------------------------------------


async def test_post_creates_day_log_for_user_timezone(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _login(client)
    r = await client.post("/chat/messages", json={"text": "olá"})
    assert r.status_code == 202

    day_logs = list((await db_session.execute(select(DayLog))).scalars())
    assert len(day_logs) == 1
    dl = day_logs[0]
    assert dl.user_id == admin_user.id
    # deve bater com a data local em America/Sao_Paulo (default do fixture)
    expected = datetime.now(ZoneInfo(admin_user.timezone)).date()
    assert dl.log_date == expected
    assert dl.status == "open"

    # Message aponta para o day_log criado
    messages = list((await db_session.execute(select(Message))).scalars())
    assert len(messages) == 1
    assert messages[0].day_log_id == dl.id


async def test_post_reuses_existing_day_log(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    await _login(client)
    r1 = await client.post("/chat/messages", json={"text": "1"})
    r2 = await client.post("/chat/messages", json={"text": "2"})
    assert r1.status_code == 202 and r2.status_code == 202

    day_logs = list((await db_session.execute(select(DayLog))).scalars())
    assert len(day_logs) == 1
