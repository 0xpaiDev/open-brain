# Learning Library V2 — Bulk Import + Materials + Topic Detail Page

> Self-contained implementation spec for a fresh Claude session. Read top-to-bottom and execute in order. All file paths are absolute under `/home/shu/projects/open-brain` (the repo root, branch `master`).

## Context

The Learning Library is shipped (V1, migration 0013) but no curriculum has been seeded. Manually creating ~80 items via the UI is impractical, so the user wants a bulk-import flow:

1. User has source material (an article, chapter, or notes)
2. User pastes the material into an external LLM (Claude.ai or ChatGPT) along with a documented "import template" prompt + JSON schema
3. LLM returns a structured JSON document
4. User pastes that JSON into the app, runs a dry-run preview, then commits
5. The app stores both the curriculum structure AND the source material
6. User can later open a topic detail page to re-read material, see items, and review feedback history

Quiz / "test me" feature is intentionally out of scope and captured for a future plan.

## What is already built (do NOT re-implement)

- Tables: `learning_topics`, `learning_sections`, `learning_items` ([src/core/models.py:699-795](src/core/models.py#L699-L795))
- Migration `0013_learning_library.py` — base learning schema with RLS
- Most recent migration is **`0014_pulse_signal_type.py`** — new migration must be `0015`
- Routes: full CRUD + `POST /v1/learning/refresh` + `GET /v1/modules` ([src/api/routes/learning.py](src/api/routes/learning.py))
- Service: `load_tree`, `cascade_item_completion`, etc. ([src/api/services/learning_service.py](src/api/services/learning_service.py))
- Daily cron at 04:30 UTC ([src/jobs/learning_daily.py](src/jobs/learning_daily.py))
- Web tree view ([web/app/learning/page.tsx](web/app/learning/page.tsx)), `useLearning()` hook ([web/hooks/use-learning.ts](web/hooks/use-learning.ts)), sidebar nav, "Learning" badge on Today tasks
- 16 backend tests in [tests/test_learning.py](tests/test_learning.py)
- No `react-markdown` in [web/package.json](web/package.json) yet (verified)

## Locked design decisions

| Decision | Choice |
|---|---|
| LLM location | External only — app provides documented prompt + schema, no in-app generation |
| Format | JSON with strict Pydantic validation |
| Dedup | Skip-on-name-collision, case-insensitive, with warning |
| Preview | Two-step: `dry_run=true` → confirm with `dry_run=false` |
| Materials | New `learning_materials` table, **one-to-one** with topic (unique constraint on `topic_id`) |
| Review UI | New full-page route `/learning/topics/[id]` |
| Atomicity | Single transaction; rollback on any DB error |
| Memory sync | None — material does NOT sync to `memory_items` |
| Rate limit | `5/minute` for `POST /v1/learning/import` |

---

## Step 1 — Migration `0015_learning_materials.py`

Path: [alembic/versions/0015_learning_materials.py](alembic/versions/0015_learning_materials.py)

- `revision = "0015"`, `down_revision = "0014"`
- Create `learning_materials`:
  - `id` UUID PK (default `uuid4`)
  - `topic_id` UUID NOT NULL, FK → `learning_topics.id` ON DELETE CASCADE
  - `content` TEXT NOT NULL (markdown body, no length cap)
  - `source_type` VARCHAR(40) NULL (free-form: `article` / `note` / `transcript` / `book_excerpt` / `other`)
  - `source_url` VARCHAR(2048) NULL
  - `source_title` VARCHAR(240) NULL
  - `metadata_json` JSONB (`with_variant(JSON(), "sqlite")`) NULL
  - `created_at`, `updated_at` with `server_default=func.now()` and `onupdate=func.now()`
  - `UniqueConstraint("topic_id", name="uq_learning_materials_topic_id")`
  - `Index("ix_learning_materials_topic_id", "topic_id")`
- Trailing `op.execute("ALTER TABLE learning_materials ENABLE ROW LEVEL SECURITY")` — match the deny-all pattern from `0009`/`0013`.
- Provide `downgrade()` that drops the index then the table.

## Step 2 — ORM model

In [src/core/models.py](src/core/models.py), append `LearningMaterial` immediately after `LearningItem` (line 795):
- Mirror migration columns. Use `Mapped[...]` syntax (consistent with siblings).
- `topic_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("learning_topics.id", ondelete="CASCADE"), nullable=False)` — use `Mapped[str]`, not `Mapped[uuid.UUID]`, matching the sibling pattern where `UUID(as_uuid=True)` maps to str in the ORM layer.
- `metadata_json: Mapped[dict | None] = mapped_column(JSONB().with_variant(JSON(), "sqlite"), nullable=True)`
- `topic: Mapped["LearningTopic"] = relationship("LearningTopic", back_populates="material")`
- `__table_args__ = (UniqueConstraint("topic_id", name="uq_learning_materials_topic_id"),)`

On `LearningTopic` (around line 723), add:
```python
material: Mapped["LearningMaterial | None"] = relationship(
    "LearningMaterial",
    back_populates="topic",
    cascade="all, delete-orphan",
    uselist=False,
)
```

## Step 3 — Pydantic import schemas

Create [src/api/schemas/__init__.py](src/api/schemas/__init__.py) (empty) and [src/api/schemas/learning_import.py](src/api/schemas/learning_import.py):

```python
class ImportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=240)

class ImportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    items: list[ImportItem] = Field(default_factory=list, max_length=20)

class ImportMaterial(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)
    source_type: str | None = Field(default=None, max_length=40)
    source_url: str | None = Field(default=None, max_length=2048)
    source_title: str | None = Field(default=None, max_length=240)
    metadata: dict[str, Any] | None = None

class ImportTopic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    depth: Literal["foundational", "deep"] = "foundational"
    sections: list[ImportSection] = Field(default_factory=list, max_length=20)
    material: ImportMaterial | None = None

class LearningImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topics: list[ImportTopic] = Field(min_length=1, max_length=50)

class ImportSkip(BaseModel):
    name: str
    reason: Literal["name_collision"]

class ImportResult(BaseModel):
    dry_run: bool
    topics_created: int
    sections_created: int
    items_created: int
    materials_created: int
    topics_skipped: list[ImportSkip]
    created_topic_ids: list[str]  # empty when dry_run=True

class MaterialOut(BaseModel):
    id: str
    topic_id: str
    content: str
    source_type: str | None
    source_url: str | None
    source_title: str | None
    metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime

class MaterialUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1)
    source_type: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    metadata: dict[str, Any] | None = None
```

**No `position` field anywhere.** Server auto-assigns by array order. Document this in a module-level comment.

## Step 4 — Rate limit

In [src/api/middleware/rate_limit.py](src/api/middleware/rate_limit.py):
```python
def _get_learning_import_rate() -> str:
    return "5/minute"
learning_import_limit = _get_learning_import_rate
```

## Step 5 — Service layer

Extend [src/api/services/learning_service.py](src/api/services/learning_service.py):

```python
async def import_curriculum(
    session: AsyncSession,
    request: LearningImportRequest,
    *,
    dry_run: bool,
) -> ImportResult:
```

Implementation:
1. Load existing topic names: `SELECT name FROM learning_topics`. Lowercase into a set for case-insensitive comparison.
2. Walk request once. For each topic, check `name.lower() in existing` → bucket into `to_create` or `to_skip(name_collision)`.
3. Compute counts (`topics_created`, `sections_created`, `items_created`, `materials_created`) from `to_create`.
4. If `dry_run`: return `ImportResult(dry_run=True, ..., created_topic_ids=[])`. **No writes.**
5. If not `dry_run`:
   - Get current max `position` from `learning_topics`: `start_pos = (await session.scalar(select(func.max(LearningTopic.position)))) or -1`. The `or -1` handles an empty table where `MAX()` returns NULL, so the first topic gets `position=0`.
   - For each `ImportTopic` in `to_create` (with `idx` starting at 0), create `LearningTopic` with `position = start_pos + 1 + idx`, then add sections (`position=idx`), then items (`position=idx`), then `LearningMaterial` if present.
   - All adds inside `try/except`. After all adds: `await session.commit()` once. On any exception: `await session.rollback()` and raise `HTTPException(500, "import failed: ...")`.
   - After commit, `await session.refresh(topic)` for each created topic to populate generated columns, then collect IDs.
6. Return `ImportResult(dry_run=False, ..., created_topic_ids=[str(id) for id in ids])`.

Also add:
```python
async def get_material(session, topic_id: uuid.UUID) -> LearningMaterial | None
async def upsert_material(session, topic_id: uuid.UUID, body: MaterialUpdate) -> LearningMaterial
async def delete_material(session, topic_id: uuid.UUID) -> bool  # raises 404 if topic missing
def material_to_dict(m: LearningMaterial) -> dict[str, Any]
```

`upsert_material` — verify topic exists (404 if not), then either create new `LearningMaterial` or mutate existing one. Single `commit()` + `refresh()` per CLAUDE.md.

Update `load_tree`:
- Add `selectinload(LearningTopic.material)` to the query.
- `topic_to_dict()` always emits `has_material: bool = topic.material is not None` (avoids N+1 on the tree view; full material body is fetched separately by the detail page).

## Step 6 — Routes

In [src/api/routes/learning.py](src/api/routes/learning.py):

Imports: `LearningImportRequest`, `ImportResult`, `MaterialOut`, `MaterialUpdate`, `learning_import_limit`.

```python
@router.post("/v1/learning/import", response_model=ImportResult)
@limiter.limit(learning_import_limit)
async def import_curriculum(
    request: Request,
    body: LearningImportRequest,
    dry_run: bool = Query(default=False),
    session: AsyncSession = Depends(get_db),
) -> ImportResult:
    _require_enabled()
    return await learning_service.import_curriculum(session, body, dry_run=dry_run)
```

Material endpoints — all `topic_id: uuid.UUID` typed, all `@limiter.limit(learning_rate_limit)` (re-use existing 60/min):
- `GET /v1/learning/topics/{topic_id}/material` — use `response_model=MaterialOut | None`. Handler must `return None` explicitly when topic exists but has no material (FastAPI will error at serialization if `response_model=MaterialOut` and `None` is returned). Returns 404 if topic missing.
- `PATCH /v1/learning/topics/{topic_id}/material` — body `MaterialUpdate`. Creates if missing, updates if present. Returns `MaterialOut`.
- `DELETE /v1/learning/topics/{topic_id}/material?confirm=true` — mirrors existing delete pattern. Returns 204.

Existing `GET /v1/learning` already returns the tree; the `topic_to_dict` change in Step 5 adds `has_material` automatically.

## Step 7 — Backend tests

New file [tests/test_learning_import.py](tests/test_learning_import.py) (~10 tests, all `@pytest.mark.asyncio`):

1. `test_import_dry_run_writes_nothing` — POST with `dry_run=true`. Assert counts match payload AND `SELECT COUNT(*) FROM learning_topics` is unchanged.
2. `test_import_commits_full_tree` — single topic, 2 sections × 3 items + material. Assert rows persist with positions `0..N` in array order.
3. `test_import_skips_name_collision` — pre-create `LearningTopic(name="X")`, import `[{name:"X"}, {name:"Y"}]`. Result: `topics_created=1`, `topics_skipped=[{name:"X", reason:"name_collision"}]`. Existing X unchanged.
4. `test_import_skip_is_case_insensitive` — pre-create "Pgvector", import "pgvector". Skipped.
5. `test_import_material_optional` — topic without material: `materials_created=0`, GET material returns null body.
6. `test_import_rejects_malformed_json` — missing required `name` returns 422.
7. `test_import_rejects_empty_topics_list` — `topics: []` fails Pydantic `min_length=1`.
8. `test_import_atomicity_rolls_back_on_db_error` — monkeypatch `session.commit` (or one of the model `__init__`s) to raise; verify zero rows persisted.
9. `test_import_assigns_positions_in_array_order` — three sections in payload, assert `position=[0,1,2]`.
10. `test_import_rate_limit_5_per_minute` — fire 6 requests, the 6th returns 429. Use inline pattern (there is no `tests/test_rate_limits.py` in this repo).

Extend [tests/test_learning.py](tests/test_learning.py):
- `test_get_material_returns_null_when_absent`
- `test_patch_material_creates_then_updates`
- `test_delete_material_requires_confirm`
- `test_delete_topic_cascades_material` (delete topic, verify orphan material is gone)
- `test_get_tree_includes_has_material_flag`

## Step 8 — Frontend

### Types

[web/lib/types.ts](web/lib/types.ts) — extend:
- `LearningTopic` gains `has_material: boolean`
- New `LearningMaterial`, `LearningImportRequest`, `LearningImportResult`, `ImportSkip` types matching Pydantic shapes.

### Hook

[web/hooks/use-learning.ts](web/hooks/use-learning.ts) — add:
- `getMaterial(topicId)` → `GET /v1/learning/topics/{id}/material`
- `saveMaterial(topicId, body)` → `PATCH /v1/learning/topics/{id}/material`
- `deleteMaterial(topicId)` → `DELETE ...?confirm=true`
- `importCurriculum(json, { dryRun })` → `POST /v1/learning/import?dry_run=...`

Each follows the existing toast-on-error pattern.

### Markdown dependency

`cd web && npm install --save react-markdown@^9 remark-gfm@^4`.

If the install fails with peer dependency errors (Next.js 15 + React 19 can conflict with older peer declarations), add `--legacy-peer-deps`.

`react-markdown` v9 escapes raw HTML by default — do NOT add `rehype-raw`. Add a one-line comment at the renderer site explaining this is intentional.

### Shared section/item components

Refactor: extract `SectionBlock` and `ItemRow` from [web/app/learning/page.tsx](web/app/learning/page.tsx) into `web/app/learning/_components/section-block.tsx` and `web/app/learning/_components/item-row.tsx`. Both pages (tree + topic detail) reuse them. Pure code move, no behavior change. When extracting, make action callbacks (`onAddItem`, `onUpdateItem`) optional props (`?`) — the topic detail page renders sections read-only and won't supply them.

### Topic detail page

New: [web/app/learning/topics/[id]/page.tsx](web/app/learning/topics/[id]/page.tsx)

Layout (top to bottom):
1. **Header** — back link "← Library", topic name, depth badge, active toggle.
2. **Material panel** — heading "Material", body rendered via `react-markdown` + `remark-gfm`, contained in `<div class="max-h-[60vh] overflow-y-auto prose prose-sm dark:prose-invert">`. "Edit" button toggles a `<Textarea>` (must use class `text-base md:text-sm` per CLAUDE.md mobile-input rule). "Save" calls `saveMaterial`. "Delete" asks confirmation.
3. **Sections + items** — render the topic's sections using the shared `SectionBlock` component.
4. **Recent feedback** — a small panel at the bottom listing items where `feedback` is non-null, latest first.

Source the topic from the cached `useLearning()` tree (avoid an extra fetch). Material is fetched lazily on mount via `getMaterial`.

### Import page

New: [web/app/learning/import/page.tsx](web/app/learning/import/page.tsx)

Two-pane layout:
- **Left:** `<Textarea>` for JSON paste (monospace font, `text-base md:text-sm`, large height). Above it: link to `/docs/learning-import-template.md` ("View import template").
- **Right:** preview pane. Initially empty. After "Validate (dry run)" click → renders counts and skips (e.g. "Will create: 3 topics, 12 sections, 45 items, 3 materials. Skipped: 1 (name_collision: pgvector)"). On JSON parse error or 422, shows the error inline.
- Buttons: "Validate (dry run)" (always enabled), "Import" (disabled until a successful dry-run with non-zero `topics_created`).
- On successful import: toast `Imported {N} topics`, redirect to `/learning`.

### Tree view updates

[web/app/learning/page.tsx](web/app/learning/page.tsx):
- Wrap each topic title in `<Link href={`/learning/topics/${topic.id}`}>...</Link>`.
- When `topic.has_material`: render a small badge: `<span className="text-xs rounded-full px-2 py-0.5 bg-secondary/30">material</span>`.
- Header: add `<Button asChild variant="outline"><Link href="/learning/import">Import</Link></Button>` next to the existing "Refresh today" button.

### Frontend tests

None added — there is no Vitest coverage for `/learning` today. Note this gap explicitly in the PR description.

## Step 9 — Import template doc

New: [docs/learning-import-template.md](docs/learning-import-template.md)

Sections:
1. **Schema reference** — table of every field, type, required/optional, max length, allowed values for `depth` and `source_type`.
2. **Two examples**:
   - Minimal: 1 topic, 2 sections, 3 items each, no material.
   - Full: 1 topic with description, 3 sections, items, material with metadata.
3. **Copy-pasteable LLM prompt** — example block:
   ```
   You are a curriculum designer for the Open Brain Learning Library. Convert the source material below into a JSON document matching the schema. Output ONLY valid JSON, no prose, no code fences.

   Constraints:
   - 3-7 items per section, max
   - Item titles are concrete actions ("Read X", "Implement Y", "Compare A vs B")
   - depth = "foundational" for prerequisite/basics, "deep" otherwise
   - Preserve the source verbatim in topic.material.content
   - Do NOT include any "position" field; the server assigns positions

   Schema:
   <schema-here>

   Source material:
   <user_input>
   {paste your article/notes here}
   </user_input>
   ```
4. **Operational notes**: dedup is case-insensitive name match; safe to dry-run multiple times; max 50 topics per request, 20 sections per topic, 20 items per section.

## Step 10 — Verification (run locally before opening PR)

```bash
make lint && make test       # backend
cd web && npm test           # frontend (existing tests still pass)
```

End-to-end:
1. `alembic upgrade head` — confirm `0015` runs cleanly.
2. `make start` — bring up local stack.
3. Open `docs/learning-import-template.md`, copy prompt + a small real article into Claude.ai, paste returned JSON into `/learning/import`.
4. Click "Validate (dry run)" — verify counts match, no rows in DB (`psql ... -c "SELECT COUNT(*) FROM learning_topics"`).
5. Click "Import" — verify rows created, return to `/learning`, see new topic with the "material" badge.
6. Click topic title → `/learning/topics/{id}` — verify markdown renders with code blocks + lists.
7. Edit material, save, verify update persists.
8. Click "Refresh today" → verify learning todos appear in `/today` with the yellow "Learning" badge.
9. Complete one learning todo with `learning_feedback="just_right"` → verify `learning_items.status='done'` and feedback persisted on the topic detail page.
10. `DELETE /v1/learning/topics/{id}?confirm=true` → verify cascade removes material row.

## Risks & footguns (call out in PR body)

- **Large material content** — Postgres TEXT is unlimited, but rendering 100KB+ markdown will stutter on mobile. Fixed-height scrollable container only; do NOT chunk on first pass.
- **Markdown safety** — `react-markdown` v9 escapes raw HTML by default. Do NOT add `rehype-raw`. Comment beside the renderer to prevent regression.
- **Position auto-assignment** — schema deliberately rejects `position`. If a user supplies it the import returns 422. Document in `learning_import.py` module comment.
- **Dedup race** — two concurrent imports of the same name would both pass the pre-check. Acceptable for V1 (single-user app). A `UNIQUE INDEX ON lower(name)` would close it but conflicts with rename use-cases — defer.
- **Atomicity in SQLite tests** — SQLite supports nested transactions via savepoints. The atomicity test (#8) deliberately monkeypatches commit-time behavior; do not rely on it for assertions in other tests.
- **Memory sync** — material does NOT enter the memory pipeline. Confirmed by intentional absence of `learning_sync.py`. Do not add a sync helper.
- **One-to-one material** — unique constraint on `topic_id`. If multi-source per topic is needed later: drop unique, add `position` column. Note in `LEARNING.md` for future contributors.

## Out of scope (capture in [LEARNING.md](LEARNING.md) backlog section, or a new `docs/learning-backlog.md`)

- Quiz / "Test me on topic" flashcards over completed items
- In-app LLM curriculum generation (a "Generate from material" button)
- Re-import with merge semantics (current: skip-only)
- Bulk delete topics
- Multiple `learning_materials` rows per topic

## Critical files for the executor

| Layer | Path |
|---|---|
| Migration | [alembic/versions/0015_learning_materials.py](alembic/versions/0015_learning_materials.py) (new) |
| ORM | [src/core/models.py](src/core/models.py) (extend) |
| Schemas | [src/api/schemas/learning_import.py](src/api/schemas/learning_import.py) (new) |
| Service | [src/api/services/learning_service.py](src/api/services/learning_service.py) (extend) |
| Routes | [src/api/routes/learning.py](src/api/routes/learning.py) (extend) |
| Rate limit | [src/api/middleware/rate_limit.py](src/api/middleware/rate_limit.py) (extend) |
| Backend tests | [tests/test_learning_import.py](tests/test_learning_import.py) (new), [tests/test_learning.py](tests/test_learning.py) (extend) |
| Frontend hook | [web/hooks/use-learning.ts](web/hooks/use-learning.ts) (extend) |
| Frontend types | [web/lib/types.ts](web/lib/types.ts) (extend) |
| Tree view | [web/app/learning/page.tsx](web/app/learning/page.tsx) (extend) |
| Shared components | [web/app/learning/_components/section-block.tsx](web/app/learning/_components/section-block.tsx), [web/app/learning/_components/item-row.tsx](web/app/learning/_components/item-row.tsx) (new — refactor existing) |
| Detail page | [web/app/learning/topics/[id]/page.tsx](web/app/learning/topics/[id]/page.tsx) (new) |
| Import page | [web/app/learning/import/page.tsx](web/app/learning/import/page.tsx) (new) |
| Markdown deps | [web/package.json](web/package.json) (extend: `react-markdown@^9`, `remark-gfm@^4`) |
| Template doc | [docs/learning-import-template.md](docs/learning-import-template.md) (new) |

## Project conventions checklist (from CLAUDE.md — verify each is honored)

- [ ] Pydantic v2 syntax (`ConfigDict`, `@field_validator`)
- [ ] No module-level `from src.core.config import settings` — use `_get_settings()` if config accessed
- [ ] Every terminal DB op has `await session.commit()`
- [ ] `await session.refresh(obj)` after commit when reading server-default columns
- [ ] All new `/v1/*` routes have `@limiter.limit()`
- [ ] New `learning_materials` table has RLS enabled in migration (deny-all)
- [ ] JSONB columns use `.with_variant(JSON(), "sqlite")`
- [ ] Route params use `uuid.UUID` typing, not `str`
- [ ] All `<input>`, `<textarea>` use `text-base md:text-sm` (≥16px)
- [ ] User-supplied content (the JSON itself) does NOT need `<user_input>` wrapping because it's not fed to an in-app LLM. The external prompt template DOES wrap user material — that's a hygiene convention only the user controls.
- [ ] `MEMORY_TYPE` underscores convention — N/A (no new memory types)
- [ ] No `Base.metadata.create_all()` — alembic only
