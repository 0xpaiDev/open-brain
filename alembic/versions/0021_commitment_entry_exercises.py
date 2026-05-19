"""Add commitment_entry_exercises junction table.

Table already exists in Supabase (created manually).
This migration ensures fresh SQLite test DBs and future environments get it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "commitment_entry_exercises",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("commitment_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("entry_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("exercise_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(datetime('now'))"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["commitment_id"], ["commitments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entry_id"], ["commitment_entries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["exercise_id"], ["commitment_exercises.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("entry_id", "exercise_id", name="uq_entry_exercise"),
    )
    op.create_index(
        "ix_entry_exercises_commitment_entry",
        "commitment_entry_exercises",
        ["commitment_id", "entry_id"],
    )
    try:
        op.execute("ALTER TABLE commitment_entry_exercises ENABLE ROW LEVEL SECURITY")
    except Exception:
        pass  # SQLite ignores RLS


def downgrade() -> None:
    op.drop_index("ix_entry_exercises_commitment_entry", table_name="commitment_entry_exercises")
    op.drop_table("commitment_entry_exercises")
