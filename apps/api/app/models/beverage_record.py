import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class BeverageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bebidas com calorias (café, leite, suco, refrigerante, chá adoçado,
    álcool). Const. Art. IV §13: contribui para `other_liquids_ml`, `kcal_in`,
    macros e micros. **NUNCA** para `water_ml`. Macros/micros materializados
    igual a `food_items` — recalculados via `NutritionCalculator` a cada
    correção.
    """

    __tablename__ = "beverage_records"
    __table_args__ = (
        CheckConstraint("volume_ml > 0", name="ck_beverage_records_volume_positive"),
        CheckConstraint(
            "source IN ('manual','llm','user_corrected','catalog')",
            name="ck_beverage_records_source",
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
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    detected_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    volume_ml: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    is_estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    needs_confirmation: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    catalog_ref_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nutrient_facts.id", ondelete="SET NULL"),
        nullable=True,
    )
    kcal: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    calcium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    iron_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    potassium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
