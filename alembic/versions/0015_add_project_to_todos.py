"""Add project column to todo_items and seed the Personal project label.

todo_items.project: soft reference (String, no FK) to project_labels.name —
mirrors the existing memory_items.project pattern. NULL renders as Personal
at the UI layer; the seed row exists so the picker can return a real value
when the user explicitly chooses Personal.
"""

import uuid as _uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PERSONAL_NAME = "Personal"
_PERSONAL_COLOR = "#7b8fc7"


def upgrade() -> None:
    op.add_column(
        "todo_items",
        sa.Column("project", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_todo_items_project", "todo_items", ["project"])

    # Idempotent seed of the Personal project label.
    project_labels = sa.table(
        "project_labels",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("color", sa.String()),
    )
    bind = op.get_bind()
    existing = bind.execute(
        sa.select(sa.func.count())
        .select_from(project_labels)
        .where(project_labels.c.name == _PERSONAL_NAME)
    ).scalar()
    if not existing:
        bind.execute(
            sa.insert(project_labels).values(
                id=_uuid.uuid4(),
                name=_PERSONAL_NAME,
                color=_PERSONAL_COLOR,
            )
        )


def downgrade() -> None:
    op.drop_index("ix_todo_items_project", table_name="todo_items")
    op.drop_column("todo_items", "project")
    # Intentionally NOT removing the Personal seed row — other tooling/data
    # may reference it; leaving it is safe because the column is gone.
