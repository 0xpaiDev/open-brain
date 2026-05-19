"""Add global exercise library table and FK on commitment_exercises.

Creates:
- exercises table (id, name normalised, display_name, created_at) with RLS
- commitment_exercises.exercise_id nullable FK to exercises.id (SET NULL on delete)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exercises",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_exercise_name"),
    )
    op.create_index("ix_exercises_name", "exercises", ["name"])

    # RLS — deny all by default (same pattern as migrations 0009/0010)
    op.execute("ALTER TABLE exercises ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "commitment_exercises",
        sa.Column("exercise_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_commitment_exercises_exercise_id",
        "commitment_exercises",
        "exercises",
        ["exercise_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_commitment_exercises_exercise", "commitment_exercises", ["exercise_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_commitment_exercises_exercise", table_name="commitment_exercises")
    op.drop_constraint(
        "fk_commitment_exercises_exercise_id", "commitment_exercises", type_="foreignkey"
    )
    op.drop_column("commitment_exercises", "exercise_id")
    op.drop_index("ix_exercises_name", table_name="exercises")
    op.drop_table("exercises")
