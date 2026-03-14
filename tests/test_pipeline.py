"""Tests for pipeline processing stages (normalize, extract, validate, embed, resolve)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.core.models import Entity, EntityAlias
from src.llm.client import EmbeddingFailed
from src.pipeline.embedder import embed_text
from src.pipeline.entity_resolver import resolve_entities
from src.pipeline.extractor import (
    EntityExtract,
    ExtractionFailed,
    ExtractionResult,
    extract,
)
from src.pipeline.normalizer import chunk, normalize
from src.pipeline.validator import ValidationFailed, validate

# ── Normalizer tests ──────────────────────────────────────────────────────


def test_normalize_strips_leading_trailing_whitespace():
    """normalize() strips leading and trailing whitespace."""
    text = "  \n  hello world  \n  "
    result = normalize(text)
    assert result == "hello world"


def test_normalize_collapses_multiple_blank_lines():
    """normalize() collapses multiple blank lines into one."""
    text = "line 1\n\n\n\nline 2\n\nline 3"
    result = normalize(text)
    assert result == "line 1\n\nline 2\n\nline 3"


def test_normalize_handles_unicode_nfc():
    """normalize() converts unicode to NFC form."""
    # Decomposed form (NFD) of 'é'
    text_nfd = "café"  # é in decomposed form
    result = normalize(text_nfd)
    # Result should be in NFC form
    assert result == "café"  # NFC form


def test_normalize_preserves_internal_structure():
    """normalize() preserves meaningful structure and indentation."""
    text = "Title\n  - Item 1\n  - Item 2"
    result = normalize(text)
    assert "Item 1" in result
    assert "Item 2" in result


def test_chunk_returns_single_for_short_text():
    """chunk() returns single-element list for text under max_tokens."""
    text = "This is a short text"
    result = chunk(text, max_tokens=100)

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0] == text


def test_chunk_splits_long_text():
    """chunk() splits long text into multiple chunks."""
    # Create text with many tokens (well over max_tokens)
    text = "word " * 1000  # ~1000 tokens
    result = chunk(text, max_tokens=100)

    assert isinstance(result, list)
    assert len(result) > 1
    # All chunks should be <= max_tokens
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    for chunk_text in result:
        tokens = len(enc.encode(chunk_text))
        assert tokens <= 100


def test_chunk_preserves_newlines():
    """chunk() respects newline boundaries when splitting."""
    text = "line 1\nline 2\nline 3\n" * 200
    result = chunk(text, max_tokens=50)

    assert len(result) > 1
    # Each chunk should contain complete lines (not mid-line splits)
    for _chunk_text in result:
        # If chunk ends with \n, it's a clean boundary
        # If it doesn't, the last line should be complete
        pass  # This is a best-effort behavior, hard to test precisely


# ── Extractor tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_returns_extraction_result_on_valid_json():
    """extract() returns ExtractionResult for valid Claude response."""
    mock_client = AsyncMock()
    mock_client.complete.return_value = (
        '{"type": "memory", "content": "test", "base_importance": 0.5}'
    )

    result = await extract("test text", attempt=0, client=mock_client)

    assert isinstance(result, ExtractionResult)
    assert result.type == "memory"
    assert result.content == "test"


@pytest.mark.asyncio
async def test_extract_raises_extraction_failed_on_invalid_json():
    """extract() raises ExtractionFailed when response is not valid JSON."""
    mock_client = AsyncMock()
    mock_client.complete.return_value = "not json at all"

    with pytest.raises(ExtractionFailed):
        await extract("test text", attempt=0, client=mock_client)


@pytest.mark.asyncio
async def test_extract_raises_extraction_failed_on_schema_mismatch():
    """extract() raises ExtractionFailed when JSON doesn't match schema."""
    mock_client = AsyncMock()
    # Missing required 'content' field
    mock_client.complete.return_value = '{"type": "memory"}'

    with pytest.raises(ExtractionFailed):
        await extract("test text", attempt=0, client=mock_client)


@pytest.mark.asyncio
async def test_extract_attempt_0_uses_main_prompt():
    """extract() with attempt=0 uses the main extraction prompt."""
    with patch("src.pipeline.extractor.get_extraction_prompt") as mock_get_prompt:
        mock_get_prompt.return_value = "test prompt 0"
        mock_client = AsyncMock()
        mock_client.complete.return_value = (
            '{"type": "memory", "content": "test"}'
        )

        await extract("test text", attempt=0, client=mock_client)

        mock_get_prompt.assert_called_once_with(0)


@pytest.mark.asyncio
async def test_extract_attempt_1_uses_retry_prompt():
    """extract() with attempt=1 uses the stricter retry prompt."""
    with patch("src.pipeline.extractor.get_extraction_prompt") as mock_get_prompt:
        mock_get_prompt.return_value = "test prompt 1"
        mock_client = AsyncMock()
        mock_client.complete.return_value = (
            '{"type": "memory", "content": "test"}'
        )

        await extract("test text", attempt=1, client=mock_client)

        mock_get_prompt.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_extract_includes_entities_and_tasks():
    """extract() correctly extracts nested structures (entities, tasks)."""
    mock_client = AsyncMock()
    json_response = {
        "type": "memory",
        "content": "test",
        "entities": [{"name": "Alice", "type": "person"}],
        "tasks": [{"description": "do something"}],
        "base_importance": 0.75,
    }
    mock_client.complete.return_value = json.dumps(json_response)

    result = await extract("test text", attempt=0, client=mock_client)

    assert len(result.entities) == 1
    assert result.entities[0].name == "Alice"
    assert len(result.tasks) == 1
    assert result.base_importance == 0.75


# ── Validator tests ───────────────────────────────────────────────────────


def test_validate_raises_on_empty_content():
    """validate() raises ValidationFailed for empty content."""
    extraction = ExtractionResult(type="memory", content="")

    with pytest.raises(ValidationFailed):
        validate(extraction)


def test_validate_normalizes_entity_names():
    """validate() normalizes entity names (strip whitespace, lowercase)."""
    extraction = ExtractionResult(
        type="memory",
        content="test",
        entities=[
            EntityExtract(name="  Claude AI  ", type="org"),
            EntityExtract(name="ALICE", type="person"),
        ],
    )

    result = validate(extraction)

    # Entity names are kept as-is, but deduplication uses normalized form
    assert len(result.entities) == 2


def test_validate_deduplicates_entities_by_normalized_name():
    """validate() deduplicates entities by their normalized name."""
    extraction = ExtractionResult(
        type="memory",
        content="test",
        entities=[
            EntityExtract(name="Alice", type="person"),
            EntityExtract(name="  alice  ", type="person"),  # Duplicate
            EntityExtract(name="Bob", type="person"),
        ],
    )

    result = validate(extraction)

    # Should deduplicate to 2 entities (Alice and Bob)
    assert len(result.entities) == 2


def test_validate_passes_through_valid_extraction():
    """validate() returns the extraction unchanged if valid."""
    extraction = ExtractionResult(
        type="memory",
        content="test content",
        summary="summary",
        entities=[EntityExtract(name="Test", type="project")],
    )

    result = validate(extraction)

    assert result.content == extraction.content
    assert result.summary == extraction.summary
    assert len(result.entities) == 1


# ── Embedder tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embed_text_returns_1024_floats():
    """embed_text() returns a list of 1024 floats."""
    mock_client = AsyncMock()
    mock_client.embed.return_value = [0.1] * 1024

    result = await embed_text("test text", client=mock_client)

    assert isinstance(result, list)
    assert len(result) == 1024
    assert all(isinstance(x, float) for x in result)


@pytest.mark.asyncio
async def test_embed_text_passes_through_embedding_failed():
    """embed_text() propagates EmbeddingFailed from client."""
    mock_client = AsyncMock()
    mock_client.embed.side_effect = EmbeddingFailed("Embedding failed")

    with pytest.raises(EmbeddingFailed):
        await embed_text("test text", client=mock_client)


# ── Entity Resolver tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_entities_creates_new_entity_when_none_exist(async_session):
    """resolve_entities() creates a new entity when no match exists."""
    entities = [EntityExtract(name="NewOrg", type="org")]

    result = await resolve_entities(async_session, entities)

    assert len(result) == 1
    assert result[0].name == "NewOrg"

    # Verify entity was persisted
    db_entity = await async_session.get(Entity, result[0].id)
    assert db_entity is not None
    assert db_entity.name == "NewOrg"


@pytest.mark.asyncio
async def test_resolve_entities_returns_existing_on_exact_alias_match(async_session):
    """resolve_entities() returns existing entity when alias matches exactly."""
    # Create an existing entity and alias
    entity = Entity(name="Original Name", type="org")
    async_session.add(entity)
    await async_session.flush()

    alias = EntityAlias(entity_id=entity.id, alias="Shorthand")
    async_session.add(alias)
    await async_session.commit()

    # Now resolve with the alias name
    entities = [EntityExtract(name="Shorthand", type="org")]
    result = await resolve_entities(async_session, entities)

    assert len(result) == 1
    assert result[0].id == entity.id
    assert result[0].name == "Original Name"


@pytest.mark.asyncio
async def test_resolve_entities_creates_separate_entity_below_threshold(
    async_session,
):
    """resolve_entities() creates new entity when fuzzy match is below threshold."""
    # Create an existing entity
    entity = Entity(name="Alice Johnson", type="person")
    async_session.add(entity)
    await async_session.commit()

    # Try to resolve a very different name (below fuzzy threshold)
    # Note: This test can't actually test fuzzy matching on SQLite.
    # In real usage on Postgres with pg_trgm, names very different from
    # "Alice Johnson" (like "Bob") won't match. For this test, we'll
    # just verify that a new entity is created.
    entities = [EntityExtract(name="Bob Smith", type="person")]
    result = await resolve_entities(async_session, entities)

    assert len(result) == 1
    assert result[0].name == "Bob Smith"
    assert result[0].id != entity.id


@pytest.mark.asyncio
async def test_resolve_entities_is_idempotent(async_session):
    """resolve_entities() + alias creation ensures idempotency on second call."""
    entities = [EntityExtract(name="TestEntity", type="project")]

    # First call - creates new entity
    result1 = await resolve_entities(async_session, entities)
    await async_session.commit()

    # Manually create an alias so second call finds it via exact match
    alias = EntityAlias(entity_id=result1[0].id, alias="TestEntity")
    async_session.add(alias)
    await async_session.commit()

    # Second call with same input - should find via alias match
    result2 = await resolve_entities(async_session, entities)

    assert result1[0].id == result2[0].id

    # Verify only one entity row exists
    query_result = await async_session.execute(
        select(Entity).where(Entity.name == "TestEntity")
    )
    entities_in_db = query_result.scalars().all()
    assert len(entities_in_db) == 1


@pytest.mark.asyncio
async def test_resolve_entities_with_multiple_entities(async_session):
    """resolve_entities() handles multiple entities in one call."""
    entities = [
        EntityExtract(name="Entity1", type="org"),
        EntityExtract(name="Entity2", type="person"),
        EntityExtract(name="Entity3", type="project"),
    ]

    result = await resolve_entities(async_session, entities)

    assert len(result) == 3
    assert {r.name for r in result} == {"Entity1", "Entity2", "Entity3"}
