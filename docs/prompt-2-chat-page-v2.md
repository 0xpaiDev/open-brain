# Web Memory Chat — Multi-Agent

You will work through this task in four roles, sequentially. Do not skip ahead.
The goal: build a working chat page at /chat where the user can have a multi-turn conversation with their memory database, optionally paste external context, and select the AI model per conversation.

---

## Business context (read once, then put on your shelf)

This is a personal second-brain system. Memories are stored as embeddings in pgvector. There is an existing RAG pipeline used by a Discord bot — the user wants to bring this to a web UI. The chat is not general-purpose — it queries the user's own memory. Key behaviors:

- The LLM should formulate its own search query from the user's message rather than embedding the raw message. This matters because the user might paste a letter from their boss and ask "does this match any patterns I've seen before?" — the raw message is not a good embedding query.
- External context (a pasted letter, a doc snippet) can be provided at the start and should stay active for follow-up questions in the same conversation.
- Multi-turn up to ~10 exchanges — soft limit, informational, not a hard block.
- The user wants to see which memories were used to answer, in a collapsible view.
- Model selector per conversation: Haiku (default, cheap) or Sonnet (when it matters). Persisted to localStorage.
- MVP: no streaming. Full response wait is acceptable.

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything — discover it.

Find and read:
- The existing RAG pipeline end to end — from how a query comes in on the Discord bot, through embedding, pgvector search, importance ranking, to the LLM synthesis call. Read every layer.
- Whether a `/v1/chat` HTTP endpoint already exists, and if so, its current shape
- The kernel method(s) involved in RAG — exact signatures and what they return
- The `/chat` page in the Next.js app — what currently renders
- How the frontend authenticates to the FastAPI backend — headers, tokens, or open
- The dashboard page — read it to understand the component patterns and API call style already established

Produce a findings report: exact file paths, function signatures, the full RAG pipeline as a numbered flow, and anything surprising or inconsistent you found.

Stop. Do not proceed until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings. Your job is to find the gaps and wrong assumptions.

Challenge specifically:
- The RAG pipeline Role 1 described — does conversation history actually get passed through today, or is every query stateless? If stateless, where exactly does that need to change?
- The "agentic query formulation" idea (two LLM calls: one to form the search query, one to synthesize) — is this actually better than just embedding the user message? Argue against it. When would it fail?
- Does the kernel's search method return enough metadata (importance, project, created_at, summary) to populate a sources view, or only raw content?
- Is there anything in the existing pipeline that would make per-message model switching break — for example, is the model hardcoded somewhere in the kernel rather than passed as a parameter?
- What does the frontend auth situation actually allow — can the chat page call the API the same way the dashboard does, or is there something different needed?

Label each: CONFIRMED | REVISED | UNKNOWN. Revisit code for anything not confirmed.

Stop. Present reconciled findings.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a plan covering:

1. **Backend endpoint** — shape of `POST /v1/chat`: request body fields, response shape including the memories_used array, error cases. Decide whether the two-LLM-call approach (query formulation + synthesis) is worth it based on what the Skeptic found, or whether a simpler approach is better. Justify.

2. **Conversation history** — how history is passed, stored (client-side only for MVP), and truncated if it grows large. The kernel likely needs a parameter change — specify exactly what.

3. **Pasted context handling** — where in the prompt chain the pasted context lives. Does it go into the query formulation call, the synthesis call, or both? Reasoning matters here.

4. **Model parameter** — how the model choice flows from the frontend request through the endpoint into the kernel call. If the kernel hardcodes the model today, specify the minimal change needed.

5. **Frontend: chat page layout** — describe the component structure: conversation thread, input area, context panel (collapsible), model selector placement, sources modal. Reference existing dashboard components where they can be reused.

6. **Soft limit behavior** — exactly what the UI shows at 10 exchanges and what "reset" does to state.

7. **Sources view** — what data populates it per message, how it's triggered (button/link under each assistant message), modal or drawer.

8. **What stays unchanged** — list explicitly.

Label every decision with reasoning. Where two approaches exist, pick one and say why.

Stop. Present the plan. Do not implement until this role is complete.

---

## ROLE 4 — PLAN WRITER

Read the architect's decisions and the full reconciled findings. Write a structured implementation plan that a Claude Code agent can execute in a separate session with no additional context.

The plan must be self-contained. The implementation agent will not have access to this conversation — only the plan document.

Structure the plan as follows:

**1. Current state summary**
What exists today, exactly — file paths, function signatures, what the /chat page renders now. Enough that the implementer can orient without re-exploring.

**2. What needs to change — backend**
Each change as a discrete task: file, what to modify, why. Include the exact kernel method signatures after the change. Include the POST /v1/chat request and response shapes as JSON examples.

**3. What needs to change — frontend**
Each change as a discrete task: component or page, what to add or modify. Describe the UI behavior precisely (what triggers the sources modal, what the soft limit banner says, how context panel collapse works). Reference existing components from the dashboard that should be reused.

**4. Implementation order**
Numbered sequence. Each step has a gate: what must be verified before the next step starts.

**5. Do not touch**
Explicit list of files and systems that must remain unchanged.

**6. End-to-end smoke test**
A manual test script the implementer runs at the end: exact steps, what to observe at each step, what counts as pass or fail. Covers the pasted-context + follow-up conversation flow specifically.

Save the plan as `chat-implementation-plan.md` in the project root. Do not implement anything.
