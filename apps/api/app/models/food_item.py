import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

FOOD_ITEM_SOURCES = ("manual", "llm", "user_corrected", "catalog")


class FoodItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Um item consumido dentro de uma refeição (food_records).

    Macros/micros são MATERIALIZADOS aqui (cache). Toda mutação chama de
    novo o NutritionCalculator; DailyRecomputeService lê apenas de itens
    vivos (deleted_at IS NULL). Const. Art. III §10.
    """

    __tablename__ = "food_items"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual','llm','user_corrected','catalog')",
            name="ck_food_items_source",
        ),
    )

    food_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("food_records.id", ondelete="CASCADE"),
        nullable=False,
    )
    detected_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    ml: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    is_estimate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
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
    potassium_mg: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
