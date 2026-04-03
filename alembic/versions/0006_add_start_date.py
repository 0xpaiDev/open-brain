"""Add start_date column to todo_items.

Nullable DateTime(timezone=True) — existing rows get NULL.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add start_date column to todo_items table."""
    op.add_column(
        "todo_items",
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Remove start_date column from todo_items table."""
    op.drop_column("todo_items", "start_date")
