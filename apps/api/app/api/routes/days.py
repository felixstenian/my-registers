"""Endpoints REST de leitura e fechamento de dia (SP-90..SP-104)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_anthropic_client_dep, get_current_user, get_session
from app.integrations.anthropic.client import AnthropicClient
from app.models import User
from app.schemas.days import DayCloseOut, DayRecordsOut, DaySnapshotOut, DayTotalsOut
from app.services.day_close import DayCloseService
from app.services.day_query import DayPayload, DayQueryService

router = APIRouter(prefix="/days", tags=["days"])


def _to_snapshot_out(payload: DayPayload) -> DaySnapshotOut:
    return DaySnapshotOut(
        date=payload.date,
        status=payload.status,  # type: ignore[arg-type]
        closed_at=payload.closed_at,
        totals=DayTotalsOut(**payload.totals),
        records=DayRecordsOut(**payload.records),
        warnings=payload.warnings,
        narrative=payload.narrative,
        snapshot_version=payload.snapshot_version,
    )


@router.get("/today", response_model=DaySnapshotOut)
async def get_today(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DaySnapshotOut:
    """SP-90: dia atual do fuso horário do usuário (SP-92)."""
    # Dia atual: se ainda não existe day_log, criamos vazio para responder
    # totals=0 em vez de 404 — reflete UX de "abri o app e não registrei
    # nada ainda".
    from app.repositories.day_log import DayLogRepository
    from app.services.chat import local_today

    await DayLogRepository(session).get_or_create(
        user_id=current_user.id, log_date=local_today(current_user.timezone)
    )
    payload = await DayQueryService(session).get_today(user=current_user)
    return _to_snapshot_out(payload)


@router.get("/{log_date}", response_model=DaySnapshotOut)
async def get_by_date(
    log_date: date,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DaySnapshotOut:
    """SP-91: dia passado. 404 se não existir day_log daquele dia."""
    payload = await DayQueryService(session).get_by_date(user=current_user, log_date=log_date)
    return _to_snapshot_out(payload)


@router.post(
    "/{log_date}/close",
    response_model=DayCloseOut,
    status_code=status.HTTP_200_OK,
)
async def close_day(
    log_date: date,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    anthropic_client: AnthropicClient = Depends(get_anthropic_client_dep),
) -> DayCloseOut:
    """SP-100/101/102/103/104: fecha o dia; idempotente."""
    result = await DayCloseService(session, anthropic=anthropic_client).close_date(
        user=current_user, log_date=log_date
    )
    # Refetch via DayQueryService para consolidar `records` no shape uniforme.
    payload = await DayQueryService(session).get_by_date(
        user=current_user, log_date=log_date, allow_recompute=False
    )
    return DayCloseOut(
        date=payload.date,
        status=payload.status,  # type: ignore[arg-type]
        closed_at=payload.closed_at,
        totals=DayTotalsOut(**payload.totals),
        records=DayRecordsOut(**payload.records),
        warnings=payload.warnings,
        narrative=result.narrative,
        snapshot_version=payload.snapshot_version,
        was_already_closed=result.was_already_closed,
    )
