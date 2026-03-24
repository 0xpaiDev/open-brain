"""Add tables for Todo, DailyPulse, and RagConversation modules.

Creates four new tables:
  - todo_items: First-class todo items with priority/status/due_date
  - todo_history: Append-only audit log of todo state changes
  - daily_pulse: One-per-day morning check-in record
  - rag_conversations: Persisted Discord RAG chat conversation buffer
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create todo_items, todo_history, daily_pulse, rag_conversations tables."""
    op.create_table(
        "todo_items",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discord_message_id", sa.String(30), nullable=True),
        sa.Column("discord_channel_id", sa.String(30), nullable=True),
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
    )
    op.create_index("ix_todo_items_status_due_date", "todo_items", ["status", "due_date"])

    op.create_table(
        "todo_history",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "todo_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("todo_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("old_value", JSONB, nullable=True),
        sa.Column("new_value", JSONB, nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_todo_history_todo_id", "todo_history", ["todo_id"])

    op.create_table(
        "daily_pulse",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("pulse_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_reply", sa.Text, nullable=True),
        sa.Column("sleep_quality", sa.Integer, nullable=True),
        sa.Column("energy_level", sa.Integer, nullable=True),
        sa.Column("wake_time", sa.String(10), nullable=True),
        sa.Column("parsed_data", JSONB, nullable=True),
        sa.Column("ai_question", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="sent"),
        sa.Column("discord_message_id", sa.String(30), nullable=True),
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
        sa.UniqueConstraint("pulse_date", name="uq_daily_pulse_pulse_date"),
    )

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("discord_channel_id", sa.String(30), nullable=False),
        sa.Column("discord_user_id", sa.String(30), nullable=False),
        sa.Column("messages", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "model_name",
            sa.String(100),
            nullable=False,
            server_default="claude-haiku-4-5-20251001",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "discord_channel_id", "discord_user_id", name="uq_rag_conv_channel_user"
        ),
    )


def downgrade() -> None:
    """Drop all four module tables in reverse dependency order."""
    op.drop_table("rag_conversations")
    op.drop_table("daily_pulse")
    op.drop_index("ix_todo_history_todo_id", table_name="todo_history")
    op.drop_table("todo_history")
    op.drop_index("ix_todo_items_status_due_date", table_name="todo_items")
    op.drop_table("todo_items")
