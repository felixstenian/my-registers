"""SP-11 — upload de mídia com validação server-side (Const. §22)."""

from __future__ import annotations

import io

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Media

pytestmark = pytest.mark.asyncio


def _png_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    img = Image.new("RGB", size, color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size: tuple[int, int] = (10, 10)) -> bytes:
    img = Image.new("RGB", size, color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


async def _login(client: AsyncClient) -> None:
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def test_upload_png_happy_path(
    client: AsyncClient, admin_user, fake_storage, db_session: AsyncSession
):
    await _login(client)
    data = _png_bytes((32, 24))
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", data, "image/png")},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(data)
    assert body["width"] == 32 and body["height"] == 24

    rows = list((await db_session.execute(select(Media))).scalars())
    assert len(rows) == 1
    media = rows[0]
    assert media.user_id == admin_user.id
    assert media.storage_key.startswith(f"users/{admin_user.id}/media/")
    assert media.storage_key.endswith(".png")
    assert media.checksum_sha256 and len(media.checksum_sha256) == 64
    assert media.storage_key in fake_storage.objects
    stored_body, stored_ct = fake_storage.objects[media.storage_key]
    assert stored_body == data
    assert stored_ct == "image/png"


async def test_upload_jpeg_happy_path(client: AsyncClient, admin_user):
    await _login(client)
    data = _jpeg_bytes()
    resp = await client.post(
        "/media",
        files={"file": ("pic.jpg", data, "image/jpeg")},
    )
    assert resp.status_code == 201


async def test_upload_rejects_unsupported_mime(client: AsyncClient, admin_user):
    await _login(client)
    resp = await client.post(
        "/media",
        files={"file": ("doc.pdf", b"%PDF-1.4 not really", "application/pdf")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "unsupported_media_type"


async def test_upload_rejects_fake_image(client: AsyncClient, admin_user):
    """Content-Type diz image/png mas o corpo não é imagem — decode probe rejeita."""
    await _login(client)
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", b"not really a png", "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_image"


async def test_upload_rejects_too_large(client: AsyncClient, admin_user):
    await _login(client)
    # imagem enorme que descompactada > 8MB: usamos 8.1MB de bytes reais
    big = b"\x00" * (8 * 1024 * 1024 + 1024)
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", big, "image/png")},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "file_too_large"


async def test_upload_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/media",
        files={"file": ("pic.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 401
