"""Testes do CLI administrativo — bootstrap, seed-nutrition, version.

Cobre TC-U-001..010 (unitários) e TC-I-001..003 (integração) da spec
specs/features/admin-bootstrap-cli/test-cases.md.

Const. Art. V §18, Art. VI §24, ADR-001.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator
from decimal import Decimal
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from typer.testing import CliRunner

import app.cli.main as cli_module
from app.cli.main import _bootstrap_admin
from app.core.security import hash_password, needs_rehash, verify_password
from app.models import NutrientFact, User

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixture: patch SessionLocal in app.cli.main to use the test engine.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture()
async def cli_session(
    test_engine: AsyncEngine,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Patches app.cli.main.SessionLocal to use the test engine so
    _bootstrap_admin writes to the test DB (same engine as db_session)."""
    Session = async_sessionmaker(test_engine, expire_on_commit=False, class_=AsyncSession)
    original = cli_module.SessionLocal
    cli_module.SessionLocal = Session
    yield Session
    cli_module.SessionLocal = original


# ---------------------------------------------------------------------------
# TC-U-001 / TC-U-002 / TC-U-003 — _bootstrap_admin (async, DB real)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_admin_creates_user_in_empty_db(cli_session, db_session: AsyncSession):
    """TC-U-001: _bootstrap_admin cria user em DB vazio."""
    user_id, created = await _bootstrap_admin("admin@example.com", "adminadmin")

    assert created is True
    assert user_id is not None

    user = (
        await db_session.execute(select(User).where(User.email == "admin@example.com"))
    ).scalar_one()
    assert user.email == "admin@example.com"
    assert user.password_hash.startswith("$argon2id$")


@pytest.mark.asyncio
async def test_bootstrap_admin_idempotent_on_existing_user(cli_session, db_session: AsyncSession):
    """TC-U-002: _bootstrap_admin idempotente — não sobrescreve password_hash."""
    first_id, first_created = await _bootstrap_admin("admin@example.com", "adminadmin")
    assert first_created is True

    original_hash = (
        (await db_session.execute(select(User).where(User.email == "admin@example.com")))
        .scalar_one()
        .password_hash
    )

    second_id, second_created = await _bootstrap_admin("admin@example.com", "nova-senha-789")
    assert second_created is False
    assert second_id == first_id

    user = (
        await db_session.execute(select(User).where(User.email == "admin@example.com"))
    ).scalar_one()
    assert user.password_hash == original_hash


@pytest.mark.asyncio
async def test_bootstrap_admin_lowercases_email(cli_session, db_session: AsyncSession):
    """TC-U-003: _bootstrap_admin lowercases email antes do lookup."""
    _, created = await _bootstrap_admin("Admin@Example.COM", "adminadmin")
    assert created is True

    _, created_again = await _bootstrap_admin("ADMIN@EXAMPLE.COM", "x")
    assert created_again is False


# ---------------------------------------------------------------------------
# TC-U-004 / TC-U-005 — bootstrap CLI com envs vazios (sync, sem DB)
# ---------------------------------------------------------------------------


def test_bootstrap_aborts_when_password_empty(monkeypatch: pytest.MonkeyPatch):
    """TC-U-004: DEFAULT_ADMIN_PASSWORD vazio → exit 1 + stderr."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "")

    result = runner.invoke(app=cli_module.app, args=["bootstrap"])

    assert result.exit_code == 1
    assert "DEFAULT_ADMIN_PASSWORD" in result.stderr
    get_settings.cache_clear()


def test_bootstrap_aborts_when_email_empty(monkeypatch: pytest.MonkeyPatch):
    """TC-U-005: DEFAULT_ADMIN_EMAIL vazio dispara primeiro → exit 1."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "adminadmin")

    result = runner.invoke(app=cli_module.app, args=["bootstrap"])

    assert result.exit_code == 1
    assert "DEFAULT_ADMIN_EMAIL" in result.stderr
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# TC-U-006 — bootstrap nunca loga senha (Const. §19; mock _bootstrap_admin)
# ---------------------------------------------------------------------------


def test_bootstrap_never_logs_password(monkeypatch: pytest.MonkeyPatch):
    """TC-U-006: stdout só contém action + user_id; senha/hash ausentes."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("DEFAULT_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "super-secret-pwd")

    async def _fake_bootstrap(email: str, password: str):
        return ("fake-uuid", True)

    with patch.object(cli_module, "_bootstrap_admin", _fake_bootstrap):
        result = runner.invoke(app=cli_module.app, args=["bootstrap"])

    assert result.exit_code == 0
    stdout = result.stdout
    assert "super-secret-pwd" not in stdout
    assert "password_hash" not in stdout.lower()
    assert "password" not in stdout.lower()
    assert "[bootstrap]" in stdout
    assert "user_id=" in stdout
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# TC-U-007 — hash_password produz Argon2id com params da Const.
# ---------------------------------------------------------------------------


def test_hash_password_produces_argon2id_with_fixed_params():
    """TC-U-007: hash segue $argon2id$v=19$m=65536,t=3,p=2$ (ADR-001, Const. §15)."""
    h = hash_password("adminadmin")
    assert h.startswith("$argon2id$")
    match = re.match(r"^\$argon2id\$v=\d+\$m=(\d+),t=(\d+),p=(\d+)\$", h)
    assert match is not None
    m, t, p = match.groups()
    assert int(m) == 65536
    assert int(t) == 3
    assert int(p) == 2


# ---------------------------------------------------------------------------
# TC-U-008 — needs_rehash detecta hash antigo
# ---------------------------------------------------------------------------


def test_needs_rehash_detects_outdated_params():
    """TC-U-008: needs_rehash retorna True para hash com params antigos."""
    from argon2 import PasswordHasher

    old_hasher = PasswordHasher(time_cost=2, memory_cost=32 * 1024, parallelism=2)
    old_hash = old_hasher.hash("adminadmin")
    assert needs_rehash(old_hash) is True

    current_hash = hash_password("adminadmin")
    assert needs_rehash(current_hash) is False


# ---------------------------------------------------------------------------
# TC-U-009 — seed-nutrition idempotente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_nutrition_idempotent(db_session: AsyncSession):
    """TC-U-009: segunda execução atualiza valores sem duplicar; não toca source != TBCA."""
    from app.integrations.nutrition.seed import seed_from_csv

    first = await seed_from_csv(db_session)
    await db_session.commit()
    assert first.inserted > 0

    second = await seed_from_csv(db_session)
    await db_session.commit()
    assert second.inserted == 0
    assert second.updated > 0

    fact = (
        await db_session.execute(
            select(NutrientFact).where(
                NutrientFact.canonical_name == "arroz_branco_cozido",
                NutrientFact.source == "TBCA_2023",
            )
        )
    ).scalar_one()
    assert fact.kcal is not None
    assert fact.kcal > 0

    manual_fact = NutrientFact(
        canonical_name="manual_item",
        aliases=["manual_item"],
        source="manual",
        basis="per_100g",
        kcal=Decimal("999"),
    )
    db_session.add(manual_fact)
    await db_session.flush()
    await db_session.commit()

    await seed_from_csv(db_session)
    await db_session.commit()

    refreshed = await db_session.get(NutrientFact, manual_fact.id)
    assert refreshed is not None
    assert refreshed.kcal == Decimal("999")


# ---------------------------------------------------------------------------
# TC-U-010 — version exibe build
# ---------------------------------------------------------------------------


def test_version_displays_build_string():
    """TC-U-010: `python -m app.cli version` → stdout 'my-registers-api 0.0.0'."""
    result = runner.invoke(app=cli_module.app, args=["version"])
    assert result.exit_code == 0
    assert "my-registers-api" in result.stdout
    assert "0.0.0" in result.stdout


# ---------------------------------------------------------------------------
# TC-U-001 (complemento) — verify_password roundtrip
# ---------------------------------------------------------------------------


def test_verify_password_roundtrip():
    """TC-U-001 (complemento): hash + verify roundtrip Boolean."""
    h = hash_password("my-secret")
    assert verify_password("my-secret", h) is True
    assert verify_password("wrong", h) is False


# ---------------------------------------------------------------------------
# TC-I-001 — bootstrap em Postgres real (via _bootstrap_admin + cli_session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_bootstrap_creates_admin_in_real_db(cli_session, db_session: AsyncSession):
    """TC-I-001: _bootstrap_admin (invocado pelo CLI) cria User em Postgres real."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    user_id, created = await _bootstrap_admin("admin@example.com", "adminadmin")
    assert created is True
    assert user_id is not None

    user = (
        await db_session.execute(select(User).where(User.email == "admin@example.com"))
    ).scalar_one()
    assert user.password_hash.startswith("$argon2id$")
    assert user.is_active is True

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# TC-I-002 — bootstrap 2x idempotente (via _bootstrap_admin + cli_session)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cli_bootstrap_idempotent_second_run(cli_session, db_session: AsyncSession):
    """TC-I-002: segunda chamada mostra already_exists e não muda o hash."""
    from app.core.config import get_settings

    get_settings.cache_clear()

    # Primeira chamada.
    r1_id, r1_created = await _bootstrap_admin("admin@example.com", "adminadmin")
    assert r1_created is True

    hash_before = (
        (await db_session.execute(select(User).where(User.email == "admin@example.com")))
        .scalar_one()
        .password_hash
    )

    # Segunda chamada.
    r2_id, r2_created = await _bootstrap_admin("admin@example.com", "adminadmin")
    assert r2_created is False
    assert r2_id == r1_id

    hash_after = (
        (await db_session.execute(select(User).where(User.email == "admin@example.com")))
        .scalar_one()
        .password_hash
    )
    assert hash_before == hash_after

    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# TC-I-003 — Login após bootstrap (SP-01 chain; via client + admin_user)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_works_after_bootstrap(client, admin_user):
    """TC-I-003: após bootstrap (admin_user fixture), POST /auth/login funciona.
    Cobre a cadeia SP-01: admin criado → login devolve 204 + cookies."""
    resp = await client.post(
        "/auth/login",
        json={"email": "admin@example.com", "password": "adminadmin"},
    )
    assert resp.status_code == 204
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies
