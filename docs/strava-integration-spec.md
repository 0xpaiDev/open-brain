# Strava Webhook Integration Spec

**Status**: Planned | **Author**: Shu + Claude | **Date**: 2026-03-25

---

## 1. Overview

Auto-ingest Strava activities as `memory_items` via webhook. When a new activity is uploaded to Strava, a webhook fires to our FastAPI server, which fetches the full activity data, generates a natural-language summary via Haiku, embeds it via Voyage AI, resolves entities (gear, location), and stores it as a searchable memory item. Training data becomes queryable alongside all other memories in the Open Brain knowledge system.

---

## 2. Architecture

### 2.1 Module Structure

| New File | Purpose |
|---|---|
| `src/integrations/strava.py` | Strava API client: OAuth token management, activity fetching, gear lookup with cache, token refresh |
| `src/pipeline/strava_processor.py` | Activity-to-memory conversion: Haiku summary, Voyage embedding, entity resolution, DB writes |
| `src/api/routes/strava.py` | 6 endpoints: OAuth authorize/callback, webhook GET/POST, status, backfill |
| `alembic/versions/0005_strava_tokens.py` | Migration: `strava_tokens` table + partial index on raw_memory |
| `tests/test_strava.py` | 24 test cases covering all endpoints and processing paths |

| Modified File | Change |
|---|---|
| `src/core/config.py` | Add 8 `STRAVA_*` settings to Settings class |
| `src/core/models.py` | Add `StravaToken` ORM model |
| `src/api/main.py` | Conditional router registration (feature flag) |
| `src/api/middleware/auth.py` | Add `/v1/strava/webhook` and `/v1/strava/callback` to `_PUBLIC_PATHS` |
| `src/api/middleware/rate_limit.py` | Add `_get_strava_rate()` callable and `strava_limit` export |
| `src/llm/prompts.py` | Add `STRAVA_ACTIVITY_SUMMARY_PROMPT` and `build_strava_activity_user_message()` |

### 2.2 Data Flow

```
Strava Activity Upload
        |
        v
POST /v1/strava/webhook (event: activity.create)
        |
        v  (return 200 immediately)
BackgroundTasks: process_strava_activity(activity_id, aspect_type)
        |
        v
1. Get valid token from DB (refresh if expired)
2. Fetch activity:  GET /api/v3/activities/{id}
3. Check idempotency: SELECT FROM raw_memory WHERE metadata_->>'strava_activity_id' = :id
4. Fetch gear name:  GET /api/v3/gear/{id}  (cached per gear_id)
5. Build metadata dict (SI units)
6. Call Haiku: structured data -> natural-language summary (JSON response)
7. Embed summary text via Voyage AI (1024-dim vector)
8. Build entity list: gear -> "tool", city -> "place"
9. Resolve entities via existing resolve_entities()
10. Create RawMemory  (source="strava", raw_text=summary, metadata_=structured_data)
11. Create MemoryItem  (type="memory", content=summary, base_importance=0.45)
12. Create MemoryEntityLinks
13. Commit
```

**Why bypass refinement_queue**: The worker extraction step converts free-text to structured JSON via LLM. Strava data is already structured — running it through extraction would be redundant. We still create `raw_memory` for the append-only audit log, preserving all structured data in `metadata_` for potential reprocessing.

**Why type="memory" not type="training"**: Adding a new type would require changes to search CTEs (`src/retrieval/search.py`), ranking, and the extraction prompt enum. Training data uses `type="memory"` with `source="strava"` and structured metadata in jsonb. The Haiku-generated `content` field embeds and searches naturally.

---

## 3. Schema Migrations

### 3.1 StravaToken Table

```sql
-- alembic/versions/0005_strava_tokens.py

CREATE TABLE strava_tokens (
    id              UUID PRIMARY KEY,
    athlete_id      INTEGER NOT NULL UNIQUE,
    access_token    TEXT NOT NULL,
    refresh_token   TEXT NOT NULL,
    expires_at      INTEGER NOT NULL,       -- Unix timestamp
    scope           VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

ORM model in `src/core/models.py`:

```python
class StravaToken(Base):
    __tablename__ = "strava_tokens"

    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    athlete_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    scope: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<StravaToken athlete_id={self.athlete_id} expires_at={self.expires_at}>"
```

**Security**: `__repr__` masks token values. Tokens are never logged. Supabase TDE encrypts at rest.

### 3.2 Partial Index for Strava Dedup

```sql
-- In same migration 0005
CREATE INDEX ix_raw_memory_strava_activity_id
    ON raw_memory ((metadata_->>'strava_activity_id'))
    WHERE source = 'strava';
```

Accelerates the idempotency check: `SELECT id FROM raw_memory WHERE source='strava' AND metadata_->>'strava_activity_id' = :id`.

**Alternatives considered**: (a) GIN index on full metadata_ — too broad, adds write overhead for all sources; (b) new column on raw_memory — violates "no columns for single-integration concerns" principle; (c) content_hash — unsuitable because same activity can produce different summaries on re-generation.

---

## 4. API Endpoints

### 4.1 Route Signatures

```python
# src/api/routes/strava.py
router = APIRouter()

# --- Public endpoints (no X-API-Key) ---

@router.get("/v1/strava/webhook")
async def validate_webhook(
    request: Request,
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
) -> dict:
    """Strava subscription validation. Returns hub.challenge if verify_token matches."""
    # 200 with {"hub.challenge": challenge} or 403

@router.post("/v1/strava/webhook", status_code=200)
@limiter.limit(strava_limit)
async def handle_webhook(
    request: Request,
    event: StravaWebhookEvent,
    background_tasks: BackgroundTasks,
) -> dict:
    """Receive Strava event notification. Returns 200 immediately; processes in background."""
    # Verify subscription_id + owner_id
    # Dispatch to BackgroundTasks based on aspect_type

@router.get("/v1/strava/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(...),
    scope: str = Query(""),
    state: str = Query(""),
    session: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    """OAuth2 callback. Exchanges code for tokens. State-verified (CSRF protection)."""
    # Verify state HMAC, exchange code, upsert strava_tokens row

# --- Protected endpoints (X-API-Key required) ---

@router.get("/v1/strava/authorize")
@limiter.limit(strava_limit)
async def initiate_oauth(request: Request) -> RedirectResponse:
    """Redirect to Strava OAuth page. Requires X-API-Key."""

@router.get("/v1/strava/status", response_model=StravaStatusResponse)
@limiter.limit(strava_limit)
async def get_status(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> StravaStatusResponse:
    """Integration health: token expiry, last activity ingested, subscription status."""

@router.post("/v1/strava/backfill", status_code=202)
@limiter.limit(strava_limit)
async def backfill_activities(
    request: Request,
    body: BackfillRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Import historical activities. Paginated, rate-aware. Runs in background."""
```

### 4.2 Request/Response Schemas

```python
class StravaWebhookEvent(BaseModel):
    """Strava webhook POST body."""
    aspect_type: str              # "create", "update", "delete"
    event_time: int               # Unix timestamp
    object_id: int                # Activity ID
    object_type: str              # "activity" or "athlete"
    owner_id: int                 # Strava athlete ID
    subscription_id: int          # Must match STRAVA_SUBSCRIPTION_ID
    updates: dict = {}

class StravaStatusResponse(BaseModel):
    """GET /v1/strava/status response."""
    connected: bool
    athlete_id: int | None
    token_expires_at: int | None
    token_expired: bool
    last_activity_ingested: datetime | None
    total_activities_ingested: int

class BackfillRequest(BaseModel):
    """POST /v1/strava/backfill request."""
    after: str = Field(..., description="ISO 8601 date, e.g. 2026-01-01")
    before: str | None = Field(None, description="ISO 8601 date, defaults to now")
    sport_types: list[str] = Field([], description="Filter by sport type, empty=all")
```

---

## 5. Processing Pipeline

### 5.1 Create Flow (`aspect_type="create"`)

```python
async def _handle_create(activity_id: int) -> None:
    """Process a new Strava activity into a memory item."""
    async with get_db_context() as session:
        # 1. Idempotency check
        existing = await session.execute(
            select(RawMemory.id)
            .where(RawMemory.source == "strava")
            .where(RawMemory.metadata_["strava_activity_id"].as_string() == str(activity_id))
            .limit(1)
        )
        if existing.scalar_one_or_none():
            logger.info("strava_activity_already_ingested", activity_id=activity_id)
            return

        # 2. Fetch activity + gear from Strava API
        client = StravaClient(session)
        await client.ensure_valid_token()
        activity = await client.fetch_activity(activity_id)
        gear_name = await client.fetch_gear(activity.get("gear_id")) if activity.get("gear_id") else None

        # 3. Check sport type allowlist
        settings = get_settings()
        if settings.strava_sport_types and activity["sport_type"] not in settings.strava_sport_types:
            logger.info("strava_activity_filtered", sport_type=activity["sport_type"])
            return

        # 4. Build metadata
        metadata = _build_metadata(activity, gear_name)

        # 5. Generate summary via Haiku
        anthropic = AnthropicClient(...)
        user_msg = build_strava_activity_user_message(metadata)
        response = await anthropic.complete(STRAVA_ACTIVITY_SUMMARY_PROMPT, user_msg)
        parsed = json.loads(response)
        content = parsed["content"]
        summary = parsed["summary"]

        # 6. Embed summary
        voyage = VoyageEmbeddingClient(...)
        embedding = await embed_text(content, client=voyage)

        # 7. Resolve entities
        entities_extract = _build_entities(metadata)
        entities = await resolve_entities(session, entities_extract)

        # 8. Create RawMemory (audit log)
        raw = RawMemory(
            source="strava",
            raw_text=content,
            metadata_=metadata,
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
        )
        session.add(raw)
        await session.flush()

        # 9. Create MemoryItem
        memory_item = MemoryItem(
            raw_id=raw.id,
            type="memory",
            content=content,
            summary=summary,
            base_importance=settings.strava_default_importance,
            embedding=embedding,
        )
        session.add(memory_item)
        await session.flush()

        # 10. Create entity links
        for entity in entities:
            link = MemoryEntityLink(memory_id=memory_item.id, entity_id=entity.id)
            session.add(link)

        await session.commit()
        logger.info("strava_activity_ingested", activity_id=activity_id, memory_id=str(memory_item.id))
```

### 5.2 Update Flow (`aspect_type="update"`)

```python
async def _handle_update(activity_id: int) -> None:
    """Handle updated activity. Creates new memory_item with supersedes_id."""
    async with get_db_context() as session:
        # Find existing raw_memory + memory_item
        result = await session.execute(
            select(RawMemory)
            .where(RawMemory.source == "strava")
            .where(RawMemory.metadata_["strava_activity_id"].as_string() == str(activity_id))
            .order_by(RawMemory.created_at.desc())
            .limit(1)
        )
        existing_raw = result.scalar_one_or_none()
        if not existing_raw:
            # Never seen this activity — treat as create
            await _handle_create(activity_id)
            return

        # Find linked memory_item
        result = await session.execute(
            select(MemoryItem).where(MemoryItem.raw_id == existing_raw.id).limit(1)
        )
        existing_memory = result.scalar_one_or_none()

        # Re-fetch activity from Strava, rebuild everything
        # ... (same as create flow but with supersedes_id)

        new_memory = MemoryItem(
            raw_id=new_raw.id,
            type="memory",
            content=content,
            summary=summary,
            base_importance=settings.strava_default_importance,
            embedding=embedding,
            supersedes_id=existing_memory.id if existing_memory else None,
        )

        if existing_memory:
            existing_memory.is_superseded = True

        await session.commit()
```

### 5.3 Delete Flow (`aspect_type="delete"`)

```python
async def _handle_delete(activity_id: int) -> None:
    """Mark memory as superseded when activity is deleted on Strava."""
    async with get_db_context() as session:
        result = await session.execute(
            select(RawMemory)
            .where(RawMemory.source == "strava")
            .where(RawMemory.metadata_["strava_activity_id"].as_string() == str(activity_id))
        )
        raw_rows = result.scalars().all()
        for raw in raw_rows:
            result = await session.execute(
                select(MemoryItem).where(MemoryItem.raw_id == raw.id)
            )
            for memory in result.scalars().all():
                memory.is_superseded = True

        await session.commit()
        logger.info("strava_activity_deleted", activity_id=activity_id)
```

---

## 6. Haiku Prompt Template

```python
# Added to src/llm/prompts.py

STRAVA_ACTIVITY_SUMMARY_PROMPT = """You summarize fitness activities for a personal knowledge system.

Given structured activity data, write a factual 2-4 sentence summary in natural language.

Include (when available):
- Sport type and distance, with location if known
- Moving time and average speed (km/h for cycling, min/km for running)
- Power data (normalized/weighted power preferred over average)
- Heart rate (average)
- Elevation gain if >100m
- Gear name
- PRs/achievements
- Indoor/trainer flag

Use metric units. Round sensibly (1 decimal for speed, whole numbers for HR/watts/elevation).
Be factual and concise. No editorializing or motivational language.

Respond with ONLY valid JSON:
{
  "summary": "One-sentence headline",
  "content": "Full 2-4 sentence summary"
}"""


def build_strava_activity_user_message(metadata: dict) -> str:
    """Wrap structured activity data for Haiku extraction."""
    return f"<user_input>{json.dumps(metadata, indent=2)}</user_input>"
```

**Example input** (metadata dict):
```json
{
  "sport_type": "Ride",
  "distance_m": 65000.0,
  "moving_time_s": 8100,
  "total_elevation_gain_m": 800.0,
  "average_speed_mps": 8.02,
  "weighted_average_watts": 185,
  "average_heartrate": 155,
  "gear_name": "Canyon Aeroad",
  "city": "Kaunas",
  "pr_count": 3,
  "trainer": false
}
```

**Example output**:
```json
{
  "summary": "65km road ride near Kaunas with 800m climbing",
  "content": "65km road ride near Kaunas with 800m of elevation gain. 2h15m moving time at 28.9 km/h average, 185W normalized power. Average HR 155bpm. Used Canyon Aeroad. 3 PRs achieved."
}
```

---

## 7. Entity Mapping Rules

| Source Data | Entity? | Entity Type | Dedup Rule |
|---|---|---|---|
| `gear_name` (e.g., "Canyon Aeroad") | Yes | `tool` | Exact name match via `resolve_entities()` alias path |
| `city` (e.g., "Kaunas") | Yes | `place` | Exact name match via `resolve_entities()` alias path |
| `sport_type` (e.g., "Ride") | No | -- | Too generic; stored in metadata for filtering |
| `activity_name` | No | -- | User-entered, often generic ("Morning Ride"); too noisy |

Entity construction in processor:

```python
def _build_entities(metadata: dict) -> list[EntityExtract]:
    """Build entity list from activity metadata."""
    entities: list[EntityExtract] = []
    if metadata.get("gear_name"):
        entities.append(EntityExtract(name=metadata["gear_name"], type="tool"))
    if metadata.get("city"):
        entities.append(EntityExtract(name=metadata["city"], type="place"))
    return entities
```

Entities pass through existing `resolve_entities()` (exact alias match -> fuzzy match -> create new). This ensures "Kaunas" is linked to the same entity whether it came from Strava or a typed memory.

---

## 8. OAuth2 Flow

### 8.1 Setup Instructions

1. Create a Strava API application at https://www.strava.com/settings/api
2. Set Authorization Callback Domain to your server domain
3. Note Client ID and Client Secret
4. Set env vars:
   ```
   STRAVA_CLIENT_ID=12345
   STRAVA_CLIENT_SECRET=abc123...
   STRAVA_VERIFY_TOKEN=random-string-you-choose
   STRAVA_WEBHOOK_ENABLED=true
   ```

### 8.2 Authorization Flow

```
User -> GET /v1/strava/authorize (with X-API-Key)
     -> 302 redirect to https://www.strava.com/oauth/authorize
          ?client_id={STRAVA_CLIENT_ID}
          &redirect_uri={server}/v1/strava/callback
          &response_type=code
          &scope=read,activity:read_all
          &state={hmac_nonce}
     -> User authorizes on Strava
     -> Strava redirects to GET /v1/strava/callback?code=xxx&state=xxx
     -> Server verifies state, exchanges code:
          POST https://www.strava.com/oauth/token
          {client_id, client_secret, code, grant_type: "authorization_code"}
     -> Receives: {access_token, refresh_token, expires_at, athlete}
     -> Upserts strava_tokens row
     -> Returns success HTML page
```

### 8.3 Token Lifecycle

```python
class StravaClient:
    STRAVA_API_BASE = "https://www.strava.com/api/v3"
    TOKEN_URL = "https://www.strava.com/oauth/token"

    def __init__(self, session: AsyncSession):
        self._session = session
        self._http = httpx.AsyncClient(timeout=30.0)
        self._gear_cache: dict[str, str] = {}  # gear_id -> name

    async def _ensure_valid_token(self) -> str:
        """Return a valid access token, refreshing if expired."""
        token_row = await self._session.execute(
            select(StravaToken).limit(1)
        )
        token = token_row.scalar_one_or_none()
        if not token:
            raise StravaAPIError("No Strava token configured. Complete OAuth flow first.")

        if token.expires_at < time.time() + 300:  # 5-minute buffer
            # Refresh
            settings = get_settings()
            resp = await self._http.post(self.TOKEN_URL, data={
                "client_id": settings.strava_client_id,
                "client_secret": settings.strava_client_secret.get_secret_value(),
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            })
            if resp.status_code != 200:
                logger.error("strava_token_refresh_failed", status=resp.status_code)
                raise StravaAPIError(f"Token refresh failed: {resp.status_code}")

            data = resp.json()
            token.access_token = data["access_token"]
            token.refresh_token = data["refresh_token"]
            token.expires_at = data["expires_at"]
            await self._session.flush()
            await self._session.commit()
            await self._session.refresh(token)

        return token.access_token
```

### 8.4 Webhook Subscription Setup

One-time setup after OAuth is complete:

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -d client_id=$STRAVA_CLIENT_ID \
  -d client_secret=$STRAVA_CLIENT_SECRET \
  -d callback_url=https://your-server.com/v1/strava/webhook \
  -d verify_token=$STRAVA_VERIFY_TOKEN
```

Strava sends a GET to `/v1/strava/webhook` with `hub.verify_token` for validation. On success, returns a `subscription_id`. Store it as `STRAVA_SUBSCRIPTION_ID` in `.env`.

---

## 9. Configuration

Add to `Settings` class in `src/core/config.py`:

```python
# ── Strava Integration ──────────────────────────────────────────────────
strava_client_id: str = ""
strava_client_secret: SecretStr = SecretStr("")
strava_verify_token: str = ""            # webhook subscription validation
strava_subscription_id: int = 0          # known subscription ID for POST verification
strava_webhook_enabled: bool = False     # feature flag — routes not registered when false
strava_default_importance: float = 0.45  # base_importance for activity memories
strava_rate_limit_per_minute: int = 30   # rate limit on webhook + other strava endpoints
strava_sport_types: list[str] = []       # empty = all types; non-empty = allowlist
```

| Env Var | Type | Required | Default | Purpose |
|---|---|---|---|---|
| `STRAVA_CLIENT_ID` | str | Yes (if enabled) | `""` | Strava API app client ID |
| `STRAVA_CLIENT_SECRET` | SecretStr | Yes (if enabled) | `""` | Strava API app secret (never logged) |
| `STRAVA_VERIFY_TOKEN` | str | Yes (if enabled) | `""` | Random string for webhook subscription validation |
| `STRAVA_SUBSCRIPTION_ID` | int | Yes (if enabled) | `0` | Subscription ID returned by Strava on subscription creation |
| `STRAVA_WEBHOOK_ENABLED` | bool | No | `false` | Feature flag. When false, strava routes are not registered. |
| `STRAVA_DEFAULT_IMPORTANCE` | float | No | `0.45` | base_importance assigned to activity memories (0.0-1.0) |
| `STRAVA_RATE_LIMIT_PER_MINUTE` | int | No | `30` | Rate limit on all Strava endpoints |
| `STRAVA_SPORT_TYPES` | list[str] | No | `[]` (all) | Allowlist. Example: `["Ride","Run","Swim"]` |

**Feature flag behavior**: When `strava_webhook_enabled=false`, the strava router is not included in the FastAPI app (conditional `app.include_router()` in `main.py`). Endpoints don't exist — they return 404, not a feature-disabled error.

---

## 10. Test Plan

All tests in `tests/test_strava.py`. Pytest + pytest-asyncio. SQLite in-memory DB. All external APIs mocked.

### 10.1 Test Fixtures

```python
@pytest.fixture
def strava_activity_payload() -> dict:
    """Complete Strava activity API response."""
    return {
        "id": 12345678, "name": "Morning ride", "sport_type": "Ride",
        "distance": 65000.0, "moving_time": 8100, "elapsed_time": 9200,
        "total_elevation_gain": 800.0, "average_speed": 8.02, "max_speed": 14.5,
        "average_heartrate": 155, "max_heartrate": 182,
        "average_watts": 175, "weighted_average_watts": 185,
        "kilojoules": 1417.5, "suffer_score": 120, "average_cadence": 88,
        "calories": 1200, "gear_id": "b12345", "device_name": "Garmin Edge 540",
        "start_date": "2026-03-25T04:30:00Z",
        "start_date_local": "2026-03-25T07:30:00",
        "timezone": "(GMT+03:00) Europe/Vilnius",
        "start_latlng": [54.89, 23.93], "end_latlng": [54.89, 23.93],
        "trainer": False, "commute": False,
        "pr_count": 3, "achievement_count": 5,
        "description": "Felt strong today",
        "map": {"summary_polyline": "..."},
    }

@pytest.fixture
def strava_gear_payload() -> dict:
    return {"id": "b12345", "name": "Canyon Aeroad", "distance": 15000000}

@pytest.fixture
def strava_webhook_create_event() -> dict:
    return {
        "aspect_type": "create", "event_time": 1711350000,
        "object_id": 12345678, "object_type": "activity",
        "owner_id": 99999, "subscription_id": 55555, "updates": {},
    }

@pytest.fixture
def strava_webhook_update_event() -> dict:
    return {
        "aspect_type": "update", "event_time": 1711350100,
        "object_id": 12345678, "object_type": "activity",
        "owner_id": 99999, "subscription_id": 55555,
        "updates": {"title": "Updated ride name"},
    }

@pytest.fixture
def strava_webhook_delete_event() -> dict:
    return {
        "aspect_type": "delete", "event_time": 1711350200,
        "object_id": 12345678, "object_type": "activity",
        "owner_id": 99999, "subscription_id": 55555, "updates": {},
    }

@pytest.fixture
def strava_token_row(async_session) -> StravaToken:
    """Insert a valid StravaToken row for tests."""
    token = StravaToken(
        athlete_id=99999,
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=int(time.time()) + 3600,  # 1 hour from now
        scope="read,activity:read_all",
    )
    async_session.add(token)
    # flush + commit in test body
    return token

@pytest.fixture
def mock_strava_http():
    """Mock httpx.AsyncClient for Strava API calls."""
    with patch("src.integrations.strava.httpx.AsyncClient") as mock:
        yield mock
```

### 10.2 Test Cases

| ID | Name | Category | What It Tests |
|---|---|---|---|
| T01 | `test_webhook_get_valid_verify_token` | unit | Hub.challenge returned when verify_token matches |
| T02 | `test_webhook_get_invalid_verify_token` | unit | 403 when verify_token doesn't match |
| T03 | `test_webhook_post_create_processes_activity` | integration | Full create flow: webhook -> fetch -> summarize -> embed -> store |
| T04 | `test_webhook_post_rejects_unknown_subscription_id` | unit | Returns 200 but no processing when subscription_id doesn't match |
| T05 | `test_webhook_post_rejects_unknown_owner_id` | unit | Returns 200 but no processing when owner_id doesn't match athlete_id |
| T06 | `test_webhook_post_ignores_non_activity` | unit | Returns 200, no processing for object_type="athlete" |
| T07 | `test_webhook_post_idempotent_duplicate` | integration | Second webhook for same activity_id creates no new rows |
| T08 | `test_webhook_post_update_supersedes` | integration | Update creates new memory_item with supersedes_id, marks original is_superseded |
| T09 | `test_webhook_post_delete_marks_superseded` | integration | Delete marks memory_item.is_superseded=true, no rows deleted |
| T10 | `test_token_refresh_on_expired` | unit | Expired token triggers refresh API call, DB row updated |
| T11 | `test_token_refresh_failure_handled` | unit | Refresh 401 -> error logged, no crash, no memory_item |
| T12 | `test_activity_fetch_404_handled` | unit | Strava 404 -> logged, no crash |
| T13 | `test_activity_fetch_500_retried` | unit | 500 on first 2 attempts, success on 3rd |
| T14 | `test_haiku_summary_generation` | unit | Mock Anthropic returns valid JSON, content + summary populated |
| T15 | `test_entity_extraction_gear_and_city` | integration | Gear -> tool entity, city -> place entity, links created |
| T16 | `test_metadata_jsonb_structure` | unit | All expected keys, correct types in raw_memory.metadata_ |
| T17 | `test_memory_item_fields_correct` | integration | type="memory", base_importance=0.45, embedding 1024-dim |
| T18 | `test_sport_type_filtering` | unit | Activity filtered out when sport_type not in allowlist |
| T19 | `test_backfill_pagination` | integration | Two pages processed, rate limit sleep called between |
| T20 | `test_status_endpoint` | unit | Returns token_expires_at, connected status, activity count |
| T21 | `test_webhook_no_api_key_required` | unit | GET/POST /v1/strava/webhook succeed without X-API-Key |
| T22 | `test_protected_endpoints_require_api_key` | unit | GET /status, POST /backfill return 401 without key |
| T23 | `test_webhook_rate_limiting` | unit | 31st request in 1 minute returns 429 |
| T24 | `test_gear_cache_avoids_duplicate_calls` | unit | Two activities with same gear_id -> one gear API call |

### 10.3 Test Details

**T01** — `test_webhook_get_valid_verify_token`
```python
async def test_webhook_get_valid_verify_token(test_client, monkeypatch):
    monkeypatch.setenv("STRAVA_VERIFY_TOKEN", "test-token")
    monkeypatch.setenv("STRAVA_WEBHOOK_ENABLED", "true")
    resp = test_client.get(
        "/v1/strava/webhook",
        params={"hub.mode": "subscribe", "hub.challenge": "abc123", "hub.verify_token": "test-token"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"hub.challenge": "abc123"}
```

**T07** — `test_webhook_post_idempotent_duplicate`
```python
async def test_webhook_post_idempotent_duplicate(
    test_client, async_session, strava_webhook_create_event, api_key_headers, monkeypatch
):
    # Pre-insert raw_memory with matching strava_activity_id
    raw = RawMemory(
        source="strava",
        raw_text="existing activity",
        metadata_={"strava_activity_id": 12345678},
    )
    async_session.add(raw)
    await async_session.commit()

    # Post webhook — should NOT create duplicate
    resp = test_client.post("/v1/strava/webhook", json=strava_webhook_create_event)
    assert resp.status_code == 200

    # Verify no new raw_memory created
    result = await async_session.execute(
        select(func.count()).where(RawMemory.source == "strava")
    )
    assert result.scalar() == 1  # Still just the one we inserted
```

**T15** — `test_entity_extraction_gear_and_city`
```python
async def test_entity_extraction_gear_and_city(async_session, mock_anthropic_client, mock_voyage_client):
    metadata = {"gear_name": "Canyon Aeroad", "city": "Kaunas", "sport_type": "Ride"}
    entities_extract = _build_entities(metadata)

    assert len(entities_extract) == 2
    assert entities_extract[0].name == "Canyon Aeroad"
    assert entities_extract[0].type == "tool"
    assert entities_extract[1].name == "Kaunas"
    assert entities_extract[1].type == "place"

    # Resolve through real resolve_entities
    entities = await resolve_entities(async_session, entities_extract)
    assert len(entities) == 2
    await async_session.commit()

    # Verify entities in DB
    result = await async_session.execute(select(Entity))
    db_entities = result.scalars().all()
    assert len(db_entities) == 2
    names = {e.name for e in db_entities}
    assert names == {"Canyon Aeroad", "Kaunas"}
```

---

## 11. Known Limitations

1. **Single-user only** — `strava_tokens` has `UNIQUE(athlete_id)` but no user FK. Clean design allows multi-tenant extension if needed later.

2. **Backfill rate constraints** — Strava allows 200 requests per 15 minutes. With 1 activity fetch + 1 gear lookup per activity, backfill processes ~13 activities/minute. 1000 historical activities take ~80 minutes. One-time cost; progress is logged.

3. **BackgroundTasks not durable** — If the API container restarts between webhook receipt and processing completion, the in-flight activity is lost. Strava retries failed webhooks for ~24 hours, providing adequate coverage for single-user volume.

4. **Tokens stored in plaintext** — Mitigated by Supabase Transparent Data Encryption at rest, `__repr__` masking in ORM, and structlog never logging token values. Acceptable for self-hosted single-user system.

5. **No Discord notification on ingestion** — User has no real-time visibility that an activity was ingested. Deferred to follow-up: a `strava_cog.py` could post an embed to a Discord channel on successful ingestion.

6. **No polyline/map storage** — Strava's `map.summary_polyline` is not stored or rendered. Could be added to metadata later if map visualization is desired.

7. **City comes from Strava, not reverse geocoding** — Strava provides city/state/country in the activity response for most activities. If missing (indoor trainer, GPS issues), no location entity is created. No external geocoding API is used.

---

## 12. Implementation Order

| Step | Files | Size | Dependencies |
|---|---|---|---|
| 1. Config | `src/core/config.py` | S | None |
| 2. Schema + Migration | `src/core/models.py`, `alembic/versions/0005_strava_tokens.py` | S | Step 1 |
| 3. Strava API Client | `src/integrations/strava.py` | M | Steps 1-2 |
| 4. Prompt | `src/llm/prompts.py` | S | None |
| 5. Processor | `src/pipeline/strava_processor.py` | M | Steps 1-4 |
| 6. Routes | `src/api/routes/strava.py` | M | Steps 1-5 |
| 7. Auth + Rate Limit + Registration | `auth.py`, `rate_limit.py`, `main.py` | S | Step 6 |
| 8. Tests | `tests/test_strava.py` | L | Steps 1-7 |
| 9. Spec Document | `docs/strava-integration-spec.md` | S | All above (this document) |

---

## 13. Dependencies

### Python Packages

| Package | Purpose | Status |
|---|---|---|
| `httpx` | HTTP client for Strava API calls | Already in deps |
| No new packages required | | |

`stravalib` was considered but rejected — raw `httpx` is cleaner for our limited API surface (3 endpoints: activity, gear, token exchange). Avoids a dependency that wraps a simple REST API.

### Environment Variables (New)

```bash
# Required when STRAVA_WEBHOOK_ENABLED=true
STRAVA_CLIENT_ID=12345
STRAVA_CLIENT_SECRET=your-client-secret
STRAVA_VERIFY_TOKEN=random-string-you-choose
STRAVA_SUBSCRIPTION_ID=55555

# Optional
STRAVA_WEBHOOK_ENABLED=true
STRAVA_DEFAULT_IMPORTANCE=0.45
STRAVA_RATE_LIMIT_PER_MINUTE=30
STRAVA_SPORT_TYPES=["Ride","Run"]
```

### External Services

| Service | Purpose | Setup Required |
|---|---|---|
| Strava API Application | OAuth2 + webhooks | Create at https://www.strava.com/settings/api |
| Caddy (existing) | HTTPS termination for webhook endpoint | Already deployed; must be publicly accessible |

---

## Appendix A: Metadata JSONB Field Reference

All fields stored in `raw_memory.metadata_` for Strava activities. Fields are nullable — only present if Strava provides them for the activity type.

| Key | Type | Unit | Source | Notes |
|---|---|---|---|---|
| `strava_activity_id` | int | — | `activity.id` | Primary dedup key |
| `sport_type` | str | — | `activity.sport_type` | "Ride", "Run", "Swim", etc. |
| `distance_m` | float | meters | `activity.distance` | |
| `moving_time_s` | int | seconds | `activity.moving_time` | |
| `elapsed_time_s` | int | seconds | `activity.elapsed_time` | |
| `total_elevation_gain_m` | float | meters | `activity.total_elevation_gain` | |
| `average_speed_mps` | float | m/s | `activity.average_speed` | |
| `max_speed_mps` | float | m/s | `activity.max_speed` | |
| `average_heartrate` | int | bpm | `activity.average_heartrate` | Only if HR monitor |
| `max_heartrate` | int | bpm | `activity.max_heartrate` | |
| `average_watts` | int | W | `activity.average_watts` | Only if power meter |
| `weighted_average_watts` | int | W | `activity.weighted_average_watts` | Normalized power |
| `kilojoules` | float | kJ | `activity.kilojoules` | |
| `suffer_score` | int | — | `activity.suffer_score` | Strava's effort metric |
| `average_cadence` | int | rpm | `activity.average_cadence` | |
| `calories` | int | kcal | `activity.calories` | |
| `gear_name` | str | — | `gear.name` (separate API call) | Null if no gear_id |
| `gear_id` | str | — | `activity.gear_id` | |
| `start_latlng` | list[float] | [lat, lng] | `activity.start_latlng` | |
| `city` | str | — | `activity.location_city` | |
| `country` | str | — | `activity.location_country` | |
| `achievement_count` | int | — | `activity.achievement_count` | |
| `pr_count` | int | — | `activity.pr_count` | |
| `start_date_local` | str | ISO 8601 | `activity.start_date_local` | |
| `timezone` | str | — | `activity.timezone` | |
| `activity_name` | str | — | `activity.name` | User-entered |
| `description` | str | — | `activity.description` | User-entered |
| `has_heartrate` | bool | — | `activity.has_heartrate` | |
| `has_power` | bool | — | `activity.device_watts` | |
| `trainer` | bool | — | `activity.trainer` | Indoor flag |
| `commute` | bool | — | `activity.commute` | |

## Appendix B: Strava Sport Types Reference

Common `sport_type` values from the Strava API:

- Cycling: `Ride`, `MountainBikeRide`, `GravelRide`, `EBikeRide`, `VirtualRide`
- Running: `Run`, `TrailRun`, `VirtualRun`
- Swimming: `Swim`
- Other: `Walk`, `Hike`, `AlpineSki`, `NordicSki`, `Rowing`, `Kayaking`, `WeightTraining`, `Yoga`, `Workout`

Use `STRAVA_SPORT_TYPES` env var to filter. Empty = ingest all types.
