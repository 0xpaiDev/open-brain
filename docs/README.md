# Spec Convention

One file per backlog item. Status gates in frontmatter. File moves from `docs/backlog/` to `docs/archive/` exactly once at ship.

---

## Folders

| Folder | Contains |
|--------|----------|
| `docs/backlog/` | All live items — any status except `shipped` / `abandoned` |
| `docs/archive/` | Completed or abandoned items — read-only reference |

---

## Frontmatter Schema

```yaml
---
status: <see table below>
created: YYYY-MM-DD
shipped: YYYY-MM-DD    # set when status → shipped
abandoned: YYYY-MM-DD  # set when status → abandoned
---
```

### Status values

| Status | Meaning | File location |
|--------|---------|---------------|
| `idea` | Captured, not yet explored | `docs/backlog/` |
| `refined` | Brainstorm complete, design axes settled | `docs/backlog/` |
| `ready` | Design locked, decisions made; Plan section may be appended | `docs/backlog/` |
| `in-progress` | Actively executing; progress log below the Plan | `docs/backlog/` |
| `shipped` | Done. Move to `docs/archive/`. | `docs/archive/` |
| `abandoned` | Won't ship. Move to `docs/archive/` with reason noted. | `docs/archive/` |

---

## Override Clause

**This convention supersedes the superpowers `brainstorming` → `writing-plans` → `executing-plans` artifact split.**

Those skills still run their *process* — brainstorm, design, plan. But their *output* lands in **one file** in `docs/backlog/`, not in separate documents. Stages become sections appended to the same file as it matures.

Concretely:
- `brainstorming` output → append to the file, bump status to `refined` or `ready`
- `writing-plans` output → append a `## Plan` section, keep status `ready`
- `executing-plans` / `subagent-driven-development` → bump status to `in-progress`, append `## Progress`
- Done → bump to `shipped`, move to `docs/archive/`

---

## Example File

```markdown
---
status: ready
created: 2026-05-23
---

# Widget Renderer — Design

## Goal
Render user-defined widgets on the dashboard without a full page reload.

## Design
- Client-side fetch on mount; SSE for live updates.
- Widgets are isolated React components; no shared state.

## Plan
1. Add `/api/widgets` endpoint returning widget configs.
2. Build `<WidgetHost>` component with error boundary.
3. Wire SSE channel; update widget on each event.
```

---

## File Naming

```
docs/backlog/YYYY-MM-DD-<kebab-topic>.md
docs/archive/YYYY-MM-DD-<kebab-topic>.md
```

Date is the creation date, not the ship date.
