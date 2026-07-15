"""CLI administrativa. Executar com: `python -m app.cli <cmd>`.

Comandos disponíveis nesta fase (Fase 0):
- `bootstrap`  — placeholder idempotente; será implementado na Fase 1.

Comandos futuros:
- `create-admin`      (Fase 1)
- `seed-nutrition`    (Fase 4)
- `recompute-day`     (Fase 4/7)
- `reset-password`    (Fase 1)
"""

import logging

import typer

from app.core.config import get_settings
from app.core.logging import configure_logging

app = typer.Typer(add_completion=False, no_args_is_help=True)
logger = logging.getLogger("app.cli")


@app.command()
def bootstrap() -> None:
    """Bootstrap idempotente (Fase 1 implementa a criação real do admin)."""
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    if not settings.default_admin_email:
        typer.echo("DEFAULT_ADMIN_EMAIL não definido; abortando.", err=True)
        raise typer.Exit(code=1)
    logger.info(
        "bootstrap_placeholder",
        extra={"event": "cli_bootstrap"},
    )
    typer.echo(
        "[bootstrap] Fase 0: sem tabelas ainda; nada a fazer. "
        "Implementação real virá na Fase 1 (usuários + refresh_tokens)."
    )


@app.command()
def version() -> None:
    typer.echo("my-registers-api 0.0.0")


if __name__ == "__main__":
    app()
