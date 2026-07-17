"""day_logs, messages, media, message_media

Revision ID: 0002_chat_and_media
Revises: 0001_users_refresh
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_chat_and_media"
down_revision: str | None = "0001_users_refresh"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # day_logs
    # ------------------------------------------------------------------
    op.create_table(
        "day_logs",
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
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.UniqueConstraint("user_id", "log_date", name="uq_day_logs_user_date"),
        sa.CheckConstraint("status IN ('open','closed')", name="ck_day_logs_status"),
    )
    op.create_index(
        "ix_day_logs_user_status", "day_logs", ["user_id", "status"]
    )
    op.execute(
        "CREATE TRIGGER trg_day_logs_updated_at BEFORE UPDATE ON day_logs "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # ------------------------------------------------------------------
    # media
    # ------------------------------------------------------------------
    op.create_table(
        "media",
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
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("checksum_sha256", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="uploaded"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('uploaded','failed')", name="ck_media_status"
        ),
    )
    op.create_index(
        "ix_media_user_created", "media", ["user_id", sa.text("created_at DESC")]
    )

    # ------------------------------------------------------------------
    # messages
    # ------------------------------------------------------------------
    op.create_table(
        "messages",
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
            sa.ForeignKey("day_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("llm_intent", sa.Text(), nullable=True),
        sa.Column("llm_model", sa.Text(), nullable=True),
        sa.Column("llm_prompt_version", sa.Text(), nullable=True),
        sa.Column("llm_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("raw_llm_response", postgresql.JSONB(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=True),
        sa.Column("tokens_output", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role IN ('user','assistant','system')", name="ck_messages_role"
        ),
    )
    op.create_index(
        "ix_messages_user_created",
        "messages",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_messages_raw_llm_response",
        "messages",
        ["raw_llm_response"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------
    # message_media
    # ------------------------------------------------------------------
    op.create_table(
        "message_media",
        sa.Column(
            "message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "media_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("media.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("message_media")
    op.drop_index("ix_messages_raw_llm_response", table_name="messages")
    op.drop_index("ix_messages_user_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_media_user_created", table_name="media")
    op.drop_table("media")
    op.execute("DROP TRIGGER IF EXISTS trg_day_logs_updated_at ON day_logs")
    op.drop_index("ix_day_logs_user_status", table_name="day_logs")
    op.drop_table("day_logs")
