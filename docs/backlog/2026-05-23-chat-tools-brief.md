---
status: refined
created: 2026-05-23
---

# Chat Tools Library — Brainstorm Brief

**Status:** active (brief, not yet a spec)
**Date:** 2026-05-23
**Source idea:** Hermes Agent's capability gap — their chat surface can manipulate data; ours can only retrieve it.

> This is a **brainstorming brief**, not an implementation spec. Its purpose is to structure the follow-up design conversation. The output of that conversation will be a real spec, which then becomes the implementation plan.

## Context

The web chat at 0xpai.com is RAG + synthesis only. Verified by reading `src/api/routes/chat.py`:

```
formulate query (Haiku) → embed (Voyage) → hybrid search → synthesize (selected model) → respond
```

There is **no tool-use loop**. No `create_todo` tool wired in. No multi-step agent behavior. The chat can answer questions over the memory store; it cannot manipulate it.

The user wants the chat to do things — defer a memory, mark a todo done, query by structured filters ("show me my learnings from last week"), search by date range, manipulate state via natural language. This is a meaningful jump in product value.

Before locking a tool list, we need to talk through the design axes. Some of them have non-obvious tradeoffs that change the architecture.

## Foundation gap (must flag before scoping the tool list)

Adding "tools" to the chat is not just listing them. The current code path is a single-shot LLM call. To support tools, we need:

1. **Tool-use loop.** Convert `complete_with_history` to Anthropic's tool-use mode. Multi-turn loop: model emits tool calls → server dispatches → model continues with tool results → eventually emits final text.
2. **Tool dispatch layer.** A registry mapping tool names to typed handlers. Each handler validates inputs, calls a service method, returns a typed result.
3. **Multi-step turn persistence.** Today, history is client-supplied as `list[ChatMessage]`. Tool-call traces (assistant tool_use blocks, user tool_result blocks) need to be preserved across the loop and probably across turns. The wire format may need to change.
4. **Partial failure handling.** Tool X succeeds, tool Y fails — what does the user see? What does the model see? How do we surface errors without confusing the LLM into retrying forever?
5. **Tool-call observability.** Logging: which tool, what args, what result. Critical for debugging and for future training-data collection.

Estimate: **1–2 days for the foundation, before any tool exists.** This is real work and should be scoped as its own PR.

## Design axes to decide together

### 1. Tool surface shape

- **Narrow typed tools** — `defer_memory(memory_id, until_date)`, `complete_todo(todo_id)`. One tool per action.
  Pros: clearer to the LLM, type-safe, easier to authorize.
  Cons: more code; ~10–15 tools at the upper bound.

- **Generic umbrella tools** — `manipulate_memory(action, args)`, `manipulate_todo(action, args)`.
  Pros: fewer tools to register.
  Cons: LLM has to learn each action's args from prose; weaker types; harder to authorize per-action.

Recommendation: **narrow.** Hermes leans this way; it's what works.

### 2. Read vs. write parity

- **Reads-first** — ship `search_memory_filtered`, `list_todos`, `count_by_type`, etc. No destructive actions in v1. Tighten the loop with users before touching writes.
- **Both together** — reads and writes in the same release.

Recommendation: **reads-first.** Reads are a strict improvement with zero destructive-action risk; they let us validate the foundation cheaply.

### 3. Confirmation gates

- **Execute immediately** — model calls `complete_todo(123)`, it happens. Relies on undo.
- **Confirm via follow-up turn** — model proposes, user confirms in next message.

We don't have undo today. Building undo is a separate workstream. So:

Recommendation: **immediate execution for low-risk writes** (defer, mark done, edit todo text — all reversible by another tool call). **Confirmation gate for high-risk writes** (supersede a memory, delete anything). The taxonomy goes in the spec.

### 4. SQL access (the user explicitly asked about this)

Three flavors in increasing risk:

- **A. Constrained DSL** — LLM emits a structured filter object (`{type: "learning", date_from: "2026-05-15", project: "open-brain", importance_min: 0.5}`). Service layer validates and translates to SQL.
- **B. Read-only SQL against whitelisted views** — LLM emits `SELECT ...` against a view that already excludes sensitive fields and other users' data. Easier to debug. Higher risk surface.
- **C. Arbitrary SQL** — model emits any query. **Don't.**

Recommendation: **A.** It's the safe shape and covers ~95% of the use cases the user described. If we later hit cases A can't express, B becomes a discussion. Skip C.

### 5. Authorization model

Every tool must scope to the authenticated user. **Authorization belongs at the service layer, not the LLM layer.** The model is not a security boundary.

Today, chat is effectively single-user (one Anthropic key, one user behind the dashboard). If multi-user is ever on the roadmap, every tool handler must take `user_id` from the request session, not from the LLM's tool call. Hardcode this from day one — retrofitting is painful.

### 6. Tool discovery (system prompt size)

- **All tools every turn** — simple, but bloats the system prompt as the tool count grows.
- **Lazy tool groups** — expose tool groups based on intent (memory tools, todo tools, pulse tools).

For v1 with 4–6 tools, **all tools every turn** is fine. Revisit if we cross ~10.

## Candidate tools (for discussion, not commitment)

Grouped by domain. R = read, W = write.

### Memory — `src/api/services/memory_service.py`

- `search_memory_filtered(query, type?, date_from?, date_to?, project?, importance_min?)` — R
- `expand_memory(memory_id)` — R (already exists as MCP tool, wrap it)
- `defer_memory(memory_id, until_date)` — W
- `adjust_importance(memory_id, value)` — W
- `supersede_memory(memory_id, new_text)` — W (uses existing supersedes mechanism — needs confirmation gate)

### Todos — `src/api/services/todo_service.py`

- `list_todos(status?, due_before?, project?)` — R
- `create_todo(text, due_date?, project?, importance?)` — W
- `complete_todo(todo_id)` — W
- `defer_todo(todo_id, until_date)` — W
- `edit_todo(todo_id, fields)` — W

### Pulse / briefing

- `get_morning_pulse(date?)` — R
- `mark_pulse_item_done(item_id)` — W

### Time-range queries (generic)

- `count_by_type(type, date_from, date_to)` — R (e.g. "how many learnings logged this week")

Total: ~13 candidates. **v1 likely ships 4–6** of these. The brainstorm decides which.

## Out of scope for this workstream

- **Messaging transport** (Telegram / WhatsApp / Slack). The chat backend is the foundation; transports plug in later. Build foundation first, transports become trivial.
- **Server-side agent runtime with shell/file tools** (the "Hermes-style VM session"). Defer until the chat tools library proves valuable.
- **Skill loading on server.** The web chat needs *tools*, not skills. Different abstraction. Skills are for Claude Code on the laptop.
- **Undo system.** Real undo is a separate, much larger workstream. v1 mitigates by limiting destructive actions and gating high-risk ones.

## Brainstorm session goals

When we sit down to turn this brief into a spec, we should leave with:

1. **Locked v1 tool list** (4–6 tools) — each with signature, validation rules, and which existing service method it wraps.
2. **A decision on each of the 6 design axes** above.
3. **A decision on SQL flavor** (A/B/C).
4. **A test plan.** These tools modify user data → integration tests against real Postgres (per the project footgun rules in `CLAUDE.md`), not SQLite mocks.
5. **An auth/scoping checklist** for code review. Every tool handler must read `user_id` from the request session.

## Critical files to read before that session

- `src/api/routes/chat.py` — current single-shot RAG flow.
- `src/api/services/memory_service.py` — service-layer entry points the tools will wrap.
- `src/api/services/todo_service.py` — same.
- `src/retrieval/search.py` — hybrid search internals (on the escalate-before-changing list per `CLAUDE.md`).
- `src/llm/prompts.py` — system prompts; tool-use mode changes prompt structure.
- The Anthropic client wrapper that owns `complete_with_history` — needs a tool-use variant. Locate it before the session so we know what we're modifying.

## Why a brief, not a spec yet

The user's request is product-shaped, not solution-shaped. "Make the chat able to manipulate data" admits at least three different implementations (constrained DSL, narrow tools, agent runtime with shell). Locking on one before discussing tradeoffs is the kind of premature commitment that ends with throwaway work.

Once the brainstorm session settles the design axes, the spec writes itself in 30 minutes.
