"""Add content_hash column to raw_memory for SHA-256 dedup.

Adds a nullable VARCHAR(64) column and a B-tree index for efficient
24h-window dedup lookups in POST /v1/memory.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add content_hash column and index to raw_memory."""
    op.add_column("raw_memory", sa.Column("content_hash", sa.String(64), nullable=True))
    op.create_index("ix_raw_memory_content_hash", "raw_memory", ["content_hash"])


def downgrade() -> None:
    """Remove content_hash column and index from raw_memory."""
    op.drop_index("ix_raw_memory_content_hash", table_name="raw_memory")
    op.drop_column("raw_memory", "content_hash")
