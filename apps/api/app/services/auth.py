"""AuthService — orquestra login, refresh e logout.

Regras críticas:
- Rotação obrigatória do refresh a cada uso (Const. Art. V §17).
- Reuso de refresh já revogado → invalida TODA a família (todos os tokens
  ativos daquele usuário).
- Access token é stateless (JWT HS256 curto); refresh é opaco e persistido
  hasheado (SHA-256).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    encode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    needs_rehash,
    verify_password,
)
from app.models import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository


@dataclass(slots=True)
class IssuedSession:
    user: User
    access_token: str
    access_expires_at: datetime
    refresh_token: str  # plaintext — só volta uma vez (para setar cookie)
    refresh_expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    async def login(
        self,
        *,
        email: str,
        password: str,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        user = await self.users.get_by_email(email)
        if user is None or not user.is_active:
            raise UnauthorizedError("invalid credentials", code="invalid_credentials")
        if not verify_password(password, user.password_hash):
            raise UnauthorizedError("invalid credentials", code="invalid_credentials")
        if needs_rehash(user.password_hash):
            await self.users.update_password_hash(user, hash_password(password))
        return await self._issue_pair(user=user, user_agent=user_agent, ip=ip)

    async def refresh(
        self,
        *,
        refresh_plain: str,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        token_hash = hash_refresh_token(refresh_plain)
        token = await self.refresh_tokens.get_by_hash(token_hash)
        if token is None:
            raise UnauthorizedError("invalid refresh", code="invalid_refresh")
        now = datetime.now(UTC)
        if token.revoked_at is not None:
            # SP-03 / Const. §17: reuso de refresh revogado → invalida família.
            # Commitamos antes de raise para não perder a revogação no rollback
            # feito pelo `get_session` dep.
            await self.refresh_tokens.revoke_family(token.user_id)
            await self.session.commit()
            raise UnauthorizedError("refresh reuse detected", code="invalid_refresh")
        if token.expires_at <= now:
            raise UnauthorizedError("refresh expired", code="invalid_refresh")
        user = await self.users.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("invalid refresh", code="invalid_refresh")
        new_session = await self._issue_pair(user=user, user_agent=user_agent, ip=ip)
        new_token_hash = hash_refresh_token(new_session.refresh_token)
        new_row = await self.refresh_tokens.get_by_hash(new_token_hash)
        await self.refresh_tokens.revoke(
            token, replaced_by=new_row.id if new_row else None
        )
        return new_session

    async def logout(self, *, refresh_plain: str | None) -> None:
        if refresh_plain is None:
            return
        token_hash = hash_refresh_token(refresh_plain)
        token = await self.refresh_tokens.get_by_hash(token_hash)
        if token is None or token.revoked_at is not None:
            return
        await self.refresh_tokens.revoke(token, replaced_by=None)

    async def _issue_pair(
        self,
        *,
        user: User,
        user_agent: str | None,
        ip: str | None,
    ) -> IssuedSession:
        settings = get_settings()
        now = datetime.now(UTC)
        refresh_plain = generate_refresh_token()
        refresh_expires_at = now + timedelta(seconds=settings.refresh_ttl_seconds)
        row = await self.refresh_tokens.insert(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_plain),
            issued_at=now,
            expires_at=refresh_expires_at,
            user_agent=user_agent,
            ip=ip,
        )
        access_token, access_expires_at = encode_access_token(
            sub=str(user.id), sid=str(row.id)
        )
        return IssuedSession(
            user=user,
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=refresh_plain,
            refresh_expires_at=refresh_expires_at,
        )
