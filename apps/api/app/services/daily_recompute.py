"""DailyRecomputeService — Const. Art. III §10 / INV-4.

Snapshot **sempre** from-scratch: SUMs sobre as tabelas cruas com
`deleted_at IS NULL`. Nunca aplica delta em cima do snapshot anterior.
Cada recompute incrementa `version`.

Fase 4 agregava só `food_items`. Fase 5 estende para `water_records`,
`beverage_records` (contribui para kcal_in + macros + other_liquids_ml)
e `activity_records` (contribui para kcal_out). Const. Art. IV §12-14:
água e bebida calórica ficam em tabelas distintas — impossível dupla
contagem por engano (INV-2, INV-3).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ActivityRecord,
    BeverageRecord,
    DailySnapshot,
    DayLog,
    FoodItem,
    FoodRecord,
    WaterRecord,
)

_ZERO = Decimal("0")

_MACRO_FIELDS = (
    "kcal",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sodium_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
)


@dataclass(slots=True)
class RecomputeResult:
    snapshot: DailySnapshot
    warnings: list[dict[str, Any]]


class DailyRecomputeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def recompute(
        self, day_log_id: uuid.UUID
    ) -> RecomputeResult:
        day_log = await self.session.get(DayLog, day_log_id)
        if day_log is None:
            raise ValueError(f"day_log {day_log_id} not found")

        food_totals, food_warnings = await self._aggregate_food(day_log_id)
        bev_totals, bev_warnings = await self._aggregate_beverage(day_log_id)
        water_ml = await self._aggregate_water(day_log_id)
        kcal_out, act_warnings = await self._aggregate_activity(day_log_id)

        # kcal_in = alimentos + bebidas calóricas. Const. Art. IV §13.
        kcal_in = food_totals["kcal"] + bev_totals["kcal"]
        # Macros/micros: somam alimentos + bebidas calóricas.
        combined = {
            field: food_totals[field] + bev_totals[field]
            for field in _MACRO_FIELDS
            if field != "kcal"
        }

        warnings = [*food_warnings, *bev_warnings, *act_warnings]

        payload = dict(
            user_id=day_log.user_id,
            day_log_id=day_log_id,
            kcal_in=kcal_in,
            kcal_out=kcal_out,
            kcal_balance=kcal_in - kcal_out,
            protein_g=combined["protein_g"],
            carbs_g=combined["carbs_g"],
            fat_g=combined["fat_g"],
            fiber_g=combined["fiber_g"],
            sodium_mg=combined["sodium_mg"],
            calcium_mg=combined["calcium_mg"],
            iron_mg=combined["iron_mg"],
            potassium_mg=combined["potassium_mg"],
            water_ml=water_ml,
            other_liquids_ml=bev_totals["volume_ml"],
            computed_at=datetime.now(UTC),
            warnings=warnings,
        )

        # Upsert por UNIQUE(day_log_id). `populate_existing=True` no
        # RETURNING evita snapshot cacheado no identity map (visto na Fase 4).
        stmt = (
            pg_insert(DailySnapshot)
            .values(**payload)
            .on_conflict_do_update(
                index_elements=["day_log_id"],
                set_={
                    **{k: v for k, v in payload.items() if k != "day_log_id"},
                    "version": DailySnapshot.__table__.c.version + 1,
                },
            )
            .returning(DailySnapshot)
            .execution_options(populate_existing=True)
        )
        result = await self.session.execute(stmt)
        snapshot = result.scalar_one()
        await self.session.flush()
        return RecomputeResult(snapshot=snapshot, warnings=warnings)

    async def _aggregate_food(
        self, day_log_id: uuid.UUID
    ) -> tuple[dict[str, Decimal], list[dict[str, Any]]]:
        sum_cols = [
            func.coalesce(func.sum(getattr(FoodItem, field)), 0).label(field)
            for field in _MACRO_FIELDS
        ]
        stmt = (
            select(*sum_cols)
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
            )
        )
        row = (await self.session.execute(stmt)).one()
        totals = {
            field: Decimal(value or 0)
            for field, value in zip(_MACRO_FIELDS, row, strict=True)
        }

        stmt_warnings = (
            select(
                FoodItem.id,
                FoodItem.detected_name,
                FoodItem.catalog_ref_id,
                FoodItem.needs_confirmation,
            )
            .join(FoodRecord, FoodRecord.id == FoodItem.food_record_id)
            .where(
                FoodRecord.day_log_id == day_log_id,
                FoodRecord.deleted_at.is_(None),
                FoodItem.deleted_at.is_(None),
            )
        )
        warnings: list[dict[str, Any]] = []
        for item_id, detected_name, catalog_ref_id, needs_confirmation in (
            await self.session.execute(stmt_warnings)
        ).all():
            if catalog_ref_id is None:
                warnings.append(
                    {
                        "code": "no_catalog_hit",
                        "entity": "food_item",
                        "item_id": str(item_id),
                        "detected_name": detected_name,
                    }
                )
            if needs_confirmation:
                warnings.append(
                    {
                        "code": "needs_confirmation",
                        "entity": "food_item",
                        "item_id": str(item_id),
                        "detected_name": detected_name,
                    }
                )
        return totals, warnings

    async def _aggregate_beverage(
        self, day_log_id: uuid.UUID
    ) -> tuple[dict[str, Decimal], list[dict[str, Any]]]:
        sum_cols = [
            func.coalesce(func.sum(getattr(BeverageRecord, field)), 0).label(field)
            for field in _MACRO_FIELDS
        ]
        vol_col = func.coalesce(func.sum(BeverageRecord.volume_ml), 0).label(
            "volume_ml"
        )
        stmt = select(*sum_cols, vol_col).where(
            BeverageRecord.day_log_id == day_log_id,
            BeverageRecord.deleted_at.is_(None),
        )
        row = (await self.session.execute(stmt)).one()
        totals: dict[str, Decimal] = {}
        for field, value in zip(
            (*_MACRO_FIELDS, "volume_ml"), row, strict=True
        ):
            totals[field] = (
                int(value or 0) if field == "volume_ml" else Decimal(value or 0)
            )

        stmt_warnings = select(
            BeverageRecord.id,
            BeverageRecord.detected_name,
            BeverageRecord.catalog_ref_id,
            BeverageRecord.needs_confirmation,
        ).where(
            BeverageRecord.day_log_id == day_log_id,
            BeverageRecord.deleted_at.is_(None),
        )
        warnings: list[dict[str, Any]] = []
        for record_id, detected_name, catalog_ref_id, needs_confirmation in (
            await self.session.execute(stmt_warnings)
        ).all():
            if catalog_ref_id is None:
                warnings.append(
                    {
                        "code": "no_catalog_hit",
                        "entity": "beverage_record",
                        "record_id": str(record_id),
                        "detected_name": detected_name,
                    }
                )
            if needs_confirmation:
                warnings.append(
                    {
                        "code": "needs_confirmation",
                        "entity": "beverage_record",
                        "record_id": str(record_id),
                        "detected_name": detected_name,
                    }
                )
        return totals, warnings

    async def _aggregate_water(self, day_log_id: uuid.UUID) -> int:
        stmt = select(
            func.coalesce(func.sum(WaterRecord.volume_ml), 0)
        ).where(
            WaterRecord.day_log_id == day_log_id,
            WaterRecord.deleted_at.is_(None),
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def _aggregate_activity(
        self, day_log_id: uuid.UUID
    ) -> tuple[Decimal, list[dict[str, Any]]]:
        stmt = select(
            func.coalesce(func.sum(ActivityRecord.kcal_burned), 0)
        ).where(
            ActivityRecord.day_log_id == day_log_id,
            ActivityRecord.deleted_at.is_(None),
        )
        kcal_out = Decimal((await self.session.execute(stmt)).scalar_one() or 0)

        stmt_warnings = select(
            ActivityRecord.id,
            ActivityRecord.detected_name,
            ActivityRecord.calc_method,
            ActivityRecord.met_value,
        ).where(
            ActivityRecord.day_log_id == day_log_id,
            ActivityRecord.deleted_at.is_(None),
        )
        warnings: list[dict[str, Any]] = []
        for record_id, detected_name, calc_method, met_value in (
            await self.session.execute(stmt_warnings)
        ).all():
            if calc_method != "mets_body_weight" or met_value is None:
                warnings.append(
                    {
                        "code": "activity_estimated",
                        "entity": "activity_record",
                        "record_id": str(record_id),
                        "detected_name": detected_name,
                    }
                )
        return kcal_out, warnings
