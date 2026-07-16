"""CLI administrativa. Executar com: `python -m app.cli <cmd>`.

Const. Art. V §18 e Art. VI §24: criação e reset de usuário são
exclusivamente CLI — nunca há endpoint HTTP público.
"""

from __future__ import annotations

import asyncio
import logging

import typer

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.repositories.user import UserRepository

app = typer.Typer(add_completion=False, no_args_is_help=True)
logger = logging.getLogger("app.cli")


async def _bootstrap_admin(email: str, password: str) -> tuple[str, bool]:
    async with SessionLocal() as session:
        users = UserRepository(session)
        existing = await users.get_by_email(email)
        if existing is not None:
            return str(existing.id), False
        user = await users.create(email=email, password_hash=hash_password(password))
        await session.commit()
        return str(user.id), True


@app.command()
def bootstrap() -> None:
    """Cria (ou confirma) o usuário admin default a partir do ambiente.

    Lê `DEFAULT_ADMIN_EMAIL` e `DEFAULT_ADMIN_PASSWORD`. Idempotente:
    executar duas vezes não sobrescreve nada. Nunca ecoa a senha em stdout
    nem em logs (Const. Art. V §19).
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)

    if not settings.default_admin_email:
        typer.echo("DEFAULT_ADMIN_EMAIL não definido; abortando.", err=True)
        raise typer.Exit(code=1)
    if not settings.default_admin_password:
        typer.echo("DEFAULT_ADMIN_PASSWORD não definido; abortando.", err=True)
        raise typer.Exit(code=1)

    user_id, created = asyncio.run(
        _bootstrap_admin(
            settings.default_admin_email.lower(), settings.default_admin_password
        )
    )
    action = "created" if created else "already_exists"
    logger.info(
        "bootstrap_admin",
        extra={"event": "cli_bootstrap", "user_id": user_id},
    )
    typer.echo(f"[bootstrap] {action} user_id={user_id}")


@app.command()
def version() -> None:
    typer.echo("my-registers-api 0.0.0")


if __name__ == "__main__":
    app()
