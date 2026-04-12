"""Add strava_tokens table for OAuth token storage and auto-refresh.

Single-row table bootstrapped from env vars on first webhook event.
Stores access_token, refresh_token, expires_at for on-demand refresh.
RLS enabled (deny-all, app connects as superuser).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strava_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("athlete_id", sa.BigInteger(), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("ALTER TABLE strava_tokens ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("strava_tokens")
