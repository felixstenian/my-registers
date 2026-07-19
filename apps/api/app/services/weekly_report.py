"""WeeklyReportService — SP-110..SP-113 / INV-8.

Regras:

- **Janela** (SP-110, Const. §30, INV-8): últimos 7 `day_logs` com
  `status='closed'`. Dias abertos são ignorados. Menos de 7 fechados →
  entrega o disponível + warning `insufficient_history`.
- **Cálculos determinísticos** (SP-111, Const. §5, INV-1): todos os
  totais e médias vêm de agregação SQL sobre `daily_snapshots`. A LLM
  apenas gera texto sobre esses números; nunca recalcula.
- **Idempotência** (SP-112): se as versões dos snapshots que compõem a
  janela não mudaram desde a última geração, retorna o mesmo report
  (mesmo `id`), sem regenerar `narrative` nem tocar `generated_at`.
- **Ordenação** (SP-113): `per_day` é do mais antigo para o mais recente.

Sobre INV-5 e recompute: se o usuário reabrisse um dia (feature fora do
MVP), o `snapshot.version` mudaria e o hash de versões cairia; a próxima
`generate()` detecta e regenera. Como reabertura não existe no MVP, a
janela é praticamente estável.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.anthropic.client import AnthropicClient
from app.models import DailySnapshot, DayLog, User, WeeklyReport

_TOTAL_FIELDS: tuple[str, ...] = (
    "kcal_in",
    "kcal_out",
    "kcal_balance",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "water_ml",
    "other_liquids_ml",
)

_FALLBACK_NARRATIVE = (
    "Semana consolidada com base nos dias encerrados. Confira totais e "
    "médias para acompanhar tendências."
)

_DISCLAIMER = (
    "As estimativas nutricionais são aproximações e não substituem "
    "acompanhamento médico ou nutricional."
)


@dataclass(slots=True)
class WeeklyReportResult:
    report: WeeklyReport
    reused: bool


class WeeklyReportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        anthropic: AnthropicClient | None = None,
    ) -> None:
        self.session = session
        self.anthropic = anthropic

    async def generate(
        self, *, user: User, message_id: uuid.UUID | None = None
    ) -> WeeklyReportResult:
        closed = await self._fetch_last_closed_days(user_id=user.id, limit=7)
        window_start, window_end = _window_bounds(closed)
        snapshots = await self._fetch_snapshots(day_log_ids=[d.id for d in closed])

        warnings: list[dict[str, Any]] = []
        if len(closed) < 7:
            # SP-110: relatório entrega o disponível + warning.
            warnings.append({"code": "insufficient_history", "days_available": len(closed)})

        totals, averages = _aggregate(snapshots)
        per_day = _per_day(closed, snapshots)  # SP-113: já ordenado ASC.
        snapshot_versions = [
            {"day_log_id": str(s.day_log_id), "version": s.version}
            for s in sorted(snapshots, key=lambda x: x.day_log_id.bytes)
        ]

        if not closed:
            # SP-110: sem histórico → devolvemos um report transiente (não
            # persistimos porque `(user_id, NULL, NULL)` não seria idempotente
            # sob a UNIQUE constraint do Postgres — NULL != NULL). O cliente
            # recebe warning `insufficient_history`.
            transient = WeeklyReport(
                id=uuid.uuid4(),
                user_id=user.id,
                window_start=None,
                window_end=None,
                days_included=0,
                totals=totals,
                averages=averages,
                per_day=per_day,
                warnings=warnings,
                snapshot_versions=snapshot_versions,
                narrative=_with_disclaimer(_FALLBACK_NARRATIVE),
                generated_at=datetime.now(UTC),
                version=1,
            )
            return WeeklyReportResult(report=transient, reused=False)

        existing = await self._find_existing(
            user_id=user.id,
            window_start=window_start,
            window_end=window_end,
        )
        if existing is not None and existing.snapshot_versions == snapshot_versions:
            # SP-112: nada mudou → devolve o mesmo report sem regerar.
            return WeeklyReportResult(report=existing, reused=True)

        narrative = await self._generate_narrative(
            user=user,
            window_start=window_start,
            window_end=window_end,
            totals=totals,
            averages=averages,
            warnings=warnings,
        )
        narrative_full = _with_disclaimer(narrative)

        payload = dict(
            user_id=user.id,
            window_start=window_start,
            window_end=window_end,
            days_included=len(closed),
            totals=totals,
            averages=averages,
            per_day=per_day,
            warnings=warnings,
            snapshot_versions=snapshot_versions,
            narrative=narrative_full,
            generated_at=datetime.now(UTC),
        )

        stmt = (
            pg_insert(WeeklyReport)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=["user_id", "window_start", "window_end"],
                set_={
                    **{k: v for k, v in payload.items() if k not in {"user_id"}},
                    "version": WeeklyReport.__table__.c.version + 1,
                },
            )
            .returning(WeeklyReport)
            .execution_options(populate_existing=True)
        )
        report = (await self.session.execute(stmt)).scalar_one()
        await self.session.flush()
        return WeeklyReportResult(report=report, reused=False)

    async def latest(self, *, user: User) -> WeeklyReport | None:
        """Retorna o relatório mais recente sem regerar. Se não existir, None."""
        stmt = (
            select(WeeklyReport)
            .where(WeeklyReport.user_id == user.id)
            .order_by(WeeklyReport.generated_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _fetch_last_closed_days(self, *, user_id: uuid.UUID, limit: int) -> list[DayLog]:
        stmt = (
            select(DayLog)
            .where(
                DayLog.user_id == user_id,
                DayLog.status == "closed",
            )
            .order_by(DayLog.log_date.desc())
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars())

    async def _fetch_snapshots(self, *, day_log_ids: list[uuid.UUID]) -> list[DailySnapshot]:
        if not day_log_ids:
            return []
        stmt = select(DailySnapshot).where(DailySnapshot.day_log_id.in_(day_log_ids))
        return list((await self.session.execute(stmt)).scalars())

    async def _find_existing(
        self,
        *,
        user_id: uuid.UUID,
        window_start,
        window_end,
    ) -> WeeklyReport | None:
        if window_start is None or window_end is None:
            return None
        stmt = select(WeeklyReport).where(
            WeeklyReport.user_id == user_id,
            WeeklyReport.window_start == window_start,
            WeeklyReport.window_end == window_end,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _generate_narrative(
        self,
        *,
        user: User,
        window_start,
        window_end,
        totals: dict[str, Any],
        averages: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> str:
        if self.anthropic is None or not self.anthropic.is_configured:
            return _FALLBACK_NARRATIVE
        payload = {
            "window_start": window_start.isoformat() if window_start else None,
            "window_end": window_end.isoformat() if window_end else None,
            "totals": totals,
            "averages": averages,
            "warning_codes": [w["code"] for w in warnings],
        }
        result = await self.anthropic.call_weekly_narrative(payload)
        if result.text is None:
            return _FALLBACK_NARRATIVE
        return result.text.strip()


def _window_bounds(
    closed_days: list[DayLog],
) -> tuple[Any, Any]:
    if not closed_days:
        return None, None
    dates = [d.log_date for d in closed_days]
    return min(dates), max(dates)


def _aggregate(
    snapshots: list[DailySnapshot],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not snapshots:
        return (
            {field: 0.0 if _is_float_field(field) else 0 for field in _TOTAL_FIELDS},
            {field: 0.0 if _is_float_field(field) else 0 for field in _TOTAL_FIELDS},
        )
    totals: dict[str, Any] = {}
    for field in _TOTAL_FIELDS:
        raw = sum((_coerce(getattr(s, field)) for s in snapshots), Decimal(0))
        totals[field] = _out_type(field, raw)
    averages: dict[str, Any] = {}
    for field in _TOTAL_FIELDS:
        raw = sum((_coerce(getattr(s, field)) for s in snapshots), Decimal(0))
        avg = raw / Decimal(len(snapshots))
        averages[field] = _out_type(field, avg)
    return totals, averages


def _per_day(closed_days: list[DayLog], snapshots: list[DailySnapshot]) -> list[dict[str, Any]]:
    by_id = {s.day_log_id: s for s in snapshots}
    ordered = sorted(closed_days, key=lambda d: d.log_date)
    return [_reduce_snapshot(d, by_id.get(d.id)) for d in ordered]


def _reduce_snapshot(day_log: DayLog, snapshot: DailySnapshot | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "date": day_log.log_date.isoformat(),
        "closed_at": day_log.closed_at.isoformat() if day_log.closed_at else None,
    }
    if snapshot is None:
        # Dia fechado sem snapshot é anômalo (T-701 garante), mas defendemos.
        payload.update({field: 0.0 for field in _TOTAL_FIELDS})
        payload["version"] = 0
        return payload
    payload["version"] = snapshot.version
    for field in _TOTAL_FIELDS:
        payload[field] = _out_type(field, _coerce(getattr(snapshot, field)))
    return payload


def _with_disclaimer(text: str) -> str:
    stripped = text.rstrip()
    if _DISCLAIMER in stripped:
        return stripped
    return f"{stripped}\n\n{_DISCLAIMER}"


def _is_float_field(field: str) -> bool:
    return field not in {"water_ml", "other_liquids_ml"}


def _coerce(value: Decimal | int | None) -> Decimal:
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(value)


def _out_type(field: str, value: Decimal) -> float | int:
    if _is_float_field(field):
        return float(value)
    return int(value)
