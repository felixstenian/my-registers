"""GET /weekly — relatório semanal (SP-110..113)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_anthropic_client_dep, get_current_user, get_session
from app.integrations.anthropic.client import AnthropicClient
from app.models import User
from app.schemas.weekly import WeeklyReportOut
from app.services.weekly_report import WeeklyReportService

router = APIRouter(prefix="/weekly", tags=["weekly"])


@router.get("", response_model=WeeklyReportOut)
async def get_weekly(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    anthropic_client: AnthropicClient = Depends(get_anthropic_client_dep),
) -> WeeklyReportOut:
    """SP-110/111/113: gera (ou reusa) o relatório da janela de 7 dias
    fechados mais recentes. SP-112: 2ª chamada sem mudanças reusa o mesmo
    `id` sem regenerar `narrative`.

    Se o usuário ainda não fechou nenhum dia, o report vem com
    `days_included=0` e `warnings.insufficient_history`.
    """
    result = await WeeklyReportService(session, anthropic=anthropic_client).generate(
        user=current_user
    )
    return WeeklyReportOut.model_validate(result.report)
