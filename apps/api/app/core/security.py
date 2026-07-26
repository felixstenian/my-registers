"""Hash de senha (Argon2id) + JWT HS256 curto + refresh token opaco.

Const. Art. V §15-17. Parâmetros Argon2id fixados pela Constituição;
rehash oportunístico no login se `needs_rehash()` sinalizar.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from jose import JWTError, jwt

from app.core.config import get_settings

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=2,
)

_JWT_ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def encode_access_token(*, sub: str, sid: str) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.jwt_access_ttl_seconds)
    payload: dict[str, Any] = {
        "sub": sub,
        "sid": sid,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)
    return token, exp


def decode_access_token(token: str) -> dict[str, Any] | None:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except JWTError:
        return None


def generate_refresh_token() -> str:
    """32 bytes URL-safe opacos. Nunca persistido em plaintext."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
