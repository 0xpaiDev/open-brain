# Learning Library — Business Case

## 1. Problem

Open-brain is a multi-layered system — vector search, async pipelines, cron jobs, LLM integrations, Strava webhooks — and it was built incrementally. There is no structured way to revisit or consolidate understanding of what was built and why. Beyond that, there is no single place to track any learning agenda at all: books to absorb, frameworks to explore, concepts to master. Learning happens reactively or gets lost in scattered notes. The daily todo flow exists but carries no learning intent.

## 2. Goal

A personal learning library — covering the open-brain stack and any other subject — that feeds 2–3 selected items into the daily todo workflow each morning based on what is currently active, so deliberate learning becomes a built-in part of every day.

## 3. Data Model

Three-layer hierarchy:

- **Topic** — a broad subject area (e.g., "Open Brain stack", "Go concurrency", "Cycling nutrition").
- **Section** — a logical grouping within a topic (e.g., under "Open Brain stack": "Backend", "RAG", "Deployment").
- **Item** — a specific thing to learn or explore within a section. Tracks completion, and on completion accepts two optional inputs: **feedback** (calibration signal for the cron LLM — was this the right level, too much, too little) and **notes** (personal reference for later revisiting).

Each topic carries a **depth indicator** — how deeply the user needs to understand this subject. Some topics require foundational awareness only ("what is it, how does it work"), others demand deep mastery. This is set per-topic during grooming and guides the cron LLM when selecting items and framing todos. Depth is groomed collaboratively with Claude when building out topic content.

## 4. Scope

| Intent | Trigger | Action |
|---|---|---|
| Daily learning todos | Morning cron | LLM draws from active topics, creates 2–3 todos in /today |
| Curriculum management | Manual via /learning page | Add, organise, and check off topics, sections, and items |
| Topic activation | Toggle per topic | Mark a topic as active/inactive — only active topics feed the cron |
| Learning mode toggle | Global setting | Turn learning todo generation on or off entirely |
| On-demand fetch | Manual trigger | Generate learning todos outside the cron schedule |
| Completion capture | On check-off | Optional feedback (LLM calibration) and notes (personal reference) |
| Topic creation | TBD | Possibly a Claude Code skill that produces structured topic files for ingestion into open-brain |

## 5. Requirements

### Functional

- Topics are independent and open-ended — could be "pgvector internals", "Go concurrency", "Nutrition science", or anything else the user grooms in.
- Each topic contains ordered sections; each section contains ordered items.
- Each item tracks completion state and optional feedback + notes on completion.
- Topics have an active/inactive toggle — inactive topics never feed the cron, but their progress is preserved.
- A global "learning mode" setting enables or disables daily todo generation without touching individual topics.
- Daily cron draws only from active topics with uncompleted items. The LLM sees the last 7 days of feedback to calibrate volume and selection.
- Learning todos appear in /today visually distinguished from regular todos, labelled with their source topic.
- A /learning page shows all topics (active, inactive, completed) with per-topic and per-section progress. Users can add and reorder topics, sections, and items, and check items off with optional feedback and notes.
- Completed topics display a checkmark and remain visible on /learning for revisiting past notes and progress.

### Non-functional

- No ceiling on number of topics, sections, or items — a dozen topics with dozens of items each must work without degrading cron performance.
- Daily cron uses a cheap/fast model.
- Job is idempotent — running twice on the same day produces no duplicate todos.
- If all active topics are exhausted, the job exits cleanly and logs it visibly.

### Safety

- Feedback and notes capture is best-effort — a failure never blocks marking an item done.
- Cron failure falls back to a random draw of 2 items rather than silently producing zero todos.
- Deactivating or completing a topic never deletes progress — completion state, feedback, and notes are always preserved.

## 6. To-Be Experience

You have eight topics in /learning: open-brain stack (with sections for backend, RAG, deployment), pgvector deep-dive, Go concurrency, cycling nutrition, two books, a framework you're exploring. Five are active. You wake up, open /today — three todos tagged "Learning" are there: one from open-brain/RAG, one from Go, one from a book.

You check one off, leave a quick feedback note ("good level, maybe slightly too broad") and a personal note ("HNSW probe count trades recall for speed — revisit when tuning production index"). Move on with your day.

Mid-week you decide to pause the book topics and focus on the stack. You toggle two topics inactive. Tomorrow's batch draws only from the technical topics. The LLM reads your recent feedback and adjusts — slightly more focused items, one fewer than yesterday.

Later you open /learning, scroll through your completed sections, re-read your notes from last month. Everything is there.

## 7. Out of Scope (v1)

- Adaptive difficulty based on context signals (Strava load, calendar busyness, time of day)
- Spaced-repetition or re-surfacing of completed items
- Automatic curriculum generation from the codebase
- Sharing, exporting, or publishing a curriculum
- Any changes to how regular todos behave
- Per-topic daily todo count config (global count is enough for v1)
- RAG search over learning notes (notes are for personal revisiting on /learning page, not memory pool ingest)
- Discord bot integration (deprecated)

## 8. Success Criteria

- Learning todos appear in /today every morning when learning mode is on, drawing only from active topics — zero manual steps required.
- Activating or deactivating a topic takes one toggle; the change is reflected the following morning.
- Completion feedback is visible to the cron LLM and demonstrably influences next-day selection within 7 days of use.
- The /learning page gives a full picture of all topics — active, inactive, done, and remaining — with all historical notes accessible, without opening any other tool.

## 9. Open Items

- **Topic creation workflow**: how structured topic files are authored and ingested. Likely a Claude Code skill with a defined schema — to be designed separately.
- **Depth indicator UX**: how depth is presented and edited on /learning (slider, labels, free-text). Decide during design phase.
- **Feedback schema**: structured vs free-text feedback. Starting with free-text; may evolve if patterns emerge.
