"""Testes de integração para SP-01..SP-06 (Fase 1).

Cobrem os requisitos da spec.md §3.1 e as invariantes INV-6, INV-7.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# SP-01 — Login com email e senha
# ---------------------------------------------------------------------------


async def test_login_success_sets_cookies_and_204(client: AsyncClient, admin_user):
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204
    cookies = resp.cookies
    assert "access_token" in cookies
    assert "refresh_token" in cookies
    # HttpOnly / Path=/ via Set-Cookie
    set_cookies = "\n".join(resp.headers.get_list("set-cookie"))
    assert "HttpOnly" in set_cookies
    assert "access_token=" in set_cookies
    assert "refresh_token=" in set_cookies


async def test_login_case_insensitive_email(client: AsyncClient, admin_user):
    resp = await client.post(
        "/auth/login",
        json={"email": "ADMIN@Example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204


async def test_login_invalid_password_returns_401_generic(
    client: AsyncClient, admin_user
):
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


async def test_login_unknown_email_returns_401_generic(client: AsyncClient):
    """SP-01/SP-02: indistinguível entre email inexistente e senha errada."""
    resp = await client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "invalid_credentials"


# ---------------------------------------------------------------------------
# SP-02 — Brute force / rate limiting
# ---------------------------------------------------------------------------


async def test_login_rate_limited_by_ip(client: AsyncClient, admin_user):
    """5 tentativas/min/IP; a 6ª deve retornar 429 independente do email."""
    for i in range(5):
        resp = await client.post(
            "/auth/login",
            json={"email": f"user{i}@example.com", "password": "x"},
        )
        assert resp.status_code == 401
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"


async def test_login_rate_limited_by_email_failures(client: AsyncClient, admin_user):
    """10 falhas no mesmo email em 15 min → 429 mesmo com senha correta.

    Contornamos o IP limit gerando IPs distintos via X-Forwarded-For.
    """
    for i in range(10):
        resp = await client.post(
            "/auth/login",
            headers={"X-Forwarded-For": f"10.0.0.{i}"},
            json={"email": "admin@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401
    resp = await client.post(
        "/auth/login",
        headers={"X-Forwarded-For": "10.0.0.99"},
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 429
    assert resp.json()["code"] == "rate_limited"


# ---------------------------------------------------------------------------
# SP-03 — Rotação e detecção de reuso
# ---------------------------------------------------------------------------


async def test_refresh_rotates_and_revokes_old(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert login.status_code == 204
    old_refresh = login.cookies["refresh_token"]

    resp = await client.post("/auth/refresh")
    assert resp.status_code == 204
    new_refresh = resp.cookies["refresh_token"]
    assert new_refresh != old_refresh

    # Antigo agora está revoked_at != NULL no banco
    stmt = select(RefreshToken).order_by(RefreshToken.issued_at)
    rows = list((await db_session.execute(stmt)).scalars())
    assert len(rows) == 2
    assert rows[0].revoked_at is not None
    assert rows[0].replaced_by == rows[1].id
    assert rows[1].revoked_at is None


async def test_refresh_reuse_of_revoked_token_invalidates_family(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    """INV-6 / SP-03: reuso de refresh revogado → invalida família inteira."""
    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    old_refresh = login.cookies["refresh_token"]

    # Rotação 1 (bem-sucedida)
    r1 = await client.post("/auth/refresh")
    assert r1.status_code == 204

    # Reuso do refresh antigo — deve ser rejeitado
    client.cookies.set("refresh_token", old_refresh)
    r2 = await client.post("/auth/refresh")
    assert r2.status_code == 401
    assert r2.json()["code"] == "invalid_refresh"

    # E o novo refresh (r1) também foi revogado pela invalidação da família
    stmt = select(RefreshToken)
    rows = list((await db_session.execute(stmt)).scalars())
    assert all(row.revoked_at is not None for row in rows)


# ---------------------------------------------------------------------------
# SP-04 — Logout
# ---------------------------------------------------------------------------


async def test_logout_clears_cookies_and_revokes_refresh(
    client: AsyncClient, admin_user, db_session: AsyncSession
):
    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert login.status_code == 204

    logout = await client.post("/auth/logout")
    assert logout.status_code == 204
    set_cookies = "\n".join(logout.headers.get_list("set-cookie"))
    assert "access_token=" in set_cookies
    assert "refresh_token=" in set_cookies
    assert "Max-Age=0" in set_cookies

    stmt = select(RefreshToken)
    rows = list((await db_session.execute(stmt)).scalars())
    assert len(rows) == 1
    assert rows[0].revoked_at is not None


# ---------------------------------------------------------------------------
# SP-05 — Endpoints proibidos não existem (T-106)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/auth/register", "/auth/forgot-password", "/auth/reset-password"],
)
async def test_forbidden_public_endpoints_return_404(client: AsyncClient, path: str):
    """Const. Art. V §18: criação e reset são exclusivamente CLI."""
    resp = await client.post(path, json={"email": "x@example.com", "password": "x"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SP-06 — Proteção de rotas
# ---------------------------------------------------------------------------


async def test_me_without_cookie_returns_401(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"


async def test_me_with_valid_cookie_returns_user(client: AsyncClient, admin_user):
    login = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert login.status_code == 204

    resp = await client.get("/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "admin@example.com"
    assert body["display_name"] == "Admin"
    assert body["is_active"] is True


async def test_me_with_tampered_cookie_returns_401(client: AsyncClient):
    client.cookies.set("access_token", "not-a-jwt")
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# INV-7 — Senha nunca vaza em resposta ou logs
# ---------------------------------------------------------------------------


async def test_password_never_in_response(client: AsyncClient, admin_user):
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    body_text = resp.text
    assert "adminadmin" not in body_text
    assert "password" not in body_text.lower()


async def test_me_never_returns_password_hash(client: AsyncClient, admin_user):
    await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    resp = await client.get("/auth/me")
    assert "password_hash" not in resp.text
    assert "password" not in resp.text.lower() or "password" not in resp.json()
