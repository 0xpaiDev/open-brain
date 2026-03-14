"""Tests for database models."""

import pytest
from sqlalchemy.dialects.postgresql import UUID

from src.core.models import Base


class TestModelSchema:
    """Tests for model schema validation."""

    def test_all_tables_exist(self) -> None:
        """All 11 required tables should exist."""
        required_tables = {
            "raw_memory",
            "memory_items",
            "decisions",
            "tasks",
            "entities",
            "entity_aliases",
            "entity_relations",
            "memory_entity_links",
            "refinement_queue",
            "failed_refinements",
            "retrieval_events",
        }

        existing_tables = set(Base.metadata.tables.keys())

        missing = required_tables - existing_tables
        assert not missing, f"Missing tables: {missing}"

    def test_uuid_pk_on_simple_tables(self) -> None:
        """Simple tables should have UUID PKs, not BigInteger."""
        simple_tables = {
            "raw_memory",
            "memory_items",
            "decisions",
            "tasks",
            "entities",
            "entity_aliases",
            "refinement_queue",
            "failed_refinements",
            "retrieval_events",
        }

        for table_name in simple_tables:
            table = Base.metadata.tables[table_name]
            pk_cols = [col for col in table.columns if col.primary_key]
            assert len(pk_cols) == 1, f"{table_name} should have single pk"

            pk_col = pk_cols[0]
            assert isinstance(pk_col.type, UUID), (
                f"{table_name}.{pk_col.name} should be UUID, got {pk_col.type}"
            )

    def test_entity_relations_composite_pk(self) -> None:
        """entity_relations should have composite PK: (from_entity_id, to_entity_id, relation_type, memory_id)."""
        entity_relations_table = Base.metadata.tables["entity_relations"]
        pk_cols = [col.name for col in entity_relations_table.columns if col.primary_key]

        expected_cols = {"from_entity_id", "to_entity_id", "relation_type", "memory_id"}
        actual_cols = set(pk_cols)

        assert (
            actual_cols == expected_cols
        ), f"entity_relations pk should be {expected_cols}, got {actual_cols}"

    def test_memory_entity_links_composite_pk(self) -> None:
        """memory_entity_links should have composite PK: (memory_id, entity_id)."""
        memory_entity_links_table = Base.metadata.tables["memory_entity_links"]
        pk_cols = [col.name for col in memory_entity_links_table.columns if col.primary_key]

        expected_cols = {"memory_id", "entity_id"}
        actual_cols = set(pk_cols)

        assert (
            actual_cols == expected_cols
        ), f"memory_entity_links pk should be {expected_cols}, got {actual_cols}"

    def test_refinement_queue_has_required_columns(self) -> None:
        """refinement_queue should have all required columns."""
        queue_table = Base.metadata.tables["refinement_queue"]
        required_cols = {
            "id",
            "raw_id",
            "status",
            "attempts",
            "locked_at",
            "updated_at",
            "created_at",
        }
        existing_cols = {col.name for col in queue_table.columns}

        missing = required_cols - existing_cols
        assert not missing, f"refinement_queue missing columns: {missing}"

    def test_failed_refinements_has_queue_id_fk(self) -> None:
        """failed_refinements should have queue_id FK to refinement_queue."""
        failed_ref_table = Base.metadata.tables["failed_refinements"]

        # Check that queue_id column exists
        assert "queue_id" in failed_ref_table.columns, "failed_refinements should have queue_id column"

        # Check that it's a foreign key by looking at table FKs
        queue_id_col = failed_ref_table.columns["queue_id"]
        fks = queue_id_col.foreign_keys
        assert len(fks) > 0, "failed_refinements.queue_id should be a foreign key"

    def test_foreign_key_types_match_references(self) -> None:
        """All foreign keys should reference UUID columns with UUID type."""
        for table_name, table in Base.metadata.tables.items():
            for fk in table.foreign_keys:
                # Get the parent column (the FK) and the referenced column
                parent_col = fk.parent
                referenced_col = fk.column

                # Both should be UUID
                if parent_col.name not in ["relation_type"]:  # relation_type is not a FK
                    assert isinstance(
                        parent_col.type, UUID
                    ) or parent_col.name == "relation_type", (
                        f"{table_name}.{parent_col.name} FK should be UUID, got {parent_col.type}"
                    )

    def test_table_creation_order_respects_fks(self) -> None:
        """Verify table creation order respects FK dependencies.

        This test catches migrations where a table with FK constraints is created
        before its referenced table, which will fail on PostgreSQL.
        """
        tables = Base.metadata.sorted_tables
        table_names = [t.name for t in tables]

        # retrieval_events has FK to memory_items — memory_items must come first
        assert table_names.index("memory_items") < table_names.index("retrieval_events"), (
            "memory_items must be created before retrieval_events (FK constraint)"
        )

        # entity_relations has FK to entities — entities must come first
        assert table_names.index("entities") < table_names.index("entity_relations"), (
            "entities must be created before entity_relations (FK constraint)"
        )

        # memory_entity_links has FK to memory_items and entities
        assert table_names.index("memory_items") < table_names.index("memory_entity_links"), (
            "memory_items must be created before memory_entity_links (FK constraint)"
        )
        assert table_names.index("entities") < table_names.index("memory_entity_links"), (
            "entities must be created before memory_entity_links (FK constraint)"
        )
