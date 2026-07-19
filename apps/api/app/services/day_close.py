"""DayCloseService — SP-100..SP-104 / INV-5.

Responsabilidades:

- **Fechar o dia** idempotentemente (SP-101, Const. §29): 2ª chamada não
  regrava `closed_at` nem sobrescreve `narrative`.
- **Recompute forçado** antes de congelar (SP-102, INV-4/Const. §10):
  totais podem estar desatualizados se algum recompute anterior falhou.
- **Gerar narrative** via LLM alimentada por totais já calculados
  (SP-103, INV-1) e concatenar disclaimer (SP-104, Const. §26).
- **Auditar** cada fechamento (Const. §22, INV-10).

Sobre INV-5: apenas o fechamento cria `closed_at` + status. Depois disso,
qualquer mutation em records daquele dia é bloqueada pelos services de
correction/deletion (`DayClosedError`). O snapshot congelado permanece
como fonte de verdade — reabrir dia não é feature do MVP.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.integrations.anthropic.client import AnthropicClient
from app.models import DailySnapshot, DayLog, User
from app.repositories.day_log import DayLogRepository
from app.repositories.food import AuditEventRepository
from app.services.chat import local_today
from app.services.daily_recompute import DailyRecomputeService, RecomputeResult

_DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)

_FALLBACK_NARRATIVE = (
    "Dia encerrado com os totais registrados no chat. Se algum item ainda "
    "precisar de confirmação, você pode ajustar amanhã, mas hoje já está "
    "fechado."
)


@dataclass(slots=True)
class DayCloseResult:
    day_log: DayLog
    snapshot: DailySnapshot
    narrative: str
    was_already_closed: bool


class DayCloseService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        anthropic: AnthropicClient | None = None,
    ) -> None:
        self.session = session
        self.anthropic = anthropic
        self.day_logs = DayLogRepository(session)
        self.audit = AuditEventRepository(session)

    async def close_today(
        self, *, user: User, message_id: uuid.UUID | None = None
    ) -> DayCloseResult:
        return await self.close_date(
            user=user, log_date=local_today(user.timezone), message_id=message_id
        )

    async def close_date(
        self,
        *,
        user: User,
        log_date: date,
        message_id: uuid.UUID | None = None,
    ) -> DayCloseResult:
        # SP-100 aciona via chat "hoje"; via REST podemos receber qualquer data.
        # get_or_create é aceitável — usuário pode "fechar" um dia sem
        # registros, resultando em snapshot zerado.
        day_log = await self.day_logs.get_or_create(user_id=user.id, log_date=log_date)

        if day_log.status == "closed":
            # SP-101: idempotência. Não recomputa, não regenera narrative,
            # não toca closed_at. Simplesmente devolve o estado atual.
            snapshot = await self._require_snapshot(day_log.id)
            return DayCloseResult(
                day_log=day_log,
                snapshot=snapshot,
                narrative=snapshot.narrative or _with_disclaimer(_FALLBACK_NARRATIVE),
                was_already_closed=True,
            )

        # SP-102: recompute obrigatório antes de congelar.
        recompute = await DailyRecomputeService(self.session).recompute(day_log.id)

        # SP-103/104: narrative + disclaimer.
        narrative_text = await self._generate_narrative(day_log, recompute)
        narrative_full = _with_disclaimer(narrative_text)

        recompute.snapshot.narrative = narrative_full

        day_log.status = "closed"
        day_log.closed_at = datetime.now(UTC)

        await self.session.flush()

        await self.audit.record(
            user_id=user.id,
            entity_type="day_log",
            entity_id=day_log.id,
            action="close",
            actor="user",
            message_id=message_id,
            before={"status": "open"},
            after={
                "status": "closed",
                "closed_at": day_log.closed_at.isoformat(),
                "snapshot_version": recompute.snapshot.version,
            },
        )

        return DayCloseResult(
            day_log=day_log,
            snapshot=recompute.snapshot,
            narrative=narrative_full,
            was_already_closed=False,
        )

    async def _generate_narrative(self, day_log: DayLog, recompute: RecomputeResult) -> str:
        payload = _totals_for_narrative(day_log, recompute)
        if self.anthropic is None or not self.anthropic.is_configured:
            return _FALLBACK_NARRATIVE
        result = await self.anthropic.call_narrative(totals_payload=payload)
        if result.text is None:
            return _FALLBACK_NARRATIVE
        return result.text.strip()

    async def _require_snapshot(self, day_log_id: uuid.UUID) -> DailySnapshot:
        stmt = select(DailySnapshot).where(DailySnapshot.day_log_id == day_log_id)
        snapshot = (await self.session.execute(stmt)).scalar_one_or_none()
        if snapshot is None:
            # Situação anômala: fechado mas sem snapshot. Forçamos recompute
            # apenas para conseguir devolver totals coerentes.
            recompute = await DailyRecomputeService(self.session).recompute(day_log_id)
            return recompute.snapshot
        return snapshot


def _with_disclaimer(text: str) -> str:
    # SP-104 / Const. §26: disclaimer SEMPRE presente. Nunca duplicar.
    stripped = text.rstrip()
    if _DISCLAIMER in stripped:
        return stripped
    return f"{stripped}\n\n{_DISCLAIMER}"


def _totals_for_narrative(day_log: DayLog, recompute: RecomputeResult) -> dict[str, object]:
    snapshot = recompute.snapshot
    return {
        "date": day_log.log_date.isoformat(),
        "kcal_in": float(snapshot.kcal_in),
        "kcal_out": float(snapshot.kcal_out),
        "kcal_balance": float(snapshot.kcal_balance),
        "protein_g": float(snapshot.protein_g),
        "carbs_g": float(snapshot.carbs_g),
        "fat_g": float(snapshot.fat_g),
        "fiber_g": float(snapshot.fiber_g),
        "water_ml": int(snapshot.water_ml),
        "other_liquids_ml": int(snapshot.other_liquids_ml),
        # Enviamos apenas os códigos (não os IDs das entidades) — a LLM
        # não precisa saber referências internas para gerar narrative.
        "warning_codes": [w["code"] for w in recompute.warnings],
    }


class DayNotFound(NotFoundError):
    def __init__(self, log_date: date) -> None:
        super().__init__(
            f"no day_log for user on {log_date.isoformat()}",
            code="day_not_found",
        )
