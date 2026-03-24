"""Add ai_question_response and notes columns to daily_pulse.

Supports the modal upgrade: structured input replaces free-text DM reply.
- ai_question_response: user's answer to the AI-generated question
- notes: free-text mood/notes from the modal
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add ai_question_response and notes columns to daily_pulse."""
    op.add_column("daily_pulse", sa.Column("ai_question_response", sa.Text, nullable=True))
    op.add_column("daily_pulse", sa.Column("notes", sa.Text, nullable=True))


def downgrade() -> None:
    """Remove ai_question_response and notes columns from daily_pulse."""
    op.drop_column("daily_pulse", "notes")
    op.drop_column("daily_pulse", "ai_question_response")
