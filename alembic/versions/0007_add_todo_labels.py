"""Add todo_labels table and label column to todo_items.

todo_labels: user-created labels for categorizing todos.
todo_items.label: soft reference (String, no FK) to label name.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create todo_labels table and add label column to todo_items."""
    op.create_table(
        "todo_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(50), nullable=False),
        sa.Column("color", sa.String(7), server_default="#6750A4", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.add_column(
        "todo_items",
        sa.Column("label", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    """Remove label column and todo_labels table."""
    op.drop_column("todo_items", "label")
    op.drop_table("todo_labels")
