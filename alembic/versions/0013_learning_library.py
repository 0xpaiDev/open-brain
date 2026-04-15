"""Add learning library tables: topics, sections, items; link from todo_items.

Three-layer hierarchy (Topic → Section → Item) supporting a daily-injected
learning todo flow. Learning items do NOT sync into memory_items; the
todos created from them do (they are normal todos with an FK back to the
source item).

RLS enabled (deny-all, app connects as superuser). Non-nullable learning_item_id
FK on todo_items is ON DELETE SET NULL so deleting an underlying item never
orphans a todo.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "learning_topics",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("depth", sa.String(length=20), server_default="foundational", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
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
    op.create_index(
        "ix_learning_topics_active_position",
        "learning_topics",
        ["is_active", "position"],
    )
    op.execute("ALTER TABLE learning_topics ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "learning_sections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("topic_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["topic_id"], ["learning_topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_sections_topic_position",
        "learning_sections",
        ["topic_id", "position"],
    )
    op.execute("ALTER TABLE learning_sections ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "learning_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["section_id"], ["learning_sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_items_section_status_position",
        "learning_items",
        ["section_id", "status", "position"],
    )
    op.execute("ALTER TABLE learning_items ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "todo_items",
        sa.Column("learning_item_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_todo_items_learning_item_id",
        "todo_items",
        "learning_items",
        ["learning_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_todo_items_learning_item_id",
        "todo_items",
        ["learning_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_todo_items_learning_item_id", table_name="todo_items")
    op.drop_constraint("fk_todo_items_learning_item_id", "todo_items", type_="foreignkey")
    op.drop_column("todo_items", "learning_item_id")

    op.drop_index("ix_learning_items_section_status_position", table_name="learning_items")
    op.drop_table("learning_items")

    op.drop_index("ix_learning_sections_topic_position", table_name="learning_sections")
    op.drop_table("learning_sections")

    op.drop_index("ix_learning_topics_active_position", table_name="learning_topics")
    op.drop_table("learning_topics")
