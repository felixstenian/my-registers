"""Fixtures compartilhadas para testes de integração.

Usa um DB de teste `registers_test` separado do dev DB. Migrations aplicadas
uma vez no início da sessão via subprocess (isola o `asyncio.run` do
alembic env.py do event loop do pytest-asyncio); entre cada teste, TRUNCATE
das tabelas de negócio para isolar estado.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio

TEST_DB_NAME = "registers_test"
TEST_DB_URL = (
    f"postgresql+asyncpg://registers_app:dev_password@localhost:5432/{TEST_DB_NAME}"
)

# Setar antes de qualquer import da app (get_settings é @lru_cache).
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["APP_ENV"] = "test"
os.environ["JWT_SECRET"] = "test-secret-do-not-use-in-prod"
os.environ["COOKIE_SECURE"] = "false"
os.environ["COOKIE_SAMESITE"] = "lax"
os.environ["DEFAULT_ADMIN_EMAIL"] = "admin@example.com"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "adminadmin"


async def _ensure_test_db() -> None:
    import asyncpg

    conn = await asyncpg.connect(
        host="localhost",
        port=5432,
        user="registers_app",
        password="dev_password",
        database="postgres",
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await conn.close()


def _run_migrations() -> None:
    """Roda alembic em subprocess para isolar o `asyncio.run` do env.py."""
    env = os.environ.copy()
    env["DATABASE_URL"] = TEST_DB_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade failed: {result.stdout}\n{result.stderr}"
        )


@pytest.fixture(scope="session", autouse=True)
def _prepare_database() -> Iterator[None]:
    asyncio.run(_ensure_test_db())
    _run_migrations()
    yield


@pytest_asyncio.fixture()
async def test_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(TEST_DB_URL, echo=False, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture()
async def db_session(test_engine) -> AsyncIterator:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    async with test_engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE refresh_tokens, users RESTART IDENTITY CASCADE")
        )
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    async with Session() as session:
        yield session


@pytest.fixture(autouse=True)
def _reset_rate_limiters() -> Iterator[None]:
    from app.core.rate_limit import reset_login_limiters

    reset_login_limiters()
    yield
    reset_login_limiters()


@pytest_asyncio.fixture()
async def client(db_session, test_engine) -> AsyncIterator:
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.api.deps import get_session as get_session_dep
    from app.main import app

    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_session():
        async with Session() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_session_dep] = _override_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture()
async def admin_user(db_session):
    from app.core.security import hash_password
    from app.repositories.user import UserRepository

    users = UserRepository(db_session)
    user = await users.create(
        email="admin@example.com",
        password_hash=hash_password("adminadmin"),
        display_name="Admin",
    )
    await db_session.commit()
    return user
