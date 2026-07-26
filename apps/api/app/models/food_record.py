import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

MEAL_SLOTS = ("breakfast", "lunch", "snack", "dinner", "other", "unspecified")


class FoodRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "food_records"
    __table_args__ = (
        CheckConstraint(
            "meal_slot IN ('breakfast','lunch','snack','dinner','other','unspecified')",
            name="ck_food_records_meal_slot",
        ),
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
    meal_slot: Mapped[str] = mapped_column(Text, nullable=False, server_default="unspecified")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
