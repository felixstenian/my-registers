"""food/catalog/snapshot/audit tables

Revision ID: 0003_food_catalog
Revises: 0002_chat_and_media
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_food_catalog"
down_revision: str | None = "0002_chat_and_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # nutrient_facts (catálogo)
    # ------------------------------------------------------------------
    op.create_table(
        "nutrient_facts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("serving_grams", sa.Numeric(10, 2), nullable=True),
        sa.Column("kcal", sa.Numeric(10, 2), nullable=True),
        sa.Column("protein_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("carbs_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("fat_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("fiber_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("sodium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("calcium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("iron_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("potassium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("basis", sa.Text(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column(
            "label_media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "verified_by_user",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IN ('TBCA_2023','USDA_FDC','manual','label_ocr')",
            name="ck_nutrient_facts_source",
        ),
        sa.CheckConstraint(
            "basis IN ('per_100g','per_100ml')", name="ck_nutrient_facts_basis"
        ),
    )
    op.create_index(
        "ix_nutrient_facts_aliases_gin",
        "nutrient_facts",
        ["aliases"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_nutrient_facts_canonical_name",
        "nutrient_facts",
        ["canonical_name"],
    )
    op.create_index(
        "ix_nutrient_facts_barcode",
        "nutrient_facts",
        ["barcode"],
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )

    # ------------------------------------------------------------------
    # food_records
    # ------------------------------------------------------------------
    op.create_table(
        "food_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "day_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("day_logs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "meal_slot",
            sa.Text(),
            nullable=False,
            server_default="unspecified",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "meal_slot IN ('breakfast','lunch','snack','dinner','other','unspecified')",
            name="ck_food_records_meal_slot",
        ),
    )
    op.create_index(
        "ix_food_records_user_day",
        "food_records",
        ["user_id", "day_log_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_food_records_user_occurred",
        "food_records",
        ["user_id", "occurred_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_food_records_updated_at BEFORE UPDATE ON food_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # food_items
    # ------------------------------------------------------------------
    op.create_table(
        "food_items",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "food_record_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("food_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("detected_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(10, 3), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("grams", sa.Numeric(10, 3), nullable=True),
        sa.Column("ml", sa.Numeric(10, 3), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "is_estimate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "needs_confirmation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "catalog_ref_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("nutrient_facts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kcal", sa.Numeric(10, 2), nullable=True),
        sa.Column("protein_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("carbs_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("fat_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("fiber_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("sodium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("calcium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("iron_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("potassium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "source IN ('manual','llm','user_corrected','catalog')",
            name="ck_food_items_source",
        ),
    )
    op.create_index(
        "ix_food_items_record", "food_items", ["food_record_id"]
    )
    op.create_index(
        "ix_food_items_normalized_name", "food_items", ["normalized_name"]
    )
    op.execute(
        "CREATE TRIGGER trg_food_items_updated_at BEFORE UPDATE ON food_items "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # daily_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        "daily_snapshots",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "day_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("day_logs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kcal_in", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("kcal_out", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "kcal_balance", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("protein_g", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("carbs_g", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("fat_g", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("fiber_g", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("sodium_mg", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("calcium_mg", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("iron_mg", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column(
            "potassium_mg", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("water_ml", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "other_liquids_ml", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "warnings", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    # ------------------------------------------------------------------
    # audit_events
    # ------------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "action IN ('create','update','delete','correct')",
            name="ck_audit_events_action",
        ),
        sa.CheckConstraint(
            "actor IN ('user','llm')", name="ck_audit_events_actor"
        ),
    )
    op.create_index(
        "ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"]
    )
    op.create_index(
        "ix_audit_events_user_created",
        "audit_events",
        ["user_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_created", table_name="audit_events")
    op.drop_index("ix_audit_events_entity", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("daily_snapshots")
    op.execute("DROP TRIGGER IF EXISTS trg_food_items_updated_at ON food_items")
    op.drop_index("ix_food_items_normalized_name", table_name="food_items")
    op.drop_index("ix_food_items_record", table_name="food_items")
    op.drop_table("food_items")
    op.execute("DROP TRIGGER IF EXISTS trg_food_records_updated_at ON food_records")
    op.drop_index("ix_food_records_user_occurred", table_name="food_records")
    op.drop_index("ix_food_records_user_day", table_name="food_records")
    op.drop_table("food_records")
    op.drop_index("ix_nutrient_facts_barcode", table_name="nutrient_facts")
    op.drop_index(
        "ix_nutrient_facts_canonical_name", table_name="nutrient_facts"
    )
    op.drop_index("ix_nutrient_facts_aliases_gin", table_name="nutrient_facts")
    op.drop_table("nutrient_facts")
