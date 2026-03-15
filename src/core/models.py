"""SQLAlchemy ORM models for Open Brain.

All primary keys are UUID. All foreign keys must match the UUID type.
GENERATED columns (importance_score) are computed by Postgres.
Composite PKs on junction tables prevent duplicates on reprocessing.

Important: Do NOT update importance_score directly. Update base_importance or
dynamic_importance, and let the GENERATED column recompute.

Note on GENERATED columns:
When changing the formula for importance_score, you must:
1. Create an Alembic migration
2. In the migration, drop the old column with CASCADE
3. Add the new column with the new formula
This is documented in IMPLEMENTATION_PLAN.md.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    UUID,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Use JSONB for PostgreSQL, JSON for other databases (e.g., SQLite in tests)
JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")

# Use pgvector Vector for PostgreSQL, JSON for SQLite (tests)
VECTOR_TYPE = Vector(1024).with_variant(JSON(), "sqlite")


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# ── Immutable logs ────────────────────────────────────────────────────────────


class RawMemory(Base):
    """Original input text, immutable append-only log.

    source: where the input came from (api, email, slack, etc.)
    raw_text: the original unprocessed text
    chunk_index/total: if the input was pre-chunked, track which chunk this is
    parent_id: if this chunk came from splitting a larger input
    """

    __tablename__ = "raw_memory"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source: Mapped[str] = mapped_column(String(50))
    raw_text: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(255), default="user")
    metadata_: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True, name="metadata")

    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    chunk_index: Mapped[int | None] = mapped_column(nullable=True)
    chunk_total: Mapped[int | None] = mapped_column(nullable=True)
    parent_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("raw_memory.id", ondelete="CASCADE"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    memory_items = relationship("MemoryItem", back_populates="raw_memory")
    refinement_queue_entries = relationship("RefinementQueue", back_populates="raw_memory")
    failed_refinements = relationship("FailedRefinement", back_populates="raw_memory")


class RetrievalEvent(Base):
    """Search access log — feeds dynamic importance calculation.

    Whenever a memory_item is returned in a search result, log it here.
    This allows the daily job to aggregate usage and update dynamic_importance.
    """

    __tablename__ = "retrieval_events"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE")
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ── Refined knowledge ─────────────────────────────────────────────────────────


class MemoryItem(Base):
    """Extracted, normalized, ranked knowledge with importance score.

    Composite importance: 0.6 × base_importance + 0.4 × dynamic_importance
    The importance_score column is GENERATED ALWAYS STORED in Postgres.

    Important: Never UPDATE importance_score directly.
    Instead, update base_importance or dynamic_importance, and Postgres will recompute.

    supersedes_id: if this corrects a previous memory, link to the original
    is_superseded: flag to mark this memory as corrected/outdated
    """

    __tablename__ = "memory_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    raw_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_memory.id"))
    type: Mapped[str] = mapped_column(String(50), default="memory")  # memory, decision, task
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    base_importance: Mapped[float] = mapped_column(Numeric(precision=4, scale=2), default=0.5)
    dynamic_importance: Mapped[float] = mapped_column(Numeric(precision=4, scale=2), default=0.0)

    # GENERATED column: importance_score = 0.6 * base + 0.4 * dynamic
    # This is computed by Postgres, not by SQLAlchemy
    # In Alembic migration, defined as:
    # ALTER TABLE memory_items ADD importance_score NUMERIC(4,2)
    #   GENERATED ALWAYS AS (0.6 * base_importance + 0.4 * dynamic_importance) STORED;
    importance_score: Mapped[float | None] = mapped_column(
        Numeric(precision=4, scale=2),
        Computed("0.6 * base_importance + 0.4 * dynamic_importance", persisted=True),
        nullable=True,
    )

    # embedding: vector(1024) — pgvector type for PostgreSQL, JSON for SQLite tests
    embedding: Mapped[list | None] = mapped_column(
        VECTOR_TYPE, nullable=True
    )

    supersedes_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), nullable=True
    )
    is_superseded: Mapped[bool] = mapped_column(default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    raw_memory = relationship("RawMemory", back_populates="memory_items")
    decisions = relationship("Decision", back_populates="memory_item")
    tasks = relationship("Task", back_populates="memory_item")
    entity_links = relationship("MemoryEntityLink", back_populates="memory_item")
    retrieval_events = relationship("RetrievalEvent", foreign_keys=[RetrievalEvent.memory_id])


class Decision(Base):
    """Structured decision record with alternatives."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("memory_items.id"))
    decision: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    alternatives: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    memory_item = relationship("MemoryItem", back_populates="decisions")


class Task(Base):
    """Task items with owner, due date, status."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("memory_items.id"))
    description: Mapped[str] = mapped_column(Text)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open")  # open, done, cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    memory_item = relationship("MemoryItem", back_populates="tasks")


# ── Entity knowledge graph ────────────────────────────────────────────────────


class Entity(Base):
    """Canonical entity name with type (person, org, project, concept, tool, place)."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    type: Mapped[str] = mapped_column(String(50))  # person, org, project, concept, tool, place
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    aliases = relationship("EntityAlias", back_populates="entity")
    outgoing_relations = relationship(
        "EntityRelation",
        foreign_keys="EntityRelation.from_entity_id",
        back_populates="from_entity",
    )
    incoming_relations = relationship(
        "EntityRelation",
        foreign_keys="EntityRelation.to_entity_id",
        back_populates="to_entity",
    )
    memory_links = relationship("MemoryEntityLink", back_populates="entity")


class EntityAlias(Base):
    """Variant names mapping to canonical entity."""

    __tablename__ = "entity_aliases"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    alias: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    entity_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"))
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    entity = relationship("Entity", back_populates="aliases")


class EntityRelation(Base):
    """Graph edges: works_on, owns, related_to, decided_by, etc.

    Composite PK: (from_entity_id, to_entity_id, relation_type, memory_id)
    This prevents duplicate edges from reprocessing.
    """

    __tablename__ = "entity_relations"
    __table_args__ = (
        Index(
            "ix_entity_relations_pk",
            "from_entity_id",
            "to_entity_id",
            "relation_type",
            "memory_id",
            unique=True,
        ),
    )

    from_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    to_entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    memory_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    from_entity = relationship(
        "Entity",
        foreign_keys=[from_entity_id],
        back_populates="outgoing_relations",
    )
    to_entity = relationship(
        "Entity",
        foreign_keys=[to_entity_id],
        back_populates="incoming_relations",
    )


class MemoryEntityLink(Base):
    """M2M junction between memory_items and entities.

    Composite PK: (memory_id, entity_id)
    Prevents duplicate links from reprocessing.
    """

    __tablename__ = "memory_entity_links"
    __table_args__ = (
        Index("ix_memory_entity_links_pk", "memory_id", "entity_id", unique=True),
    )

    memory_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memory_items.id", ondelete="CASCADE"), primary_key=True
    )
    entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    memory_item = relationship("MemoryItem", back_populates="entity_links")
    entity = relationship("Entity", back_populates="memory_links")


# ── Processing state ──────────────────────────────────────────────────────────


class RefinementQueue(Base):
    """Job queue with SELECT FOR UPDATE SKIP LOCKED polling.

    status: pending, processing, done, failed
    attempts: how many times we've tried to process this
    locked_at: when we last set status=processing (for stale lock detection)
    updated_at: last update time
    """

    __tablename__ = "refinement_queue"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    raw_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_memory.id"))
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    raw_memory = relationship("RawMemory", back_populates="refinement_queue_entries")


class FailedRefinement(Base):
    """Dead letter queue: jobs that failed 3 times.

    queue_id: FK to the refinement_queue row
    error_reason: last error message
    attempt_count: total attempts
    last_output: last LLM output before failure (for debugging)
    retry_count: how many times we've manually retried
    resolved_at: when this was manually resolved
    """

    __tablename__ = "failed_refinements"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    raw_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("raw_memory.id"))
    queue_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("refinement_queue.id"))
    error_reason: Mapped[str] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(default=3)
    last_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    raw_memory = relationship("RawMemory", back_populates="failed_refinements")
