# External Services & API Calls

Quick reference — what calls external APIs, which key, which model, what triggers it.

**Update this file whenever you add or change an external API call.**

---

## Anthropic

Key: `ANTHROPIC_API_KEY` (env var) — pay-per-token.

| Consumer | File | Model (env var) | Default | Trigger |
|---|---|---|---|---|
| Chat (RAG path) | `src/api/routes/chat.py` | `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | User request to `/v1/chat` |
| Memory distillation | `src/jobs/synthesis.py` via worker | `SYNTHESIS_MODEL` | `claude-haiku-4-5-20251001` (**prod: `claude-opus-4-6`**) | Ingest queues item → worker picks up from `refinement_queue` |
| Learning daily job | `src/jobs/learning_daily.py` | `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | Scheduler (daily cron) |
| Voice intent extraction | `src/llm/voice_extractor.py` | `ANTHROPIC_MODEL` | `claude-haiku-4-5-20251001` | User voice request |
| Session-end ingest | `scripts/claude-code/session_end_ingest.py` | `OB_SESSION_END_HAIKU_MODEL` | `claude-haiku-4-5` | CC stop hook — **prefers CLI (subscription), falls back to API key** |

**Not on the API key (use `claude --print` → CC subscription):**

| Consumer | File | Model (env var) | Default | Trigger |
|---|---|---|---|---|
| Daily memory distill | `scripts/memory/run-distill.sh` | `OB_MEMORY_MODEL` | `claude-haiku-4-5` | Local cron + session-start hook |
| Weekly memory curate | `scripts/memory/run-curate.sh` | `OB_CURATE_MODEL` | `claude-sonnet-4-6` | Local cron (weekly) |

> Makefile targets `make memory-distill` and `make memory-curate` explicitly unset `ANTHROPIC_API_KEY` before calling these scripts so they never accidentally bill the API key.

---

## Voyage AI

Key: `VOYAGE_API_KEY` (env var) — pay-per-token.

| Consumer | File | Model (env var) | Default | Trigger |
|---|---|---|---|---|
| Embedding (all vector ops) | `src/llm/client.py` → `VoyageEmbeddingClient` | `VOYAGE_MODEL` | `voyage-3` | Any ingest, any hybrid search query |

Called on every `ingest_memory()` (to embed the new chunk) and every `/v1/search` or chat request that hits the RAG path (to embed the query).

---

## Strava

Auth: OAuth tokens in env (`STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_ACCESS_TOKEN`, `STRAVA_REFRESH_TOKEN`).

| Consumer | File | What | Trigger |
|---|---|---|---|
| Activity webhook | `src/api/routes/strava.py` | Receives push events from Strava | Strava POSTs to `/v1/strava/webhook` on new activity |
| Activity sync | `src/pipeline/training_sync.py` | Pulls activity data via Strava API | Webhook trigger → worker |

---

## Google Calendar

Auth: Service account credentials file (`GOOGLE_CALENDAR_CREDENTIALS_PATH`, `GOOGLE_CALENDAR_TOKEN_PATH`).

| Consumer | File | What | Trigger |
|---|---|---|---|
| Calendar sync | `src/integrations/calendar.py` | Reads calendar events | Pulse generation (`/v1/pulse`) |

---

## Supabase / PostgreSQL

Connection: `DATABASE_URL` (Supabase direct connection, port 5432 — **never port 6543 pooler**).

Not an "API call" per se but the only external data store. All ORM access goes through SQLAlchemy async sessions.

---

## Cost notes (as of 2026-05-24)

- **Opus 4.6 in prod synthesis** is the main variable cost driver. Each synthesis run on the `open-brain` key costs ~$0.05–0.10 depending on memory volume. Runs once per ingest batch.
- **Voyage embeddings** are very cheap (voyage-3 is ~$0.00006/1k tokens) — not worth optimising.
- **CC subscription** covers distill + curate scripts — zero API key cost.
