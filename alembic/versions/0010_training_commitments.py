"""Add training & commitments tables, extend daily_pulse and memory_items.

New tables: commitments, commitment_entries, strava_activities
New columns: daily_pulse.clean_meal, daily_pulse.alcohol,
             memory_items.tags (JSONB with GIN index)
RLS enabled on all new tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_TABLES = ["commitments", "commitment_entries", "strava_activities"]


def upgrade() -> None:
    # ── commitments ───────────────────────────────────────────────────────
    op.create_table(
        "commitments",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("exercise", sa.String(100), nullable=False),
        sa.Column("daily_target", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(20), server_default="reps", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── commitment_entries ────────────────────────────────────────────────
    op.create_table(
        "commitment_entries",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "commitment_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("commitments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("logged_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint(
        "uq_commitment_entry_date", "commitment_entries", ["commitment_id", "entry_date"]
    )
    op.create_index(
        "ix_commitment_entries_commitment_date",
        "commitment_entries",
        ["commitment_id", "entry_date"],
    )

    # ── strava_activities ─────────────────────────────────────────────────
    op.create_table(
        "strava_activities",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("strava_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("activity_type", sa.String(50), nullable=True),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("tss", sa.Float(), nullable=True),
        sa.Column("avg_power_w", sa.Float(), nullable=True),
        sa.Column("avg_hr", sa.Integer(), nullable=True),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Extend daily_pulse ────────────────────────────────────────────────
    op.add_column("daily_pulse", sa.Column("clean_meal", sa.Boolean(), nullable=True))
    op.add_column("daily_pulse", sa.Column("alcohol", sa.Boolean(), nullable=True))

    # ── Extend memory_items with tags ─────────────────────────────────────
    op.add_column(
        "memory_items",
        sa.Column("tags", sa.JSON(), nullable=True, server_default="[]"),
    )
    # GIN index for PostgreSQL @> (contains) queries on tags
    op.execute(
        "CREATE INDEX ix_memory_items_tags ON memory_items USING GIN (tags) "
        "WHERE tags IS NOT NULL"
    )

    # ── Enable RLS on new tables ──────────────────────────────────────────
    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Drop GIN index
    op.execute("DROP INDEX IF EXISTS ix_memory_items_tags")

    # Drop tags column
    op.drop_column("memory_items", "tags")

    # Drop nutrition columns
    op.drop_column("daily_pulse", "alcohol")
    op.drop_column("daily_pulse", "clean_meal")

    # Drop new tables (FK order)
    op.drop_table("strava_activities")
    op.drop_table("commitment_entries")
    op.drop_table("commitments")
