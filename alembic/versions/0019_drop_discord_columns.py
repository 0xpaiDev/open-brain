"""Drop Discord-specific columns and rag_conversations table.

Discord integration has been removed. This migration:
- Drops rag_conversations table (Discord-only conversation state)
- Drops discord_message_id and discord_channel_id from todo_items
- Drops discord_message_id from daily_pulse
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("rag_conversations")

    with op.batch_alter_table("todo_items") as batch_op:
        batch_op.drop_column("discord_message_id")
        batch_op.drop_column("discord_channel_id")

    with op.batch_alter_table("daily_pulse") as batch_op:
        batch_op.drop_column("discord_message_id")


def downgrade() -> None:
    with op.batch_alter_table("daily_pulse") as batch_op:
        batch_op.add_column(sa.Column("discord_message_id", sa.String(30), nullable=True))

    with op.batch_alter_table("todo_items") as batch_op:
        batch_op.add_column(sa.Column("discord_message_id", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("discord_channel_id", sa.String(30), nullable=True))

    op.create_table(
        "rag_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("discord_channel_id", sa.String(30), nullable=False),
        sa.Column("discord_user_id", sa.String(30), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("discord_channel_id", "discord_user_id", name="uq_rag_conv_channel_user"),
    )
