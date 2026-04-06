"""Add project_labels table and project column to memory_items.

project_labels: user-created project labels for categorizing memories.
memory_items.project: soft reference (String, no FK) to project label name.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create project_labels table and add project column to memory_items."""
    op.create_table(
        "project_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("color", sa.String(7), server_default="#6750A4", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.add_column(
        "memory_items",
        sa.Column("project", sa.String(100), nullable=True),
    )
    op.create_index("ix_memory_items_project", "memory_items", ["project"])


def downgrade() -> None:
    """Remove project column and project_labels table."""
    op.drop_index("ix_memory_items_project", table_name="memory_items")
    op.drop_column("memory_items", "project")
    op.drop_table("project_labels")
