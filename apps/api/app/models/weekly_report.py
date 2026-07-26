import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WeeklyReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Relatório semanal (Fase 8 / SP-110..113).

    Const. §30 e INV-8: só dias com `status='closed'` entram na agregação.
    Idempotência via UNIQUE(user_id, window_start, window_end) — se os
    snapshots participantes não mudaram (comparação por `snapshot_versions`),
    a mesma linha é retornada sem regerar `narrative`.
    """

    __tablename__ = "weekly_reports"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "window_start",
            "window_end",
            name="uq_weekly_reports_user_window",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    window_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    window_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    days_included: Mapped[int] = mapped_column(Integer, nullable=False)
    totals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    averages: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    per_day: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    warnings: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    # Assinatura das versões dos snapshots consumidos — usado para decidir se
    # o report ficou stale (SP-112 idempotência: se snapshots não mudaram,
    # não regeneramos narrative nem incrementamos version).
    snapshot_versions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
