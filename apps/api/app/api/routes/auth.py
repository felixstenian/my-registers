"""Endpoints de autenticação — /auth/login, /refresh, /logout, /me.

Cobre SP-01, SP-02, SP-03, SP-04, SP-06. Const. Art. V §15-21.
Não existem /auth/register nem /auth/forgot-password (Const. §18, SP-05).
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    get_client_ip,
    get_current_user,
    get_session,
    get_user_agent,
)
from app.core.config import get_settings
from app.core.exceptions import RateLimitedError, UnauthorizedError
from app.core.rate_limit import get_email_fail_limiter, get_ip_limiter
from app.models import User
from app.schemas.auth import LoginRequest, UserMe
from app.services.auth import AuthService, IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, issued: IssuedSession) -> None:
    settings = get_settings()
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=issued.access_token,
        max_age=settings.jwt_access_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=issued.refresh_token,
        max_age=settings.refresh_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    settings = get_settings()
    for name in (ACCESS_COOKIE, REFRESH_COOKIE):
        response.set_cookie(
            key=name,
            value="",
            max_age=0,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            path="/",
        )


@router.post("/login", status_code=status.HTTP_204_NO_CONTENT)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> Response:
    ip = get_client_ip(request) or "unknown"
    email_key = payload.email.lower()

    ip_limiter = get_ip_limiter()
    email_limiter = get_email_fail_limiter()

    if ip_limiter.is_blocked(ip):
        raise RateLimitedError("too many attempts from ip", code="rate_limited")
    if email_limiter.is_blocked(email_key):
        raise RateLimitedError("too many failed attempts for email", code="rate_limited")

    ip_limiter.record(ip)

    service = AuthService(session)
    try:
        issued = await service.login(
            email=email_key,
            password=payload.password,
            user_agent=get_user_agent(request),
            ip=ip,
        )
    except UnauthorizedError:
        email_limiter.record(email_key)
        raise

    _set_session_cookies(response, issued)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> Response:
    if not refresh_token:
        raise UnauthorizedError("missing refresh token", code="invalid_refresh")
    service = AuthService(session)
    issued = await service.refresh(
        refresh_plain=refresh_token,
        user_agent=get_user_agent(request),
        ip=get_client_ip(request),
    )
    _set_session_cookies(response, issued)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: AsyncSession = Depends(get_session),
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
) -> Response:
    service = AuthService(session)
    await service.logout(refresh_plain=refresh_token)
    _clear_session_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserMe)
async def me(current_user: User = Depends(get_current_user)) -> UserMe:
    return UserMe.model_validate(current_user)
