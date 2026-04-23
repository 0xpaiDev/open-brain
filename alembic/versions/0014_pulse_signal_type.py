"""Add signal_type column to daily_pulse for signal-driven generation.

Phase 1 of the signal-driven morning pulse: each generated pulse records which
detector fired (focus / opportunity / open / NULL = legacy or silent). Column is
nullable and has no CHECK constraint so the enum can evolve in Phase 2 without
another migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_pulse",
        sa.Column("signal_type", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_pulse", "signal_type")
