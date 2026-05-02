"""Add learning_materials table: per-topic source material storage.

One-to-one with learning_topics (unique constraint on topic_id).
Stores markdown content + optional provenance metadata.

RLS enabled (deny-all, app connects as superuser).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_materials",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("source_title", sa.String(length=240), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"], ["learning_topics.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("topic_id", name="uq_learning_materials_topic_id"),
    )
    op.create_index(
        "ix_learning_materials_topic_id",
        "learning_materials",
        ["topic_id"],
    )
    op.execute("ALTER TABLE learning_materials ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_learning_materials_topic_id", table_name="learning_materials")
    op.drop_table("learning_materials")
