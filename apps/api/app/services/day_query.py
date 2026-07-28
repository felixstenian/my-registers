"""DayQueryService — SP-90 / SP-91 / SP-92.

Constrói o payload de resposta para `GET /days/today` e `GET /days/{date}`:

- Localiza (ou cria/recomputa) o `day_log` do usuário na data-alvo (Const.
  Art. III §10 — SNAPSHOT SEMPRE from-scratch nas leituras de dia aberto).
- Recomputa se o snapshot ainda não existir (para não retornar totais
  desalinhados quando `daily_snapshots.version` está stale) — em dia
  fechado NUNCA recomputa (INV-5, Const. Art. VIII §28).
- Retorna records vivos (`deleted_at IS NULL`) agrupados por categoria
  para renderização no cliente.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models import (
    ActivityRecord,
    BeverageRecord,
    DailySnapshot,
    DayLog,
    FoodItem,
    FoodRecord,
    User,
    WaterRecord,
)
from app.services.chat import local_today
from app.services.daily_recompute import DailyRecomputeService


@dataclass(slots=True)
class DayPayload:
    date: date
    status: str
    closed_at: datetime | None
    totals: dict[str, Any]
    records: dict[str, list[dict[str, Any]]]
    warnings: list[dict[str, Any]]
    narrative: str | None
    snapshot_version: int


class DayQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_today(self, *, user: User) -> DayPayload:
        return await self._build(
            user_id=user.id, log_date=local_today(user.timezone), allow_recompute=True
        )

    async def get_by_date(
        self, *, user: User, log_date: date, allow_recompute: bool | None = None
    ) -> DayPayload:
        """SP-91: dia passado. `allow_recompute` = None → decide pelo status.

        - Dia inexistente para o user → 404.
        - Dia aberto sem snapshot → recomputa.
        - Dia fechado → snapshot congelado é sempre a resposta (INV-5).
        """
        return await self._build(
            user_id=user.id, log_date=log_date, allow_recompute=allow_recompute
        )

    async def _build(
        self,
        *,
        user_id: uuid.UUID,
        log_date: date,
        allow_recompute: bool | None,
    ) -> DayPayload:
        day_log = await self._find_day_log(user_id=user_id, log_date=log_date)
        if day_log is None:
            raise NotFoundError(
                f"no day_log for user on {log_date.isoformat()}",
                code="day_not_found",
            )

        snapshot = await self._get_snapshot(day_log.id)
        should_recompute = (
            day_log.status == "open"
            and snapshot is None
            and (allow_recompute is None or allow_recompute)
        )
        if should_recompute:
            recompute = await DailyRecomputeService(self.session).recompute(day_log.id)
            snapshot = recompute.snapshot

        # snapshot pode ainda ser None se o dia está fechado sem snapshot
        # persistido (situação anômala; guardamos como totals zerados para não
        # explodir o cliente).
        totals = _snapshot_to_totals(snapshot)
        warnings = list(snapshot.warnings) if snapshot else []
        records = await self._load_records(day_log.id)

        return DayPayload(
            date=day_log.log_date,
            status=day_log.status,
            closed_at=day_log.closed_at,
            totals=totals,
            records=records,
            warnings=warnings,
            narrative=snapshot.narrative if snapshot else None,
            snapshot_version=snapshot.version if snapshot else 0,
        )

    async def _find_day_log(self, *, user_id: uuid.UUID, log_date: date) -> DayLog | None:
        stmt = select(DayLog).where(DayLog.user_id == user_id, DayLog.log_date == log_date)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _get_snapshot(self, day_log_id: uuid.UUID) -> DailySnapshot | None:
        stmt = select(DailySnapshot).where(DailySnapshot.day_log_id == day_log_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _load_records(self, day_log_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        food = await self._load_food(day_log_id)
        water = await self._load_water(day_log_id)
        beverage = await self._load_beverage(day_log_id)
        activity = await self._load_activity(day_log_id)
        return {
            "food": food,
            "water": water,
            "beverage": beverage,
            "activity": activity,
        }

    async def _load_food(self, day_log_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = (
            select(FoodRecord, FoodItem)
            .join(FoodItem, FoodItem.food_record_id == FoodRecord.id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
            )
            .order_by(FoodRecord.occurred_at, FoodItem.id)
        )
        rows = list((await self.session.execute(stmt)).all())
        grouped: dict[uuid.UUID, dict[str, Any]] = {}
        for record, item in rows:
            entry = grouped.setdefault(
                record.id,
                {
                    "id": str(record.id),
                    "meal_slot": record.meal_slot,
                    "occurred_at": record.occurred_at.isoformat(),
                    "items": [],
                },
            )
            entry["items"].append(
                {
                    "id": str(item.id),
                    "detected_name": item.detected_name,
                    "grams": _dec(item.grams),
                    "ml": _dec(item.ml),
                    "quantity": _dec(item.quantity),
                    "unit": item.unit,
                    "kcal": _dec(item.kcal),
                    "protein_g": _dec(item.protein_g),
                    "carbs_g": _dec(item.carbs_g),
                    "fat_g": _dec(item.fat_g),
                    "fiber_g": _dec(item.fiber_g),
                    # Micros — usados pela expansão de /day (SP-152).
                    "sodium_mg": _dec(item.sodium_mg),
                    "calcium_mg": _dec(item.calcium_mg),
                    "iron_mg": _dec(item.iron_mg),
                    "potassium_mg": _dec(item.potassium_mg),
                    # Metadata útil pra badges + auditoria na página /day.
                    "confidence": _dec(item.confidence),
                    "has_catalog": item.catalog_ref_id is not None,
                    "is_estimate": item.is_estimate,
                    "needs_confirmation": item.needs_confirmation,
                    "source": item.source,
                }
            )
        return list(grouped.values())

    async def _load_water(self, day_log_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = (
            select(WaterRecord)
            .where(
                WaterRecord.day_log_id == day_log_id,
                WaterRecord.deleted_at.is_(None),
            )
            .order_by(WaterRecord.occurred_at)
        )
        return [
            {
                "id": str(r.id),
                "volume_ml": int(r.volume_ml),
                "occurred_at": r.occurred_at.isoformat(),
            }
            for r in (await self.session.execute(stmt)).scalars()
        ]

    async def _load_beverage(self, day_log_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = (
            select(BeverageRecord)
            .where(
                BeverageRecord.day_log_id == day_log_id,
                BeverageRecord.deleted_at.is_(None),
            )
            .order_by(BeverageRecord.occurred_at)
        )
        return [
            {
                "id": str(r.id),
                "detected_name": r.detected_name,
                "volume_ml": int(r.volume_ml),
                "kcal": _dec(r.kcal),
                "protein_g": _dec(r.protein_g),
                "carbs_g": _dec(r.carbs_g),
                "fat_g": _dec(r.fat_g),
                "needs_confirmation": r.needs_confirmation,
                "occurred_at": r.occurred_at.isoformat(),
            }
            for r in (await self.session.execute(stmt)).scalars()
        ]

    async def _load_activity(self, day_log_id: uuid.UUID) -> list[dict[str, Any]]:
        stmt = (
            select(ActivityRecord)
            .where(
                ActivityRecord.day_log_id == day_log_id,
                ActivityRecord.deleted_at.is_(None),
            )
            .order_by(ActivityRecord.occurred_at)
        )
        return [
            {
                "id": str(r.id),
                "detected_name": r.detected_name,
                "activity_type": r.activity_type,
                "duration_minutes": _dec(r.duration_minutes),
                "intensity": r.intensity,
                "kcal_burned": _dec(r.kcal_burned),
                "calc_method": r.calc_method,
                "occurred_at": r.occurred_at.isoformat(),
            }
            for r in (await self.session.execute(stmt)).scalars()
        ]


def _dec(value: Decimal | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _snapshot_to_totals(snapshot: DailySnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "kcal_in": 0.0,
            "kcal_out": 0.0,
            "kcal_balance": 0.0,
            "protein_g": 0.0,
            "carbs_g": 0.0,
            "fat_g": 0.0,
            "fiber_g": 0.0,
            "sodium_mg": 0.0,
            "calcium_mg": 0.0,
            "iron_mg": 0.0,
            "potassium_mg": 0.0,
            "water_ml": 0,
            "other_liquids_ml": 0,
        }
    return {
        "kcal_in": float(snapshot.kcal_in),
        "kcal_out": float(snapshot.kcal_out),
        "kcal_balance": float(snapshot.kcal_balance),
        "protein_g": float(snapshot.protein_g),
        "carbs_g": float(snapshot.carbs_g),
        "fat_g": float(snapshot.fat_g),
        "fiber_g": float(snapshot.fiber_g),
        "sodium_mg": float(snapshot.sodium_mg),
        "calcium_mg": float(snapshot.calcium_mg),
        "iron_mg": float(snapshot.iron_mg),
        "potassium_mg": float(snapshot.potassium_mg),
        "water_ml": int(snapshot.water_ml),
        "other_liquids_ml": int(snapshot.other_liquids_ml),
    }
