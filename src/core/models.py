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

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    UUID,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


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
    embedding: Mapped[list | None] = mapped_column(VECTOR_TYPE, nullable=True)

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
    entity_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE")
    )
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
    __table_args__ = (Index("ix_memory_entity_links_pk", "memory_id", "entity_id", unique=True),)

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


# ── Module: Todo ───────────────────────────────────────────────────────────────


class TodoItem(Base):
    """First-class todo item managed via Discord slash commands.

    priority: "high" | "normal" | "low"
    status: "open" | "done" | "cancelled"
    discord_message_id/channel_id: stored to allow in-place embed edits on bot restart.
    """

    __tablename__ = "todo_items"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discord_message_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    discord_channel_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_todo_items_status_due_date", "status", "due_date"),)

    # Relationships
    history: Mapped[list["TodoHistory"]] = relationship(
        "TodoHistory", back_populates="todo", cascade="all, delete-orphan"
    )


class TodoHistory(Base):
    """Append-only audit log for todo state changes.

    event_type: "created" | "completed" | "deferred" | "cancelled" | "priority_changed"
    old_value/new_value: JSON snapshots of changed fields
    reason: populated on deferrals
    """

    __tablename__ = "todo_history"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    todo_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("todo_items.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    todo: Mapped["TodoItem"] = relationship("TodoItem", back_populates="history")


# ── Module: Daily Pulse ────────────────────────────────────────────────────────


class DailyPulse(Base):
    """Morning check-in record — one row per calendar day.

    pulse_date has a UNIQUE constraint to prevent duplicate sends.
    status: "sent" | "replied" | "parsed" | "parse_failed" | "skipped" | "completed"
    parsed_data: full Haiku-parsed JSON blob (sleep_quality, energy_level, etc.)
    ai_question_response: user's answer to the AI-generated question (modal field 4)
    notes: free-text mood / notes from the modal
    """

    __tablename__ = "daily_pulse"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    pulse_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, unique=True
    )
    raw_reply: Mapped[str | None] = mapped_column(Text, nullable=True)
    sleep_quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wake_time: Mapped[str | None] = mapped_column(String(10), nullable=True)
    parsed_data: Mapped[dict | None] = mapped_column(JSON_TYPE, nullable=True)
    ai_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_question_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    discord_message_id: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Module: RAG Chat ───────────────────────────────────────────────────────────


class RagConversation(Base):
    """Persisted conversation buffer for Discord RAG chat.

    One row per (channel, user) pair. Survives bot restarts.
    messages: [{role: "user"|"assistant", content: "..."}]
    model_name: tracks which model is active for this conversation.
    Unique constraint on (discord_channel_id, discord_user_id).
    """

    __tablename__ = "rag_conversations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    discord_channel_id: Mapped[str] = mapped_column(String(30), nullable=False)
    discord_user_id: Mapped[str] = mapped_column(String(30), nullable=False)
    messages: Mapped[list] = mapped_column(JSON_TYPE, nullable=False, default=list)
    model_name: Mapped[str] = mapped_column(String(100), default="claude-haiku-4-5-20251001")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("discord_channel_id", "discord_user_id", name="uq_rag_conv_channel_user"),
    )


# ── Job Monitoring ────────────────────────────────────────────────────────────


class JobRun(Base):
    """Tracks execution of scheduled jobs (pulse, importance, synthesis).

    Used by the job runner wrapper to record start/finish/status of each
    cron-triggered job, and by the /v1/jobs/status endpoint for monitoring.
    """

    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    job_name: Mapped[str] = mapped_column(String(50), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_job_runs_name_started", "job_name", started_at.desc()),)
