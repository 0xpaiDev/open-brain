# Web Memory Chat — Implementation Plan

## Context

The Open Brain system has a working RAG pipeline used by both a Discord bot (`src/integrations/modules/rag_cog.py`) and a CLI chat command (`cli/ob.py:418-503`). The CLI `ob chat` is a "poor man's" version: it fetches context from `/v1/search/context` per turn, calls Claude/OpenAI directly, and optionally ingests the conversation. The web chat builds on this with query formulation, sources view, external context, and a proper UI.

Conversation state is client-side only (no DB persistence, no schema changes).

---

## Security Note: API Key in localStorage

**Current state:** All frontend pages already use `localStorage.getItem("ob_api_key")` → `X-API-Key` header (`web/lib/api.ts:1-6`, `web/components/auth-provider.tsx`). The chat page follows this same established pattern.

**Risk:** localStorage is readable by any JS on the page (XSS vector). If an attacker injects a script, they can exfiltrate the key.

**Mitigating factors for this project:**
- Single-user personal tool (not multi-tenant)
- Deployed behind Caddy TLS reverse proxy (HTTPS only)
- No third-party scripts or CDN-loaded JS — all code is first-party Next.js bundle
- Security headers already set: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security` (`src/api/main.py:50-58`)
- CORS restricted to `dashboard_origins` config

**Verdict:** Acceptable for MVP. A future enhancement could move to httpOnly cookie auth (requires backend changes to set/validate cookies instead of API key header), but this is out of scope and would affect all existing pages, not just chat.

---

## 1. Current State Summary

### Existing chat: `ob chat` CLI
- **File:** `cli/ob.py:418-503`
- Per-turn: calls `GET /v1/search/context?q=<user_message>` → injects context into system prompt → calls Claude/OpenAI
- No query formulation (embeds raw user message)
- No sources view (context is opaque)
- Optionally ingests full conversation to memory at session end
- Supports `--topic` for seed context, `--model claude|openai`, `--no-ingest`

### Backend
- **No `/v1/chat` HTTP endpoint exists** — only the CLI `ob chat` command
- RAG pipeline: `hybrid_search()` in `src/retrieval/search.py` → `build_context()` in `src/retrieval/context_builder.py` → `AnthropicClient.complete_with_history()` in `src/llm/client.py:116-171`
- Prompt helpers local to `src/integrations/modules/rag_cog.py:69-95` — `_build_system_prompt()`, `_build_rag_user_message()`
- `AnthropicClient.complete()` (single-turn, line 65) and `.complete_with_history()` (multi-turn, line 116) both accept `model` parameter
- `VoyageEmbeddingClient.embed()` returns 1024-dim vector
- Search route pattern: `src/api/routes/search.py:82-166` — creates clients per-request, calls hybrid_search, commits session
- Rate limit pattern: `src/api/middleware/rate_limit.py` — callable `_get_X_rate()` → exposed as `X_limit`

### Frontend
- `/chat` page: `web/app/chat/page.tsx` — stub rendering "Coming soon"
- API client: `web/lib/api.ts` — `api<T>(method, path, body)` with X-API-Key from localStorage
- Types: `web/lib/types.ts` — has `SearchResultItem` (reusable for sources)
- Hooks pattern: `web/hooks/use-memories.ts`
- UI: shadcn/ui — Dialog, Collapsible, Button, Input, Textarea, Select in `web/components/ui/`
- Sidebar already links to `/chat`

---

## 2. Backend Changes

### 2a. Extract shared prompts → `src/llm/rag_prompts.py` (new file)

Move from `rag_cog.py`:
- `_build_system_prompt(context)` → `build_rag_system_prompt(context, external_context=None)` — add optional `<external_context>` XML section
- `_build_rag_user_message(query)` → `build_rag_user_message(query)` — unchanged logic

Add new:
- `QUERY_FORMULATION_SYSTEM` constant — instructs Haiku to extract a concise search query from conversation + user message
- `build_query_formulation_content(history_tail, external_context_snippet, user_message)` — formats input for the formulation call

Then update `rag_cog.py` to import from new module and delete local functions.

### 2b. Add chat rate limiter → `src/api/middleware/rate_limit.py`

```python
def _get_chat_rate() -> str:
    return "30/minute"

chat_limit = _get_chat_rate
```

### 2c. Create chat endpoint → `src/api/routes/chat.py` (new file)

**Pydantic models:**

```python
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=8000)

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list)  # max 20 validated
    external_context: str | None = Field(default=None, max_length=20000)
    model: str = Field(default="claude-haiku-4-5-20251001")

class ChatSourceItem(BaseModel):
    id: str
    content: str
    summary: str | None
    type: str
    importance_score: float
    combined_score: float
    project: str | None = None

class ChatResponse(BaseModel):
    reply: str
    sources: list[ChatSourceItem]
    search_query: str
    model: str
    history_length: int
```

**Route handler flow (`POST /v1/chat`):**
1. Validate model against `{settings.rag_default_model, settings.rag_sonnet_model}`
2. Validate history length <= 20
3. Create AnthropicClient + VoyageEmbeddingClient per-request (same pattern as search route)
4. **Query formulation** — `AnthropicClient.complete()` with Haiku (always), using last 4 history items + truncated external_context (2000 chars) + `<user_input>` wrapped message. Fallback: raw message if formulation fails.
5. **Embed** formulated query via Voyage
6. **Search** via `hybrid_search(session, query_text, query_embedding, limit=5)`
7. **Build context** via `build_context(results)`
8. **Build system prompt** via `build_rag_system_prompt(context, external_context)`
9. **Build messages** — history (clean text) + current message wrapped in `<user_input>` tags
10. **Synthesis** — `complete_with_history(system_prompt, messages, model=body.model, max_tokens=2048)`
11. `await session.commit()` (for RetrievalEvents logged by hybrid_search)
12. Return `ChatResponse` with sources from search results

### 2d. Register router → `src/api/main.py`

Add `from src.api.routes.chat import router as chat_router` + `app.include_router(chat_router, tags=["Chat"])`.

---

## 3. Frontend Changes

### 3a. Types → `web/lib/types.ts`

```typescript
interface ChatMessage { role: "user" | "assistant"; content: string }
interface ChatSourceItem { id: string; content: string; summary: string | null; type: string; importance_score: number; combined_score: number; project: string | null }
interface ChatDisplayMessage { id: string; role: "user" | "assistant"; content: string; sources?: ChatSourceItem[]; searchQuery?: string }
interface ChatRequest { message: string; history: ChatMessage[]; external_context?: string; model: string }
interface ChatResponse { reply: string; sources: ChatSourceItem[]; search_query: string; model: string; history_length: number }
```

### 3b. Hook → `web/hooks/use-chat.ts`

State: `messages: ChatDisplayMessage[]`, `externalContext`, `model` (from localStorage `ob_chat_model`), `loading`, `error`

- `sendMessage(text)` — builds ChatRequest, calls `api<ChatResponse>("POST", "/v1/chat", body)`, appends user + assistant messages
- History truncation before API call: `.slice(-20)` (keep last 10 pairs)
- `resetChat()` — clears messages + external context (keeps model)
- `exchangeCount` — derived from messages

### 3c. Components → `web/components/chat/`

| Component | File | Description |
|---|---|---|
| `ModelSelector` | `model-selector.tsx` | shadcn Select, two options (Haiku/Sonnet), persists to localStorage |
| `ChatSources` | `chat-sources.tsx` | Collapsible per-message: type badge, content snippet (200 chars or summary), project, score |
| `ChatThread` | `chat-thread.tsx` | Scrollable message list, auto-scroll, user/assistant bubbles, "Searched for: ..." + ChatSources per assistant message |
| `ExternalContextPanel` | `external-context-panel.tsx` | Collapsible panel + Textarea, char count, clear button |
| `ChatInput` | `chat-input.tsx` | Textarea (Enter sends, Shift+Enter newline), send button, exchange counter, warning at 10+ |

### 3d. Page → `web/app/chat/page.tsx`

Replace stub. Layout: header (title + ModelSelector + Reset) → ChatThread (flex-grow) → ExternalContextPanel → ChatInput. `"use client"`, uses `useChat()` hook.

### 3e. Soft limit

- At 10 exchanges: yellow warning — "You've reached 10 exchanges. Answers may lose early context. Consider resetting."
- Send stays enabled (soft only)
- Reset clears messages + external context, resets counter, keeps model

---

## 4. Implementation Order (Session-Based)

### Session 1: Backend Foundation
| # | Task | Gate |
|---|---|---|
| 1 | Create `src/llm/rag_prompts.py` — extract prompts from rag_cog + add formulation prompt | Import works, functions return expected strings |
| 2 | Update `rag_cog.py` — import from new module, delete local functions | `make test` passes (existing RAG tests green) |
| 3 | Add `chat_limit` to `src/api/middleware/rate_limit.py` | Import works |
| 4 | Create `src/api/routes/chat.py` — full endpoint with Pydantic models | New file exists |
| 5 | Register router in `src/api/main.py` | `make start` → `/docs` shows POST `/v1/chat` |
| 6 | Write backend tests `tests/test_chat.py` | `make test` — all chat tests pass |

**Session 1 gate:** `make test` fully green, endpoint visible in Swagger docs.

### Session 2: Frontend Chat UI
| # | Task | Gate |
|---|---|---|
| 7 | Add chat types to `web/lib/types.ts` | `npm run build` succeeds |
| 8 | Create `web/hooks/use-chat.ts` | Hook exports, no TS errors |
| 9 | Create chat components: model-selector, chat-sources, chat-thread, external-context-panel, chat-input | Each component renders without errors |
| 10 | Implement `web/app/chat/page.tsx` — wire everything together | `npm run build` succeeds |
| 11 | Write frontend tests | `npm test` passes |

**Session 2 gate:** `npm run build` clean, `npm test` green, manual smoke test passes (Section 6).

---

## 5. Do Not Touch

- `src/core/models.py` — no schema changes, no new tables
- `alembic/versions/*` — no migrations
- `src/retrieval/search.py` — hybrid_search used as-is
- `src/retrieval/context_builder.py` — build_context used as-is
- `src/llm/client.py` — AnthropicClient + VoyageEmbeddingClient used as-is
- Discord bot behavior — only import path changes in rag_cog.py
- `src/api/routes/search.py` — untouched
- `cli/ob.py` — existing `ob chat` CLI untouched
- Auth middleware, CORS config — untouched (new route auto-protected)

---

## 6. End-to-End Smoke Test

**Prerequisites:** Backend running (`make start`), frontend running (`cd web && npm run dev`), valid API key in localStorage.

### Test 1: Basic chat
1. Navigate to `/chat`
2. Type "What projects have I been working on?" → Send
3. **Expect:** Loading indicator → assistant reply with "Searched for: ..." and collapsible "Sources (N)" → sources expand to show memory cards

### Test 2: Model switching
1. Switch selector to "Sonnet", send "Tell me more about the most important one"
2. **Expect:** Response uses Sonnet (verify `response.model` in Network tab). Follow-up resolves anaphora via history.

### Test 3: External context + follow-up
1. Expand external context panel, paste: "Meeting with Alex on 2026-03-15: Discussed migrating auth to OAuth2."
2. Ask: "Does this match any decisions I've recorded?"
3. **Expect:** Formulated search query targets auth/OAuth (not raw pasted text). Response references both memory + pasted context.
4. Follow-up: "What was the reasoning?" — works without re-pasting.

### Test 4: Soft limit
1. Send 10 messages → warning banner appears. Send button still works.

### Test 5: Reset
1. Click Reset → messages cleared, context cleared, counter resets, model unchanged.

### Test 6: Error handling
1. Stop backend (`make stop`), send a message → error displayed, no crash, no partial state.
