"""Add execution explorer tables (traces, spans, cost tracking).

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBSERVABILITY_TABLES = ["traces", "cron_steps", "llm_calls", "tool_calls", "events"]


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("trigger_type", sa.Text(), nullable=False),
        sa.Column("trigger_name", sa.Text(), nullable=True),
        sa.Column("trigger_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("total_input_tokens", sa.Integer(), nullable=True),
        sa.Column("total_output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cache_read_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cache_creation_tokens", sa.Integer(), nullable=True),
        sa.Column("llm_call_count", sa.Integer(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column(
            "causal_parent_trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id"),
            nullable=True,
        ),
        sa.Column(
            "rerun_of_trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id"),
            nullable=True,
        ),
        sa.Column("cost_alert_threshold_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_traces_started_at", "traces", [sa.text("started_at DESC")])
    op.create_index(
        "ix_traces_trigger_type_started_at",
        "traces",
        ["trigger_type", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_traces_status_started_at", "traces", ["status", sa.text("started_at DESC")]
    )
    op.create_index("ix_traces_causal_parent", "traces", ["causal_parent_trace_id"])
    op.create_index("ix_traces_rerun_of", "traces", ["rerun_of_trace_id"])

    op.create_table(
        "cron_steps",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=True),
        sa.Column("step_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column("step_metadata", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_cron_steps_trace_id", "cron_steps", ["trace_id"])
    op.create_index(
        "ix_cron_steps_trace_started", "cron_steps", ["trace_id", sa.text("started_at")]
    )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=True),
        sa.Column("call_site", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False, server_default="anthropic"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=True),
        sa.Column("cache_creation_input_tokens", sa.Integer(), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("pricing_version", sa.Text(), nullable=False),
        sa.Column("raw_request", postgresql.JSONB(), nullable=True),
        sa.Column("raw_response", postgresql.JSONB(), nullable=True),
        sa.Column("request_summary", postgresql.JSONB(), nullable=False),
        sa.Column("response_summary", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_class", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_calls_trace_id", "llm_calls", ["trace_id"])
    op.create_index(
        "ix_llm_calls_model_started", "llm_calls", ["model", sa.text("started_at DESC")]
    )
    op.create_index(
        "ix_llm_calls_call_site_started",
        "llm_calls",
        ["call_site", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_llm_calls_status_started", "llm_calls", ["status", sa.text("started_at DESC")]
    )
    op.create_index("ix_llm_calls_started_at", "llm_calls", [sa.text("started_at DESC")])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("args", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("is_error", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_tool_calls_trace_id", "tool_calls", ["trace_id"])
    op.create_index(
        "ix_tool_calls_tool_name_started",
        "tool_calls",
        ["tool_name", sa.text("started_at DESC")],
    )
    op.create_index(
        "ix_tool_calls_status_started", "tool_calls", ["status", sa.text("started_at DESC")]
    )

    op.create_table(
        "events",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "trace_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("traces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("span_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False, server_default="info"),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_events_trace_id", "events", ["trace_id"])
    op.create_index(
        "ix_events_event_type_occurred", "events", ["event_type", sa.text("occurred_at DESC")]
    )

    # Add trace_id to refinement_queue for causal linking (worker → ingest trace)
    op.add_column(
        "refinement_queue",
        sa.Column("trace_id", sa.UUID(as_uuid=True), nullable=True),
    )

    for table in OBSERVABILITY_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_column("refinement_queue", "trace_id")
    for table in reversed(OBSERVABILITY_TABLES):
        op.drop_table(table)
