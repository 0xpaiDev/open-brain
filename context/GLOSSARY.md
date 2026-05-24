# Domain Glossary

Canonical terms for this project. Updated lazily — only when a term is resolved in conversation.

**Rules:**
- One entry per genuinely ambiguous concept (not every noun in the codebase).
- Canonical term chosen; alternatives listed under **Avoid** so I don't drift back.
- 1–2 sentences max per definition.
- If I use the wrong word and you correct me, I add or update the entry immediately.

---

## raw_memory

The append-only source record written at ingest time. Contains the original text exactly as provided. Never edited — corrections create new `memory_items` with `supersedes_memory_id`.

**Avoid:** "source", "input", "original memory"

---

## memory_item

A single extracted chunk derived from a `raw_memory` by the distillation pipeline. What gets embedded and searched. Multiple items can come from one raw_memory.

**Avoid:** "memory", "chunk", "note", "record"

---

## ingest

The action of adding new content to the system — writes a `raw_memory` row and queues distillation. Entry point: `ingest_memory()` in `memory_service.py`.

**Avoid:** "store", "save", "capture", "upload"

---

## distill

The background process that turns a `raw_memory` into one or more `memory_items` via LLM extraction. Run by the worker on the `refinement_queue`.

**Avoid:** "process", "extract", "synthesize", "refine" (too generic)

---

## importance_score

The GENERATED column on `memory_items` — never set directly. Recomputes from `base_importance` and `dynamic_importance`. Always read this column; never write to it.

**Avoid:** "score", "weight", "rank" (ambiguous with search ranking)
