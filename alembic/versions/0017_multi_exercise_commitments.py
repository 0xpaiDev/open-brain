"""Multi-exercise commitments: add kind/import_hash columns, new exercise/log tables.

Additive only:
- commitment.exercise becomes nullable (existing rows keep their value)
- commitment.kind column added (nullable, server_default='single')
- commitment.import_hash column added (nullable, for plan idempotency)
- New table: commitment_exercises (per-exercise definitions)
- New table: commitment_exercise_logs (per-exercise log entries, soft-delete)

RLS enabled on all new tables (deny-all; app connects as postgres superuser).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extend commitments table (additive, no data rewrite) ─────────────────
    with op.batch_alter_table("commitments") as batch_op:
        batch_op.alter_column("exercise", nullable=True)
        batch_op.add_column(sa.Column("kind", sa.String(20), nullable=True, server_default="single"))
        batch_op.add_column(sa.Column("import_hash", sa.String(64), nullable=True))
        batch_op.create_index("ix_commitments_import_hash", ["import_hash"])

    # ── commitment_exercises ─────────────────────────────────────────────────
    op.create_table(
        "commitment_exercises",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(20), nullable=False, server_default="reps"),
        sa.Column("progression_metric", sa.String(20), nullable=False, server_default="reps"),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("commitment_id", "name", name="uq_commitment_exercise_name"),
    )
    op.create_index(
        "ix_commitment_exercises_commitment",
        "commitment_exercises",
        ["commitment_id"],
    )
    op.execute("ALTER TABLE commitment_exercises ENABLE ROW LEVEL SECURITY")

    # ── commitment_exercise_logs ─────────────────────────────────────────────
    op.create_table(
        "commitment_exercise_logs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("commitment_exercises.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("log_date", sa.Date(), nullable=False),
        sa.Column("sets", sa.Integer(), nullable=True),
        sa.Column("reps", sa.Integer(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_exercise_logs_commitment_exercise_date",
        "commitment_exercise_logs",
        ["commitment_id", "exercise_id", "log_date"],
    )
    op.create_index(
        "ix_exercise_logs_commitment_date",
        "commitment_exercise_logs",
        ["commitment_id", "log_date"],
    )
    op.execute("ALTER TABLE commitment_exercise_logs ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("commitment_exercise_logs")
    op.drop_table("commitment_exercises")

    with op.batch_alter_table("commitments") as batch_op:
        batch_op.drop_index("ix_commitments_import_hash")
        batch_op.drop_column("import_hash")
        batch_op.drop_column("kind")
        batch_op.alter_column("exercise", nullable=False)
