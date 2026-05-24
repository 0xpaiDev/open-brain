"""add chat_logs table

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | Sequence[str] | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_logs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("tools_enabled", sa.Boolean(), nullable=False),
        sa.Column("intent_tool", sa.String(64), nullable=True),
        sa.Column("intent_method", sa.String(16), nullable=True),
        sa.Column("llm_calls", postgresql.JSONB(), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.execute("ALTER TABLE chat_logs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("chat_logs")
