"""Endpoints exclusivos do ambiente E2E (`APP_ENV=test`).

Nunca são registrados em produção — `create_app` só inclui esse router se
`settings.app_env == "test"`. Ainda assim cada handler faz um guard runtime
como defesa em profundidade (retorna 404 fora de test).

Endpoints:
- `POST /test/reset` — TRUNCATE das tabelas de negócio + recria admin_user
  a partir de `DEFAULT_ADMIN_EMAIL/PASSWORD`. Também drena as filas do
  `TestAnthropicClient`.
- `POST /test/queue-llm-response` — enfileira envelope canned na fila
  correspondente (record_intent | record_intent_error | narrative |
  weekly_narrative). Payload Pydantic valida schema básico; envelope de
  intent é validado como `LLMEnvelope` estrito. `record_intent_error`
  enfileira um error code que faz `call_record_intent` devolver
  `LLMCallResult(error=...)`, disparando o fallback SP-14.
- `GET /test/queue-llm-status` — retorna tamanho atual de cada fila
  (útil pra debug de setup em Playwright).

Playwright chama esses endpoints via `page.request.post(...)` antes de
disparar a interação na UI.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.core.config import get_settings
from app.core.rate_limit import reset_login_limiters
from app.core.security import hash_password
from app.integrations.anthropic import test_client as fake
from app.repositories.user import UserRepository
from app.schemas.llm import LLMEnvelope

router = APIRouter(prefix="/test", tags=["test-hooks"])

# Ordem de DELETE (filhos -> pais) pra respeitar FKs. Usamos DELETE em vez
# de TRUNCATE porque `nutrient_facts.label_media_id -> media` tem
# ON DELETE SET NULL, e o TRUNCATE ignora esse comportamento (cascata ou
# aborta), o que apagaria o seed TBCA junto com media.
# nutrient_facts NAO e' listado: e catalogo estatico seeded no boot da api.
_DELETE_ORDER = (
    "audit_events",
    "food_items",
    "food_records",
    "beverage_records",
    "water_records",
    "activity_records",
    "daily_snapshots",
    "weekly_reports",
    "message_media",
    "messages",
    "day_logs",
    "media",
    "refresh_tokens",
    "users",
)


def _require_test_env() -> None:
    if get_settings().app_env != "test":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


class QueueLlmRequest(BaseModel):
    kind: Literal["record_intent", "record_intent_error", "narrative", "weekly_narrative"]
    # Para record_intent: envelope completo (dict aceita `_LenientBase` mode).
    envelope: dict[str, Any] | None = None
    # Para record_intent_error: error code string (ex.: "anthropic_timeout").
    error: str | None = None
    # Para narrative / weekly_narrative: texto pt-BR pronto.
    text: str | None = None


class QueueStatusResponse(BaseModel):
    record_intent: int = Field(ge=0)
    record_error: int = Field(ge=0)
    narrative: int = Field(ge=0)
    weekly_narrative: int = Field(ge=0)


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
async def reset_state(session: AsyncSession = Depends(get_session)) -> Response:
    _require_test_env()
    settings = get_settings()

    for table in _DELETE_ORDER:
        await session.execute(text(f"DELETE FROM {table}"))
    await UserRepository(session).create(
        email=settings.default_admin_email,
        password_hash=hash_password(settings.default_admin_password),
        display_name="Admin",
    )
    # Commit explicito antes de retornar: o Playwright dispara /auth/login
    # imediatamente apos receber 204, e sem esse commit hava race — a
    # request de login veria o snapshot antes do INSERT do admin novo e
    # inseria refresh_token apontando pra user id stale (FK violation).
    await session.commit()

    fake.clear_all_queues()
    reset_login_limiters()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/queue-llm-response", status_code=status.HTTP_204_NO_CONTENT)
async def queue_llm_response(payload: QueueLlmRequest) -> Response:
    _require_test_env()

    if payload.kind == "record_intent":
        if payload.envelope is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="envelope required for record_intent",
            )
        envelope = LLMEnvelope.model_validate(payload.envelope)
        fake.queue_record_intent(envelope)
    elif payload.kind == "record_intent_error":
        if not payload.error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="error required for record_intent_error",
            )
        fake.queue_record_error(payload.error)
    elif payload.kind == "narrative":
        fake.queue_narrative(payload.text)
    else:
        fake.queue_weekly_narrative(payload.text)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/queue-llm-status", response_model=QueueStatusResponse)
async def queue_llm_status() -> QueueStatusResponse:
    _require_test_env()
    return QueueStatusResponse(**fake.queue_sizes())
