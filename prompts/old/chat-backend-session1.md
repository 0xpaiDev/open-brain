# Web Memory Chat — Backend Foundation (Session 1) — Multi-Agent

You will work through this task in five roles, sequentially. Do not skip ahead.
The goal: A fully functional `POST /v1/chat` endpoint that performs query formulation, RAG search, and multi-turn synthesis — with shared prompt utilities extracted from the Discord bot and comprehensive tests.

---

## Business context (read once, then put on your shelf)

Open Brain is a personal memory system with a RAG pipeline. It currently serves chat through a Discord bot (`src/integrations/modules/rag_cog.py`) and a CLI command (`cli/ob.py`), but has no HTTP chat endpoint. The web dashboard at `/chat` is a stub. This session builds the backend half: extracting shared prompt logic into a reusable module, creating the `/v1/chat` endpoint with query formulation (reformulating the user message into a better search query via Haiku), and wiring it into the existing FastAPI app. Conversation state is client-side only — no DB schema changes, no migrations.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it.

Find and read:
- `src/integrations/modules/rag_cog.py` — specifically `_build_system_prompt(context)` and `_build_rag_user_message(query)` (around lines 69-95). Understand exactly what they produce and how the Discord bot uses them in `_handle_rag_message()`.
- `src/llm/client.py` — `AnthropicClient.complete()` (single-turn, line ~65) and `complete_with_history()` (multi-turn, line ~116). Note their signatures, model parameter handling, error types (`ExtractionFailed`), and the 60s timeout pattern.
- `src/api/routes/search.py` (lines 82-166) — the per-request client creation pattern: how `VoyageEmbeddingClient` is instantiated with settings, how `hybrid_search()` is called, and the `await session.commit()` at the end for retrieval event logging.
- `src/api/middleware/rate_limit.py` — the callable pattern (`_get_X_rate()` → `X_limit = _get_X_rate`), how `limiter` is imported and used as a decorator.
- `src/api/main.py` (lines 82-94) — how routers are imported and registered via `app.include_router()`.
- `src/retrieval/search.py` — `hybrid_search()` signature (session, query_text, query_embedding, limit, filters) and its `SearchResult` dataclass fields.
- `src/retrieval/context_builder.py` — `build_context(results, token_budget)` signature and `ContextResult` dataclass.

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests

Map the data flow end-to-end: user message → query formulation → embedding → hybrid search → context building → system prompt → synthesis → response.

Produce a findings report with:
- Exact file paths
- Relevant code snippets
- Data flow description
- Your honest assessment of structure and quality

Note any surprises or mismatches vs expectations.

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions.

Challenge specifically:
- That `_build_system_prompt` and `_build_rag_user_message` can be extracted without breaking the Discord bot's `_handle_rag_message()` flow — check every call site and ensure import paths will resolve after the move.
- That `AnthropicClient.complete()` (used for query formulation with Haiku) can be called with a hardcoded model name, or whether the model is baked into the client instance at init time — if so, you need a separate client or to pass model override.
- That `hybrid_search()` results contain all fields needed for the `ChatSourceItem` response model (`id`, `content`, `summary`, `type`, `importance_score`, `combined_score`, `project`) — verify the `SearchResult` dataclass has every field.
- That the `<user_input>` prompt injection defense pattern is consistently applied to the user message in the synthesis call but NOT to the formulated search query (which is system-generated and should not be wrapped).

Additionally challenge:
- Hidden dependencies or coupling (does `rag_cog.py` use any Discord-specific objects in the prompt functions?)
- Data shape assumptions (does `complete_with_history()` expect `messages` as `list[dict]` or typed objects?)
- Edge cases (empty history, formulation failure fallback, empty search results, model not in allowlist)
- Backward compatibility risks (will existing tests for `rag_cog.py` break after extraction?)
- Missing or weak test coverage (are there existing tests for `_build_system_prompt` or the RAG flow?)

For each challenge, label:
CONFIRMED | REVISED | UNKNOWN

For anything REVISED or UNKNOWN:
- Revisit the codebase
- Update findings with corrected understanding

Stop. Present the reconciled findings before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Prompt extraction (`src/llm/rag_prompts.py`)** — what functions to create, their exact signatures, how `QUERY_FORMULATION_SYSTEM` constant should instruct Haiku (extract concise search query from conversation + message, return only the query, no preamble), and how `build_query_formulation_content()` formats its input (history tail, external context snippet, user message).

2. **Discord bot update (`rag_cog.py`)** — minimal change: replace local `_build_system_prompt` and `_build_rag_user_message` with imports from `src.llm.rag_prompts`. Verify no behavioral change.

3. **Chat endpoint design (`src/api/routes/chat.py`)** — Pydantic models (`ChatMessage`, `ChatRequest`, `ChatResponse`, `ChatSourceItem`), the 10-step handler flow (validate → formulate → embed → search → build context → build prompt → build messages → synthesize → commit → respond), error handling strategy (formulation failure fallback, search failure, synthesis failure), and model allowlist validation.

4. **Rate limiter addition** — add `_get_chat_rate()` / `chat_limit` to `rate_limit.py` following the existing callable pattern.

5. **Router registration** — add to `main.py` following the existing pattern.

6. **Test strategy (`tests/test_chat.py`)** — what to mock (AnthropicClient, VoyageEmbeddingClient, hybrid_search), what scenarios to test (happy path, empty history, formulation fallback, invalid model, rate limiting, history length > 20, empty search results), how to structure fixtures. Follow the existing test patterns in `tests/`.

7. **What stays unchanged**
- `src/core/models.py` — no schema changes
- `alembic/versions/*` — no migrations
- `src/retrieval/search.py` — `hybrid_search` used as-is
- `src/retrieval/context_builder.py` — `build_context` used as-is
- `src/llm/client.py` — `AnthropicClient` used as-is
- `src/api/routes/search.py` — untouched
- `cli/ob.py` — untouched

8. **Constraints & Safety**
- Prompt injection: user input always wrapped in `<user_input>` tags for synthesis; formulated query (system-generated) is NOT wrapped
- External context: truncated to 2000 chars before formulation, full (up to 20k) in system prompt
- History: validated max 20 messages, only last 4 used for formulation
- Model allowlist: only `settings.rag_default_model` and `settings.rag_sonnet_model` accepted
- Rate limit: 30/minute for chat (heavier than search due to two LLM calls)
- `await session.commit()` required after hybrid_search for retrieval event persistence
- No `register_vector(conn)` — follow the existing footgun avoidance
- Use `_get_settings()` lazy helper, not module-level settings import

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan. Implement it exactly as specified.

Work in this order:
1. Create `src/llm/rag_prompts.py` — extract `build_rag_system_prompt()`, `build_rag_user_message()` from rag_cog, add `QUERY_FORMULATION_SYSTEM` constant and `build_query_formulation_content()`. Verify imports work.
2. Update `src/integrations/modules/rag_cog.py` — replace local functions with imports from `src.llm.rag_prompts`, delete local definitions. Run `make test` to verify no breakage.
3. Add `_get_chat_rate()` and `chat_limit` to `src/api/middleware/rate_limit.py`.
4. Create `src/api/routes/chat.py` — Pydantic models + full `POST /v1/chat` endpoint following the 10-step flow from the architect's plan.
5. Register the chat router in `src/api/main.py`.
6. Create `tests/test_chat.py` — comprehensive tests covering happy path, edge cases, validation, and error handling. Run `make test` to verify all pass.

After each step:
- Run the existing test suite
- Fix any failures before continuing

After implementation:
- Perform manual verification (if applicable)
- Validate outputs/logs for correctness
- Identify any remaining risks or edge cases

Final check:
- Re-read the business context
- Verify the implementation matches the original intent
- Especially validate: no schema changes were made, `<user_input>` wrapping is applied correctly (user input wrapped, system-generated query NOT wrapped), and `await session.commit()` is present after hybrid_search

Stop. Do not consider the task complete until reviewed.

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

Inputs:
- Architect's plan
- Full diff of changes
- Implementer's summary

Evaluate across:

1. **Correctness**
   - Does the implementation fully satisfy the plan?
   - Any logical errors or missing cases?

2. **Scope adherence**
   - Any unnecessary changes?
   - Anything missing that was explicitly required?

3. **Code quality**
   - Readability, structure, naming
   - Consistency with existing patterns

4. **Safety**
   - Edge cases (null, async, race conditions)
   - Backward compatibility
   - Failure handling

5. **System impact**
   - Hidden coupling or side effects
   - Performance implications

6. **Tests & validation**
   - Are tests sufficient and meaningful?
   - What critical paths are untested?

Output:
- List of issues grouped by severity:
  - CRITICAL (must fix before merge)
  - MAJOR (should fix)
  - MINOR (nice to improve)

- Concrete suggested fixes for each CRITICAL and MAJOR issue

If CRITICAL issues exist:
- The task is NOT complete
- Return to ROLE 4 with explicit fixes required

If no CRITICAL issues:
- Provide final approval summary
- Highlight any residual risks or follow-up improvements
