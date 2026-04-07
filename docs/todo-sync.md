# Plan: Fix Task Extraction Noise & Todo Sync Pipeline

## Context

Two problems:
1. Auto-captured Claude Code sessions create noisy Task rows ("refactor component", "fix test") that pollute the task list. Only intentional sources should produce tasks.
2. TodoItem data is invisible to hybrid search and RAG chat. Asking "what are my todos?" returns nothing because search only queries `memory_items`.

**Solution for #2:** Sync todos into `memory_items` as first-class memories. On every todo write (create/update/complete), upsert a `memory_item` with the todo's content embedded. Completions also get their own memory. This makes todos searchable via the existing hybrid pipeline with zero changes to search or context builder.

---

## Change 1: Gate Task Extraction for Auto-Captured Sources

**New file:** `src/pipeline/constants.py`

Shared pipeline constants — avoids other modules importing from `worker.py`:
```python
AUTO_CAPTURE_SOURCES: frozenset[str] = frozenset({
    "claude-code",
    "claude_code_memory",
    "claude_code_history",
    "claude_code_project",
})
```

**File:** `src/pipeline/worker.py`

Import from constants module:
```python
from src.pipeline.constants import AUTO_CAPTURE_SOURCES
```

**Mod A** — Line 200: Extend importance cap to all auto-capture sources (latent bug fix):
```python
if raw.source in AUTO_CAPTURE_SOURCES and extraction.base_importance > ceiling:
```

**Mod B** — Lines 392-410: Guard task insertion:
```python
if raw.source not in AUTO_CAPTURE_SOURCES:
    for task_extract in extraction.tasks:
        ...  # existing code, indented one level
else:
    logger.debug("store_memory_item_skipped_tasks", source=raw.source, count=len(extraction.tasks))
```

**Tests** — `tests/test_worker.py`:
- `test_store_memory_item_skips_tasks_for_auto_capture_source`
- `test_store_memory_item_creates_tasks_for_intentional_source`
- Update existing importance cap test for `claude_code_memory`

---

## Change 2: Todo Sync Pipeline

### Design

Every todo mutation syncs a corresponding `memory_item`:

| Todo Event | Memory Action |
|---|---|
| Create | Create RawMemory(source="todo") + MemoryItem(type="todo") with embedding |
| Update (description, priority, due_date, label) | Supersede old memory_item, create new type="todo" |
| Complete (status="done") | Supersede old type="todo" memory, create new type="todo_completion" |
| Cancel | Supersede old type="todo" memory (no completion memory) |
| Reopen | Supersede old memory, create new type="todo" |

**Content format** (what gets embedded):

Type "todo":
```
Todo: Fix deployment script
Priority: high | Status: open | Due: 2026-04-10 | Label: work
```

Type "todo_completion":
```
Completed todo: Fix deployment script
Priority: high | Completed: 2026-04-07 | Label: work
```

**Linking:** Store `todo_id` in `RawMemory.metadata_` to find the current memory_item for supersession:
```python
SELECT mi.id FROM memory_items mi
JOIN raw_memory rm ON mi.raw_id = rm.id
WHERE rm.metadata_->>'todo_id' = :todo_id
  AND mi.is_superseded = false
ORDER BY mi.created_at DESC
```

**Race condition handling:** If rapid successive updates produce multiple non-superseded rows for the same todo_id, the query orders by `created_at DESC` and supersedes ALL matching rows (not just one). The sync function iterates the result set and marks each as `is_superseded=True`.

**Importance mapping:**
- high → base_importance=0.7
- normal → base_importance=0.5
- low → base_importance=0.3

**Transaction strategy:** The sync happens _after_ the todo's commit (in a new transaction) to avoid holding a DB transaction open during the embedding API call (~50ms). If sync fails, the todo write succeeds — the sync can be retried via backfill. Wrapped in try/except with logging.

### Files

#### New: `src/pipeline/todo_sync.py`

Core module with three functions:

```python
async def sync_todo_to_memory(session, todo, event_type, voyage_client):
    """Sync a TodoItem mutation to memory_items.
    
    1. Format content string from todo fields + event_type
    2. Generate embedding via embed_text()
    3. Find & supersede existing memory_item for this todo_id
    4. Create RawMemory(source="todo", metadata_={"todo_id": str(todo.id)})
    5. Create MemoryItem(type=..., content=..., embedding=..., raw_id=...)
    6. Commit
    """

def _format_todo_content(todo, event_type) -> tuple[str, str]:
    """Return (content_text, memory_type).
    
    memory_type: "todo" for open/updated, "todo_completion" for completed
    """

def _priority_to_importance(priority: str) -> float:
    """Map priority to base_importance: high=0.7, normal=0.5, low=0.3"""
```

On completion: supersede the old "todo" memory AND create a "todo_completion" memory. Active todos = non-superseded type="todo", completion history captured separately.

#### Modified: `src/api/services/todo_service.py`

Add sync calls after each commit:

```python
# At end of create_todo(), after commit+refresh:
await _try_sync(session, todo, "created")

# At end of update_todo(), after commit+refresh:
await _try_sync(session, todo, event_type)
```

The `_try_sync` wrapper:
```python
async def _try_sync(session, todo, event_type):
    try:
        from src.pipeline.todo_sync import sync_todo_to_memory
        from src.llm.client import embedding_client
        if not embedding_client:
            logger.warning("todo_sync_skipped_no_embedding_client", todo_id=str(todo.id))
            return
        await sync_todo_to_memory(session, todo, event_type, embedding_client)
    except Exception:
        logger.warning("todo_memory_sync_failed", todo_id=str(todo.id), exc_info=True)
```

Note: `_try_sync` is called after both `create_todo()` and `update_todo()`. Reopen is a status change handled by `update_todo()` (event_type="reopened") — no separate function needed. The sync handles all event types from the update_todo event_type detection (completed, cancelled, reopened, deferred, priority_changed, updated).

#### Modified: `src/llm/rag_prompts.py`

Update system prompt (line 29) to mention todos and give behavioural instruction:
```python
"You are a knowledgeable assistant with access to the user's personal memory system, "
"including their active todos and completed tasks. "
"When the user asks about priorities, progress, or what to work on, "
"check both memory and todo history before responding. "
```

#### New: `scripts/backfill_todo_memories.py`

One-time script to sync all existing TodoItems with error isolation and progress logging:
```python
async def backfill():
    failed = 0
    total = 0
    async with get_session() as session:
        todos = await session.execute(select(TodoItem))
        for todo in todos.scalars():
            total += 1
            try:
                event = "completed" if todo.status == "done" else "created"
                await sync_todo_to_memory(session, todo, event, embedding_client)
                # NOTE: For completed todos, this creates only a todo_completion memory.
                # The normal flow would first supersede an existing type="todo" memory,
                # but during backfill there is no prior memory to supersede. This is
                # intentional — historical completed todos get a completion record only,
                # not a reconstructed open-state memory. The completion record contains
                # the full description and is searchable.
            except Exception:
                failed += 1
                logger.warning("backfill_todo_failed", todo_id=str(todo.id), exc_info=True)
    logger.info("backfill_complete", total=total, failed=failed)
```

Run via: `python -m scripts.backfill_todo_memories`

### Tests

#### New: `tests/test_todo_sync.py`
- `test_format_todo_content_open` — verifies content format for open todo
- `test_format_todo_content_completed` — verifies completion content and type="todo_completion"
- `test_priority_to_importance` — maps high->0.7, normal->0.5, low->0.3
- `test_sync_creates_raw_memory_and_memory_item` — full DB test: creates todo, syncs, verifies RawMemory(source="todo") and MemoryItem(type="todo") exist
- `test_sync_supersedes_on_update` — create -> sync -> update -> sync -> verify old is_superseded=True
- `test_sync_completion_creates_both_memories` — complete -> verify old "todo" superseded + new "todo_completion" exists
- `test_sync_cancelled_supersedes_without_completion` — cancel -> verify old superseded, no "todo_completion"
- `test_sync_graceful_failure` — mock embedding to fail, verify no crash
- `test_sync_skipped_when_no_embedding_client` — mock embedding_client as None, assert warning logged and no exception raised

#### Updated: `tests/test_chat.py`
- `test_chat_finds_synced_todo` — create todo, sync to memory, chat "what are my todos?", verify todo appears in response context
- `test_chat_finds_todo_by_semantic_query` — E2E test (separate from unit run). Create todo "deploy the auth service to production", query "what work tasks do I have?", verify todo surfaces via semantic similarity. Marked `@pytest.mark.e2e` to avoid flakiness in `make test` — runs only via explicit `pytest -m e2e`

---

## What Stays Unchanged
- Hybrid search (`search.py`) — todos are now regular memory_items, searchable as-is
- Context builder — formats todo memories like any other memory
- TodoItem CRUD endpoints — todo management unchanged
- `memory_items` table schema — no new columns
- Search API response shape

## Migration Requirements
**None.** TodoItems sync into existing `raw_memory` + `memory_items` tables using existing columns. No schema changes.

## Verification Plan
1. `make test` — all existing + new tests pass
2. Run backfill script on dev DB
3. Manual: create a todo via API -> verify RawMemory + MemoryItem created
4. Manual: complete a todo -> verify old memory superseded + todo_completion memory created
5. Manual: chat "what are my open todos?" -> verify todos in response
6. Manual: chat "what travel tasks have I completed?" -> verify completion memories in response
7. Manual: ingest a claude-code source memory with tasks -> verify 0 Task rows

## Files Summary
| File | Action |
|---|---|
| `src/pipeline/constants.py` | **New** — AUTO_CAPTURE_SOURCES frozenset |
| `src/pipeline/worker.py` | Modify — import from constants, gate tasks, extend importance cap |
| `src/pipeline/todo_sync.py` | **New** — sync_todo_to_memory, formatting, importance mapping |
| `src/api/services/todo_service.py` | Modify — call sync after create/update commits |
| `src/llm/rag_prompts.py` | Modify — mention todos in system prompt |
| `scripts/backfill_todo_memories.py` | **New** — one-time backfill |
| `tests/test_worker.py` | Modify — task gating tests |
| `tests/test_todo_sync.py` | **New** — sync pipeline tests |
| `tests/test_chat.py` | Modify — todo visibility integration test |
