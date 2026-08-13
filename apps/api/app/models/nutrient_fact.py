import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin

CATALOG_SOURCES = ("TBCA_2023", "USDA_FDC", "manual", "label_ocr")


class NutrientFact(UUIDPrimaryKeyMixin, Base):
    """Catálogo nutricional. Referenciado por food_items.catalog_ref_id.

    `basis` decide se os campos por 100 são por peso (`per_100g`) ou por
    volume (`per_100ml`). NutritionCalculator escala pelas gramas/ml do item.
    """

    __tablename__ = "nutrient_facts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('TBCA_2023','USDA_FDC','manual','label_ocr')",
            name="ck_nutrient_facts_source",
        ),
        CheckConstraint(
            "basis IN ('per_100g','per_100ml')",
            name="ck_nutrient_facts_basis",
        ),
    )

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    serving_grams: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    kcal: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    protein_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    carbs_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fat_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    fiber_g: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    sodium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    calcium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    iron_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    potassium_mg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    barcode: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_media_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media.id", ondelete="SET NULL"),
        nullable=True,
    )
    verified_by_user: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # SP-141: cadastro manual grava aqui. Facts do seed TBCA e label_ocr
    # ficam com NULL (catálogo canônico não tem dono).
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
