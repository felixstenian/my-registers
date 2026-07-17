"""DailyRecomputeService — Const. Art. III §10 / INV-4.

Snapshot **sempre** from-scratch: `SELECT SUM(...) FROM food_items WHERE
day_log_id=? AND deleted_at IS NULL`. Nunca aplica delta em cima do
snapshot anterior. Cada recompute incrementa `version`.

Fase 4 agrega apenas `food_items`. Fase 5 estende para `water_records`,
`beverage_records`, `activity_records`.
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

from app.models import DailySnapshot, DayLog, FoodItem, FoodRecord

_ZERO = Decimal("0")

_TOTALS_FIELDS = (
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
        # Confirma que o day_log existe e pega user_id.
        day_log = await self.session.get(DayLog, day_log_id)
        if day_log is None:
            raise ValueError(f"day_log {day_log_id} not found")

        totals, warnings = await self._aggregate_food(day_log_id)

        payload = dict(
            user_id=day_log.user_id,
            day_log_id=day_log_id,
            kcal_in=totals["kcal"],
            kcal_out=_ZERO,
            kcal_balance=totals["kcal"],  # kcal_in - kcal_out; sem atividade ainda
            protein_g=totals["protein_g"],
            carbs_g=totals["carbs_g"],
            fat_g=totals["fat_g"],
            fiber_g=totals["fiber_g"],
            sodium_mg=totals["sodium_mg"],
            calcium_mg=totals["calcium_mg"],
            iron_mg=totals["iron_mg"],
            potassium_mg=totals["potassium_mg"],
            water_ml=0,
            other_liquids_ml=0,
            computed_at=datetime.now(UTC),
            warnings=warnings,
        )

        # Upsert por UNIQUE(day_log_id). Em conflito, incrementa version.
        # `populate_existing=True` força SQLAlchemy a atualizar o objeto no
        # identity map com os valores do RETURNING (senão a 2ª recompute do
        # mesmo day devolve o snapshot cacheado da 1ª chamada — kcal/version
        # stale).
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
            for field in _TOTALS_FIELDS
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
            field: Decimal(value or 0) for field, value in zip(_TOTALS_FIELDS, row, strict=True)
        }

        # Warnings agregam itens que precisam de atenção.
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
                        "item_id": str(item_id),
                        "detected_name": detected_name,
                    }
                )
            if needs_confirmation:
                warnings.append(
                    {
                        "code": "needs_confirmation",
                        "item_id": str(item_id),
                        "detected_name": detected_name,
                    }
                )

        return totals, warnings
