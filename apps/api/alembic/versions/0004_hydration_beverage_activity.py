"""water_records, beverage_records, activity_records

Revision ID: 0004_hydration_beverage_activity
Revises: 0003_food_catalog
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_hydration_beverage_activity"
down_revision: str | None = "0003_food_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # water_records — Const. Art. IV §12: sem kcal/macros por estrutura
    # ------------------------------------------------------------------
    op.create_table(
        "water_records",
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
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column(
            "is_estimate",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
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
            "volume_ml > 0", name="ck_water_records_volume_positive"
        ),
        sa.CheckConstraint(
            "source IN ('manual','llm','user_corrected')",
            name="ck_water_records_source",
        ),
    )
    op.create_index(
        "ix_water_records_user_day",
        "water_records",
        ["user_id", "day_log_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_water_records_updated_at BEFORE UPDATE ON water_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # beverage_records — Const. Art. IV §13: com macros/micros
    # ------------------------------------------------------------------
    op.create_table(
        "beverage_records",
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
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("brand", sa.Text(), nullable=True),
        sa.Column("volume_ml", sa.Integer(), nullable=False),
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
            "volume_ml > 0", name="ck_beverage_records_volume_positive"
        ),
        sa.CheckConstraint(
            "source IN ('manual','llm','user_corrected','catalog')",
            name="ck_beverage_records_source",
        ),
    )
    op.create_index(
        "ix_beverage_records_user_day",
        "beverage_records",
        ["user_id", "day_log_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_beverage_records_updated_at BEFORE UPDATE ON beverage_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # activity_records — SP-60..64: kcal_burned deterministicamente
    # ------------------------------------------------------------------
    op.create_table(
        "activity_records",
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
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("activity_type", sa.Text(), nullable=False),
        sa.Column("duration_minutes", sa.Numeric(6, 2), nullable=False),
        sa.Column("distance_km", sa.Numeric(6, 3), nullable=True),
        sa.Column(
            "intensity", sa.Text(), nullable=False, server_default="unknown"
        ),
        sa.Column("met_value", sa.Numeric(4, 2), nullable=True),
        sa.Column(
            "kcal_burned", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
        sa.Column("calc_method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
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
            "intensity IN ('light','moderate','vigorous','unknown')",
            name="ck_activity_records_intensity",
        ),
        sa.CheckConstraint(
            "calc_method IN ('mets_body_weight','llm_estimate','user_manual')",
            name="ck_activity_records_calc_method",
        ),
        sa.CheckConstraint(
            "duration_minutes > 0",
            name="ck_activity_records_duration_positive",
        ),
    )
    op.create_index(
        "ix_activity_records_user_day",
        "activity_records",
        ["user_id", "day_log_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.execute(
        "CREATE TRIGGER trg_activity_records_updated_at BEFORE UPDATE ON activity_records "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_activity_records_updated_at ON activity_records")
    op.drop_index("ix_activity_records_user_day", table_name="activity_records")
    op.drop_table("activity_records")
    op.execute("DROP TRIGGER IF EXISTS trg_beverage_records_updated_at ON beverage_records")
    op.drop_index("ix_beverage_records_user_day", table_name="beverage_records")
    op.drop_table("beverage_records")
    op.execute("DROP TRIGGER IF EXISTS trg_water_records_updated_at ON water_records")
    op.drop_index("ix_water_records_user_day", table_name="water_records")
    op.drop_table("water_records")
