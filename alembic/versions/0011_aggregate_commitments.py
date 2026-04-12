"""Add aggregate commitment support.

New columns on commitments: cadence, targets (JSONB), progress (JSONB)
New table: commitment_activities (junction for dedup/audit)
RLS enabled on new table.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extend commitments table ─────────────────────────────────────────
    op.add_column(
        "commitments",
        sa.Column("cadence", sa.String(20), server_default="daily", nullable=False),
    )
    # Use JSONB for PostgreSQL (raw SQL for explicit type)
    op.execute("ALTER TABLE commitments ADD COLUMN targets JSONB")
    op.execute("ALTER TABLE commitments ADD COLUMN progress JSONB")

    # ── commitment_activities junction table ──────────────────────────────
    op.create_table(
        "commitment_activities",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "strava_activity_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("strava_activities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_commitment_activity",
        "commitment_activities",
        ["commitment_id", "strava_activity_id"],
    )
    op.create_index(
        "ix_commitment_activities_commitment",
        "commitment_activities",
        ["commitment_id"],
    )
    op.create_index(
        "ix_commitment_activities_strava",
        "commitment_activities",
        ["strava_activity_id"],
    )

    # ── Enable RLS on new table ──────────────────────────────────────────
    op.execute("ALTER TABLE commitment_activities ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("commitment_activities")
    op.drop_column("commitments", "progress")
    op.drop_column("commitments", "targets")
    op.drop_column("commitments", "cadence")
