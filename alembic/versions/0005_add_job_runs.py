"""Add job_runs table for cron job monitoring.

Tracks execution of scheduled jobs (pulse, importance, synthesis)
with start/finish times, status, and error messages.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create job_runs table with index on (job_name, started_at DESC)."""
    op.create_table(
        "job_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_name", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_job_runs_name_started",
        "job_runs",
        ["job_name", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    """Drop job_runs table."""
    op.drop_index("ix_job_runs_name_started", table_name="job_runs")
    op.drop_table("job_runs")
