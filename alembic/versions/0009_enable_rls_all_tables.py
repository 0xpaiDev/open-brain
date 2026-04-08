"""Enable Row-Level Security on all tables.

Supabase exposes every table via its PostgREST API. Without RLS,
anyone with the project URL can read/write/delete all data using the
anon key. Enabling RLS with no policies = deny-all for non-superuser
roles (anon, authenticated) while the app's direct postgres connection
(superuser) bypasses RLS transparently.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Every table in the schema as of migration 0008.
ALL_TABLES = [
    "raw_memory",
    "retrieval_events",
    "memory_items",
    "decisions",
    "tasks",
    "entities",
    "entity_aliases",
    "entity_relations",
    "memory_entity_links",
    "refinement_queue",
    "failed_refinements",
    "todo_labels",
    "project_labels",
    "todo_items",
    "todo_history",
    "daily_pulse",
    "rag_conversations",
    "job_runs",
]


def upgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ALL_TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
