"""Schemas de resposta para `/days/*` (SP-90 a SP-104)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DayTotalsOut(BaseModel):
    kcal_in: float
    kcal_out: float
    kcal_balance: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    sodium_mg: float
    calcium_mg: float
    iron_mg: float
    potassium_mg: float
    water_ml: int
    other_liquids_ml: int


class DayRecordsOut(BaseModel):
    food: list[dict[str, Any]] = Field(default_factory=list)
    water: list[dict[str, Any]] = Field(default_factory=list)
    beverage: list[dict[str, Any]] = Field(default_factory=list)
    activity: list[dict[str, Any]] = Field(default_factory=list)


class DaySnapshotOut(BaseModel):
    date: date
    status: Literal["open", "closed"]
    closed_at: datetime | None
    totals: DayTotalsOut
    records: DayRecordsOut
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    narrative: str | None = None
    snapshot_version: int


class DayCloseOut(DaySnapshotOut):
    """Idempotente. `was_already_closed=True` sinaliza SP-101 no cliente."""

    was_already_closed: bool
