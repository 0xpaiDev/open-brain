"""Initial schema with 11 tables, UUID PKs, composite PKs, and indexes.

This migration creates the base schema for Open Brain with:
- All tables using UUID primary keys
- Composite PKs on entity_relations and memory_entity_links (idempotent)
- GENERATED column for importance_score (0.6 * base + 0.4 * dynamic)
- HNSW index on memory_items.embedding (vector similarity)
- GIN index on memory_items.content (full-text search)
- B-tree indexes on frequently queried columns
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial schema."""

    # Enable required extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ─────────────────────────────────────────────────────────────────
    # Immutable logs
    # ─────────────────────────────────────────────────────────────────

    # raw_memory: original input text
    op.create_table(
        "raw_memory",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255), nullable=False, server_default="user"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("chunk_total", sa.Integer(), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["raw_memory.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_raw_memory_created_at", "created_at"),
    )

    # ─────────────────────────────────────────────────────────────────
    # Refined knowledge
    # ─────────────────────────────────────────────────────────────────

    # memory_items: extracted, normalized, ranked knowledge
    op.create_table(
        "memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="memory"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("base_importance", sa.Numeric(precision=4, scale=2), nullable=False, server_default="0.50"),
        sa.Column("dynamic_importance", sa.Numeric(precision=4, scale=2), nullable=False, server_default="0.00"),
        # MANUAL DDL: importance_score is GENERATED in Postgres
        sa.Column("embedding", postgresql.UUID(as_uuid=True), nullable=True),  # Placeholder, will be vector
        sa.Column("supersedes_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("is_superseded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["raw_id"], ["raw_memory.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_memory_items_type", "type"),
        sa.Index("ix_memory_items_created_at", "created_at"),
        sa.Index("ix_memory_items_is_superseded", "is_superseded"),
    )

    # retrieval_events: search access log for dynamic importance
    # NOTE: Must be created AFTER memory_items due to FK constraint
    op.create_table(
        "retrieval_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_retrieval_events_memory_id", "memory_id"),
    )

    # decisions: structured decision records
    op.create_table(
        "decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("alternatives", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # tasks: task items with owner and due date
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(255), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_tasks_status", "status"),
        sa.Index("ix_tasks_due_date", "due_date"),
    )

    # ─────────────────────────────────────────────────────────────────
    # Entity knowledge graph
    # ─────────────────────────────────────────────────────────────────

    # entities: canonical entity names
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.Index("ix_entities_name", "name"),
        sa.Index("ix_entities_type", "type"),
    )

    # entity_aliases: variant names mapping to canonical entities
    op.create_table(
        "entity_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(255), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("alias"),
        sa.Index("ix_entity_aliases_alias", "alias"),
    )

    # entity_relations: graph edges (COMPOSITE PK)
    op.create_table(
        "entity_relations",
        sa.Column("from_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["from_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("from_entity_id", "to_entity_id", "relation_type", "memory_id"),
    )

    # memory_entity_links: M2M junction (COMPOSITE PK)
    op.create_table(
        "memory_entity_links",
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("memory_id", "entity_id"),
    )

    # ─────────────────────────────────────────────────────────────────
    # Processing state
    # ─────────────────────────────────────────────────────────────────

    # refinement_queue: job queue with SELECT FOR UPDATE SKIP LOCKED
    op.create_table(
        "refinement_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["raw_id"], ["raw_memory.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.Index("ix_refinement_queue_status", "status"),
    )

    # failed_refinements: dead letter queue
    op.create_table(
        "failed_refinements",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("queue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("error_reason", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("last_output", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["raw_id"], ["raw_memory.id"]),
        sa.ForeignKeyConstraint(["queue_id"], ["refinement_queue.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ─────────────────────────────────────────────────────────────────
    # MANUAL DDL: Custom indexes and columns
    # ─────────────────────────────────────────────────────────────────

    # Add importance_score as GENERATED column
    op.execute(
        """
        ALTER TABLE memory_items
        ADD COLUMN importance_score NUMERIC(4, 2)
        GENERATED ALWAYS AS (0.6 * base_importance + 0.4 * dynamic_importance) STORED
        """
    )

    # Change embedding column to pgvector type
    op.execute(
        """
        ALTER TABLE memory_items
        ALTER COLUMN embedding DROP DEFAULT,
        ALTER COLUMN embedding SET DATA TYPE vector(1024)
        """
    )

    # HNSW index for vector similarity search
    op.execute(
        """
        CREATE INDEX ix_memory_items_embedding_hnsw
        ON memory_items
        USING hnsw (embedding vector_cosine_ops)
        WITH (m=16, ef_construction=64)
        WHERE embedding IS NOT NULL
        """
    )

    # GIN index for full-text search (exact expression must match query)
    op.execute(
        """
        CREATE INDEX ix_memory_items_content_gin
        ON memory_items
        USING GIN (to_tsvector('english', content))
        """
    )

    # B-tree index on importance_score for ranking
    op.execute(
        """
        CREATE INDEX ix_memory_items_importance_score
        ON memory_items (importance_score DESC)
        WHERE is_superseded = FALSE
        """
    )

    # B-tree index for stale lock reclaim query
    op.execute(
        """
        CREATE INDEX ix_refinement_queue_status_locked_at
        ON refinement_queue (status, locked_at)
        WHERE status IN ('pending', 'processing')
        """
    )


def downgrade() -> None:
    """Drop all tables and indexes."""

    # Drop tables in reverse order of creation (respecting foreign keys)
    op.drop_table("failed_refinements")
    op.drop_table("refinement_queue")
    op.drop_table("memory_entity_links")
    op.drop_table("entity_relations")
    op.drop_table("entity_aliases")
    op.drop_table("entities")
    op.drop_table("tasks")
    op.drop_table("decisions")
    op.drop_table("retrieval_events")  # Must drop before memory_items (FK depends on it)
    op.drop_table("memory_items")
    op.drop_table("raw_memory")

    # Disable extensions (usually leave them, but clean for downgrade)
    # op.execute("DROP EXTENSION IF EXISTS vector")
    # op.execute("DROP EXTENSION IF EXISTS pg_trgm")
