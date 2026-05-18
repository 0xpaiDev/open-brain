# Nav Scroll-Hide + Memory Card Polish

**Date:** 2026-05-18  
**Status:** Ready for implementation

## Context

Two independent UI improvements:

1. The top nav and mobile bottom tabs are always visible, even when the user is actively scrolling down through content. This wastes vertical space on mobile. The convention (used by Facebook, Instagram, Chrome on Android) is to hide navigation on scroll-down and reveal it on any scroll-up.

2. Memory cards use a `border-l-4` left border to signal priority for `task`, `todo`, `todo_completion` types. This is a weak, easy-to-miss signal and inconsistent with the badge-based visual language used by other types. Additionally, `memory` and `task` types have no badge at all, making the grid visually inconsistent.

---

## Feature 1: Scroll-Hide Navigation

### Hook — `web/hooks/use-scroll-visibility.ts` (new file)

```ts
// Returns true when nav should be visible
useScrollVisibility(): boolean
```

- Starts `true` (visible)
- Attaches a passive `scroll` listener on `window`
- Tracks `lastScrollY` ref to compute direction
- Scrolling **down** past a 10px threshold → `visible = false`
- Any **upward** movement → `visible = true`
- Cleanup: removes listener on unmount

### TopNav — `web/components/layout/top-nav.tsx`

- Import and call `useScrollVisibility()`
- Change outer `<header>` classes:
  - Add `transition-transform duration-300 ease-in-out`
  - `visible` → `translate-y-0`
  - `!visible` → `-translate-y-full`

### BottomTabs — `web/components/layout/bottom-tabs.tsx`

- Import and call `useScrollVisibility()`
- Change outer `<nav>` classes:
  - Add `transition-transform duration-300 ease-in-out`
  - `visible` → `translate-y-0`
  - `!visible` → `translate-y-full`

### Layout — `web/app/layout.tsx`

No changes needed. The `pt-16` and bottom padding stay fixed — nav sliding away doesn't cause layout shift, same as Facebook's approach.

---

## Feature 2: Memory Card Polish

### File: `web/components/memory/memory-card.tsx`

#### 2a. Remove left border from TYPE_CONFIG

Strip `border-l-4 border-l-tertiary` from `task`, `todo`, `todo_completion` className strings.

#### 2b. Add missing badges

| Type | Badge (before) | Badge (after) |
|---|---|---|
| `memory` | none | `"MEMORY"` |
| `task` | none | `"TASK"` |
| `decision` | `"DECISION"` | unchanged |
| `context` | `"CONTEXT"` | unchanged |
| `todo` | `"TODO"` | unchanged |
| `todo_completion` | `"DONE"` | unchanged |
| `daily_pulse` | `"PULSE"` | unchanged |

#### 2c. High-priority badge for todo/task types

`MemoryItemResponse` does not carry a `priority` field — priority lives on `TodoItem`, not on memory cards. Use `importance_score` as the proxy.

- If `item.importance_score >= 0.8` **and** `item.type` is `"todo"` or `"task"`:
  - Render a small `HIGH` badge after the type badge
  - Style: `bg-amber-500/20 text-amber-400` (warm, distinct from the secondary badge color)

---

## Verification

1. Run `cd web && npm run dev`, open on mobile viewport (375px)
2. Scroll down — top nav should slide up out of view, bottom tabs should slide down out of view
3. Scroll up — both reappear with smooth transition
4. On desktop, same behavior for top nav (bottom tabs hidden on desktop anyway)
5. Memory page: confirm no left borders on any cards
6. Confirm all 7 types show icon + badge
7. Create/find a todo memory item with `importance_score >= 0.8` — confirm `HIGH` badge appears
8. Run `cd web && npm test` — no regressions
