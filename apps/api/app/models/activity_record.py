import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

INTENSITY_VALUES = ("light", "moderate", "vigorous", "unknown")
CALC_METHOD_VALUES = ("mets_body_weight", "llm_estimate", "user_manual", "workout_session")


class ActivityRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """SP-60..64. `kcal_burned` calculado no backend por MET × weight_kg ×
    (duration_minutes / 60). `met_value` e `calc_method` gravados para
    recomputo futuro (Const. Art. III §10 — recompute from-scratch).
    """

    __tablename__ = "activity_records"
    __table_args__ = (
        CheckConstraint(
            "intensity IN ('light','moderate','vigorous','unknown')",
            name="ck_activity_records_intensity",
        ),
        CheckConstraint(
            "calc_method IN ('mets_body_weight','llm_estimate','user_manual','workout_session')",
            name="ck_activity_records_calc_method",
        ),
        CheckConstraint("duration_minutes > 0", name="ck_activity_records_duration_positive"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    day_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("day_logs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    duration_minutes: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    distance_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 3), nullable=True)
    intensity: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    met_value: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)
    kcal_burned: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    calc_method: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    workout_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
