"""drop notes column from daily_pulse

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("daily_pulse", "notes")


def downgrade() -> None:
    op.add_column(
        "daily_pulse",
        sa.Column("notes", sa.Text(), nullable=True),
    )
