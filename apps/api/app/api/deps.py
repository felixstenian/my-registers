"""Dependências FastAPI reutilizáveis para autenticação e sessão."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from fastapi import Cookie, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import UnauthorizedError
from app.core.security import decode_access_token
from app.db.session import SessionLocal
from app.models import User
from app.repositories.user import UserRepository

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    return request.client.host if request.client else None


def get_user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent") or None


async def get_current_user(
    access_token: str | None = Cookie(default=None, alias=ACCESS_COOKIE),
    session: AsyncSession = Depends(get_session),
) -> User:
    if not access_token:
        raise UnauthorizedError("missing access token", code="unauthorized")
    payload = decode_access_token(access_token)
    if payload is None or "sub" not in payload:
        raise UnauthorizedError("invalid access token", code="unauthorized")
    try:
        user_id = uuid.UUID(payload["sub"])
    except (TypeError, ValueError):
        raise UnauthorizedError("invalid access token", code="unauthorized") from None
    users = UserRepository(session)
    user = await users.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("user not active", code="unauthorized")
    return user
