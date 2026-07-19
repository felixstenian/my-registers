"""Schemas de resposta para `/weekly` (SP-110..113)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WeeklyReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    window_start: date | None
    window_end: date | None
    days_included: int
    totals: dict[str, Any] = Field(default_factory=dict)
    averages: dict[str, Any] = Field(default_factory=dict)
    per_day: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    narrative: str | None = None
    generated_at: datetime
    version: int
