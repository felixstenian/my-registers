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
        _bootstrap_admin(settings.default_admin_email.lower(), settings.default_admin_password)
    )
    action = "created" if created else "already_exists"
    logger.info(
        "bootstrap_admin",
        extra={"event": "cli_bootstrap", "user_id": user_id},
    )
    typer.echo(f"[bootstrap] {action} user_id={user_id}")


async def _seed_nutrition() -> tuple[int, int]:
    from app.integrations.nutrition.seed import seed_from_csv

    async with SessionLocal() as session:
        result = await seed_from_csv(session)
        await session.commit()
        return result.inserted, result.updated


@app.command("seed-nutrition")
def seed_nutrition() -> None:
    """Popula/atualiza o catálogo `nutrient_facts` a partir de `seed_tbca.csv`.

    Idempotente: rodar duas vezes deixa o banco no mesmo estado da segunda
    execução do CSV. Não toca em rótulos criados por OCR ou entradas manuais.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    inserted, updated = asyncio.run(_seed_nutrition())
    logger.info(
        "seed_nutrition_done",
        extra={"event": "cli_seed_nutrition", "inserted": inserted, "updated": updated},
    )
    typer.echo(f"[seed-nutrition] inserted={inserted} updated={updated}")


async def _reseed_catalog() -> tuple[int, int]:
    from app.services.catalog_backfill import CatalogBackfillService

    async with SessionLocal() as session:
        service = CatalogBackfillService(session)
        result = await service.reseed_catalog()
        await session.commit()
    return result.seed_inserted, result.seed_updated


@app.command("reseed-catalog")
def reseed_catalog() -> None:
    """Insere fatos TBCA faltantes no `nutrient_facts` a partir do CSV atual.

    O banco foi seedado de uma versão antiga do `seed_tbca.csv` (DB tinha 35
    fatos; o CSV atual tem 65). `seed_from_csv` faz upsert idempotente, então
    rodar duas vezes é inofensivo. NÃO renomeia nada: os `canonical_name` no
    banco já são a forma normalizada do CSV (ex.: `brocolis_cozido` →
    `brocoll_cozido`), e renomear quebraria o lookup.
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    inserted, updated = asyncio.run(_reseed_catalog())
    logger.info(
        "reseed_catalog_done",
        extra={"event": "cli_reseed_catalog", "inserted": inserted, "updated": updated},
    )
    typer.echo(f"[reseed-catalog] inserted={inserted} updated={updated}")


async def _backfill_zeroed(include_closed: bool) -> None:
    from app.services.catalog_backfill import CatalogBackfillService

    async with SessionLocal() as session:
        service = CatalogBackfillService(session)
        result = await service.backfill_zeroed_items(include_closed=include_closed)
        await session.commit()
    typer.echo(
        f"[backfill-zeroed] scanned={result.scanned} fixed={result.fixed} "
        f"recomputed_days={result.recomputed_days}"
    )
    for name in result.unresolved:
        typer.echo(f"  unresolved (sem hit no catálogo): {name}")
    for name in result.skipped_closed:
        typer.echo(f"  skipped (dia fechado): {name}")


@app.command("backfill-zeroed")
def backfill_zeroed(
    include_closed: bool = typer.Option(
        False,
        "--include-closed",
        help="Corrige também itens em dias fechados (INV-5: use com responsabilidade).",
    ),
) -> None:
    """Religa food_items legados com kcal=0 ao catálogo e recomputa macros.

    Correção one-off para retrospectiva: rode `reseed-catalog` antes se o
    catálogo do banco estiver defasado do CSV (fatos faltantes).
    """
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    asyncio.run(_backfill_zeroed(include_closed))


@app.command()
def version() -> None:
    typer.echo("my-registers-api 0.0.0")


if __name__ == "__main__":
    app()
