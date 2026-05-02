# Redesign: Learning Library + Topic Detail

## Context

The Learning Library page (`web/app/learning/page.tsx`) and the topic detail page (`web/app/learning/topics/[id]/page.tsx`) are functional but visually flat — they're a list of bordered cards with raw checkboxes, no progress indicators, no filters, no collapsible structure, and a generic add-topic form. The inspiration in `docs/learning-redisgn/` (README + screenshot + HTML prototype) shows a much more polished checklist UI with: stat cards across the top, an overall progress ring, filter pills (All / Active / Inactive), collapsible topic cards with per-topic and per-section progress rings/bars, a pill switch for the active toggle, double-click rename, hover-to-reveal delete, and a clean accent-colored "Add topic" button.

The goal is to recreate that look and behavior **using the existing Open Brain theme** (no new color palette) and **existing primitives** (`@base-ui/react` Button/Input/Collapsible/Tabs/Switch). The mobile view must work — Open Brain runs on phones, the inputs already follow the `text-base md:text-sm` pattern, and the design must not break that.

User-confirmed scope decisions (do not re-litigate):
1. **Color mapping** — use existing theme tokens. Inspiration's `#6f95e2` blue → `bg-primary` / `text-primary` (`#adc6ff`). Inspiration's `#e07060` salmon → `bg-tertiary` / `text-tertiary` (`#ffb3ad`). Inspiration's `#4caf7d` green → existing `--color-streak-hit` (`#4ade80`). Do NOT introduce new color tokens.
2. **Feedback/notes editing on main library page is removed.** Main library = clean checklist (check / rename / delete). Feedback/notes textareas live only on the topic detail page (`/learning/topics/[id]`).
3. **Topic detail page gets the full polish AND becomes interactive** (sections render with the new `SectionBlock` in editable mode — check items, double-click rename, edit feedback/notes). It is the natural home for that work now that the main page is read-clean.

---

## Files to change / create

### New components

| Path | Purpose |
|---|---|
| `web/components/ui/progress-ring.tsx` | SVG circular progress (props: `size`, `strokeWidth`, `pct`, `accentClass`, `trackClass`). Used at 34px/2.5px on topic header, 38px/3px on overall-progress card. Switches stroke color to `--color-streak-hit` when `pct >= 1`. |
| `web/components/ui/switch.tsx` | Pill toggle wrapping `@base-ui/react/switch`. 36×20 track, 14×14 thumb, `border-radius: 10px`. OFF: `bg-surface-container-high border-border`. ON: `bg-streak-hit`. Smooth 200ms thumb slide. |
| `web/app/learning/_components/topic-card.tsx` | Extract topic card from page.tsx. Owns its collapsed state. Header (progress ring + name/meta + Active switch + chevron). Expanded content = progress bar + sections + "Add section" dashed button. Entrance animation `ob-fadeIn`. |
| `web/app/learning/_components/stat-card.tsx` | Stat block: bold value + dim label. Optional `accent` flag (uses `text-primary` for the "Active" card). |
| `web/app/learning/_components/overall-progress-card.tsx` | Card with 38px ProgressRing + "Overall progress" / "X% complete" text. |

### Files to rewrite

| Path | What changes |
|---|---|
| `web/app/learning/page.tsx` | Full restructure (see "Page composition" below). Filter state (`"all" \| "active" \| "inactive"`), persisted to localStorage key `ob:learning:filter`. Stats computed from `topics` (3 cards + overall progress). Add-topic input + Add button as a single rounded container with `focus-within:border-primary`. Filter pills as a small custom segmented control (the existing `Tabs variant="line"` is underline-style; the inspiration is filled-pill). |
| `web/app/learning/_components/section-block.tsx` | Rewrite. Collapsible wrapping `@base-ui/react/collapsible`. Header: 3px-wide vertical accent bar (gradient track of `--color-primary` filled to `pct*100%`, rest is `border`), uppercase section name, "N/M" badge when any items done, chevron. Body: list of `ItemRow`s + "Add item" inline (ghost `+ Add item` → reveals input on click). Compact spacing per spec. The component is used only on the detail page in editable mode (with `onAddItem` + `onUpdateItem` provided); on the library page it renders read-only items. Keep a single component, drive behavior off whether handler props are provided. |
| `web/app/learning/_components/item-row.tsx` | Rewrite. Clean row: 18×18 checkbox (custom div using `--color-primary` when checked, with `ob-checkPop` animation on tick), title (line-through when done, double-click → inline `<input>` rename), 16×16 delete X revealed on hover (always visible on `<sm` breakpoint — touch devices have no hover). On the *detail* page only, add a small "▾" toggle that reveals the feedback + notes textareas (preserves today's functionality, just better-styled). Feedback/notes UI is gated by an `editable` prop and is NOT shown on the main library page. |
| `web/app/learning/topics/[id]/page.tsx` | Polish: header gets the 38px progress ring + meta line ("N sections · X/Y items"), Active state shown as the new `Switch` (replaces raw checkbox), back link styled as ghost button. Material panel: same card surface, header row cleaner, Edit/Delete grouped as button-group. Sections render with new `SectionBlock` in **editable** mode (`onAddItem` + `onUpdateItem` provided), so double-click rename + check + delete + feedback/notes-toggle all work here. Recent feedback section gets the same card surface and a small "F" icon per row. |
| `web/app/globals.css` | Add two `@keyframes` (`ob-fadeIn`, `ob-checkPop`) and matching utility classes (`.animate-ob-fadeIn`, `.animate-ob-checkPop`). See "Animations" below for exact CSS. |
| `web/app/learning/import/page.tsx` | Light polish only — verify Buttons use `Button` component (already does). No structural change. |

### Hooks / API

The existing `useLearning()` in `web/hooks/use-learning.ts` already exposes everything we need EXCEPT delete operations:

- Present: `createTopic`, `toggleTopicActive`, `createSection`, `createItem`, `updateItem` (handles status / title / feedback / notes), `getMaterial`, `saveMaterial`, `deleteMaterial`, `triggerRefresh`, `importCurriculum`.
- **Verify whether `deleteSection(id)` and `deleteItem(id)` exist** in `useLearning`. If missing, add them — they call `DELETE /v1/learning/sections/{id}` and `DELETE /v1/learning/items/{id}`. Check `src/api/routes/learning.py` for the route handlers; if absent, add them following the same pattern as the existing PATCH/POST routes (transaction, commit, refresh, RLS-safe). Apply `@limiter.limit()` per the CLAUDE.md rule that every `/v1/*` route needs rate-limiting. Cascade rules: deleting a section deletes its items; deleting an item is a hard delete (no soft-delete fields).
- Optimistic update pattern: mirror `toggleTopicActive` (mutate local state, refetch on error).
- After delete, re-render is automatic via the existing `topics` state mutation.

---

## Page composition (main library)

```
<div className="py-6 md:py-8 space-y-5">

  {/* HEADER */}
  <div className="flex items-start justify-between gap-3 flex-wrap">
    <div>
      <h1 className="text-2xl md:text-3xl font-headline font-bold">Learning Library</h1>
      <p className="text-sm text-on-surface-variant mt-1">
        Topics, sections, and items. Active topics feed into the morning todo list.
      </p>
    </div>
    <div className="flex gap-2">
      <Button variant="outline" size="sm" onClick={triggerRefresh}>Refresh today</Button>
      <Link href="/learning/import" className={buttonVariants({ variant: "outline", size: "sm" })}>Import</Link>
    </div>
  </div>

  {/* STATS ROW */}
  <div className="flex flex-wrap gap-2.5">
    <StatCard value={topicCount} label="Topics" />
    <StatCard value={activeCount} label="Active" accent />
    <StatCard value={`${doneItems}/${totalItems}`} label="Items done" />
    <div className="flex-1 min-w-[160px]">
      <OverallProgressCard pct={overallPct} />
    </div>
  </div>

  {/* ADD TOPIC + FILTERS */}
  <div className="flex flex-col sm:flex-row gap-2.5">
    <form onSubmit={...} className="flex-1 flex rounded-[9px] border border-border bg-surface-container overflow-hidden focus-within:border-primary transition-colors">
      <input
        value={newTopicName}
        onChange={...}
        placeholder="New topic name…"
        className="flex-1 bg-transparent px-3.5 py-2.5 text-base md:text-sm outline-none"
      />
      <button
        type="submit"
        disabled={!newTopicName.trim()}
        className="bg-primary text-primary-foreground px-4 text-sm font-semibold disabled:opacity-50 hover:opacity-85 transition-opacity"
      >
        Add topic
      </button>
    </form>
    <FilterPills value={filter} onChange={setFilter} />
  </div>

  {/* TOPIC LIST */}
  <div className="space-y-3">
    {filteredTopics.map(t => <TopicCard key={t.id} topic={t} {...handlers} />)}
    {!loading && filteredTopics.length === 0 && (
      <p className="text-sm text-on-surface-variant text-center py-12">
        {filter === "all" ? "No topics yet. Create one to start." : `No ${filter} topics.`}
      </p>
    )}
  </div>
</div>
```

**Stats math** (compute once via `useMemo`):
```ts
const topicCount = topics.length;
const activeCount = topics.filter(t => t.is_active).length;
const allItems = topics.flatMap(t => t.sections.flatMap(s => s.items));
const totalItems = allItems.length;
const doneItems = allItems.filter(i => i.status === "done").length;
const overallPct = totalItems === 0 ? 0 : doneItems / totalItems;
```

---

## Topic card composition

```tsx
<section
  className="group rounded-[14px] border border-border bg-surface-container hover:border-surface-container-highest transition-colors animate-ob-fadeIn"
>
  <header
    className="flex items-center gap-3 p-3.5 md:p-4 cursor-pointer"
    onClick={() => setCollapsed(c => !c)}
  >
    <ProgressRing size={34} strokeWidth={2.5} pct={topicPct} />
    <div className="flex-1 min-w-0">
      <div className="flex items-center gap-2">
        <Link
          href={`/learning/topics/${topic.id}`}
          onClick={(e) => e.stopPropagation()}
          className="text-[14.5px] font-semibold truncate hover:text-primary transition-colors"
        >
          {topic.name}
        </Link>
        {topicPct >= 1 && <Badge tone="green">Complete</Badge>}
      </div>
      <p className="text-[11px] text-on-surface-variant mt-0.5">
        {topic.sections.length} sections · {doneItems}/{totalItems} items
      </p>
    </div>
    <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-2">
      <span className={`text-[11px] font-medium hidden sm:inline ${topic.is_active ? "text-streak-hit" : "text-on-surface-variant"}`}>
        {topic.is_active ? "Active" : "Inactive"}
      </span>
      <Switch checked={topic.is_active} onCheckedChange={onToggle} />
    </div>
    <Chevron rotated={collapsed} />
  </header>

  {!collapsed && (
    <div className="pb-3">
      {totalItems > 0 && (
        <div className="px-4 mb-3.5">
          <div className="h-0.5 bg-surface-container-high rounded">
            <div
              className={`h-full rounded transition-[width] duration-[400ms] ${topicPct >= 1 ? "bg-streak-hit" : "bg-primary"}`}
              style={{ width: `${topicPct * 100}%` }}
            />
          </div>
        </div>
      )}
      <div className="px-3 space-y-1.5">
        {topic.sections.map(s => <SectionBlock key={s.id} section={s} {...sectionHandlers} />)}
        <AddSectionButton onAdd={(name) => onAddSection(name)} />
      </div>
    </div>
  )}
</section>
```

Note: per scope decision #2, the main library page DOES still expand to show sections (that's the whole point of the collapsible card). What it does NOT show is the per-item feedback/notes textareas. Items render as clean rows.

**`Badge tone="green"`** is a small inline component (or just an inline span) — `bg-streak-hit/15 text-streak-hit text-[10px] font-semibold rounded-md px-1.5 py-px`.

**`Chevron rotated={collapsed}`** — a 10×6 SVG with `rotate(0deg)` expanded / `rotate(-90deg)` collapsed, `transition: transform 200ms`.

---

## Filter pills

Use a custom segmented control rather than `Tabs` — the existing `Tabs variant="line"` is underline-style; the inspiration is filled-pill style. Three buttons, each with `aria-pressed`:

```tsx
function FilterPills({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  const opts: { v: Filter; label: string }[] = [
    { v: "all", label: "All" },
    { v: "active", label: "Active" },
    { v: "inactive", label: "Inactive" },
  ];
  return (
    <div role="group" aria-label="Filter topics" className="flex gap-1">
      {opts.map(o => (
        <button
          key={o.v}
          type="button"
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "rounded-lg border px-3.5 py-1.5 text-[12.5px] transition-all",
            value === o.v
              ? "bg-primary text-primary-foreground border-primary font-semibold"
              : "bg-surface-container border-border text-on-surface-variant hover:bg-surface-container-high"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
```

Persist `filter` to localStorage key `ob:learning:filter` (read on mount with stale-value guard — if the persisted value isn't one of `"all" | "active" | "inactive"`, default to `"all"`). Same pattern as `task-list.tsx`'s `focusId` persistence (per CLAUDE.md).

---

## Animations (add to `web/app/globals.css`)

Find a spot inside the `@layer utilities` block (or after existing utility definitions) and add:

```css
@keyframes ob-fadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to   { opacity: 1; transform: translateY(0); }
}
@keyframes ob-checkPop {
  0%   { transform: scale(1); }
  50%  { transform: scale(1.22); }
  100% { transform: scale(1); }
}
.animate-ob-fadeIn { animation: ob-fadeIn 0.22s ease both; }
.animate-ob-checkPop { animation: ob-checkPop 0.18s ease; }
```

The project already imports `tw-animate-css` but only ships generic Tailwind animations — these custom ones go directly in globals.css.

---

## Mobile considerations

- **Stats row**: `flex-wrap gap-2.5`. The three stat cards naturally wrap to 2 + 1 (or 1 per line on very narrow). The overall-progress card is wrapped in `flex-1 min-w-[160px]` so it takes the remaining row on wide and full row on narrow.
- **Add-topic + filter row**: `flex-col sm:flex-row`. On mobile the input takes full width, filter pills sit below it.
- **Topic header**: progress ring + name + switch + chevron must fit on a phone. Use `min-w-0` on the name container so truncation works. The "Active" / "Inactive" text label is hidden on `<sm` (`hidden sm:inline`) — the colored Switch alone communicates state.
- **Delete X on item row**: hover-only doesn't work on touch. Use `opacity-100 sm:opacity-0 sm:group-hover:opacity-100` so it's always visible on phones, hover-only on desktop.
- **Inputs**: ALL inputs must use `text-base md:text-sm` (project rule — Safari auto-zoom on `<16px`). The built-in `<Input>` component already follows this; the inline `<input>` inside the add-topic form must too.
- **Tap targets**: `Switch` track is 20px tall — wrap in a `py-2 -my-2` invisible padding so the tappable area is ≥40px.
- **Topic detail page**: existing layout already mobile-friendly. Replace the active-toggle `<input type="checkbox">` with `<Switch>` and confirm the back-link is touch-friendly.
- **No duplicate DOM for responsive layouts** (CLAUDE.md footgun) — JSDOM ignores CSS `hidden`/`sm:hidden`, so duplicating mobile vs. desktop variants of a control breaks tests. Use a single DOM with responsive classes only.

---

## Critical files to modify

- `web/app/learning/page.tsx` — full rewrite (composition above)
- `web/app/learning/_components/topic-card.tsx` — **NEW**, extracted
- `web/app/learning/_components/section-block.tsx` — rewrite (collapsible + accent-bar header)
- `web/app/learning/_components/item-row.tsx` — rewrite (clean checkbox + double-click rename + hover delete; on detail page also a feedback/notes toggle)
- `web/app/learning/_components/stat-card.tsx` — **NEW**
- `web/app/learning/_components/overall-progress-card.tsx` — **NEW**
- `web/app/learning/topics/[id]/page.tsx` — polish + interactive sections
- `web/components/ui/progress-ring.tsx` — **NEW**
- `web/components/ui/switch.tsx` — **NEW** (wraps `@base-ui/react/switch`)
- `web/app/globals.css` — add `ob-fadeIn` / `ob-checkPop` keyframes + utilities
- `web/hooks/use-learning.ts` — verify; if missing, add `deleteSection(id)` and `deleteItem(id)` mutations
- `src/api/routes/learning.py` — verify; if missing, add `DELETE /v1/learning/sections/{id}` and `DELETE /v1/learning/items/{id}` (with `@limiter.limit()` per CLAUDE.md rule)

## Existing primitives to reuse (do NOT reimplement)

- `Button`, `buttonVariants` — `web/components/ui/button.tsx` (no `asChild`; for Link-as-button use `<Link className={buttonVariants({...})}>`)
- `Input` — `web/components/ui/input.tsx` (already `text-base md:text-sm`)
- `Textarea` — `web/components/ui/textarea.tsx` (used on detail page)
- `Collapsible` — `web/components/ui/collapsible.tsx` (use `Root` + `Trigger` + `Content` for SectionBlock)
- `Dialog` — for any future "delete topic" confirmation; not required this pass
- `cn` helper — `web/lib/utils.ts`
- Existing types — `web/lib/types.ts` (`LearningTopic`, `LearningSection`, `LearningItem`, `LearningMaterial`)

## Test patterns to follow

Existing tests under `web/__tests__/` use Vitest + `@testing-library/react`. Mock `fetch` via the existing `mockFetch(handler)` helper (see `web/__tests__/hooks/use-commitments.test.ts`). Mock `sonner` toast.

Add at minimum:
- `web/__tests__/components/progress-ring.test.tsx` — renders correct stroke-dasharray for 0%, 50%, 100%; switches to green at 100%.
- `web/__tests__/components/switch.test.tsx` — fires `onCheckedChange` on click; respects `checked` prop.
- `web/__tests__/components/learning-item-row.test.tsx` — checkbox click toggles status; double-click on title enters edit mode; Enter commits, Escape cancels; delete X click invokes handler.
- `web/__tests__/components/learning-topic-card.test.tsx` — collapses/expands on header click; clicking the Switch does NOT collapse (stop propagation); progress ring reflects done/total.
- `web/__tests__/app/learning-page.test.tsx` — filter pills filter the rendered list; persisted filter loaded from localStorage; stats row reflects topic data.

If backend delete endpoints are added, follow the existing learning route test patterns. CLAUDE.md footgun: tests share `async_session` with handlers — call `session.expire_all()` before re-reading a relationship after a route mutation.

---

## Verification

After implementation, in order:

1. **Type check + lint**: `cd web && npm run lint && npx tsc --noEmit`
2. **Unit tests**: `cd web && npm test` — all existing tests still pass + new ones added.
3. **Backend tests** (only if delete endpoints added): from repo root, `make test` (filter to `tests/api/routes/test_learning*.py`).
4. **Visual check (desktop)**: `make start` (or `cd web && npm run dev`), visit `http://localhost:3000/learning`. Verify: stat cards correct, overall progress ring animates, add-topic creates a topic that fades in, filter pills filter list, topic header collapses/expands smoothly, switch toggles `is_active`, progress bar fills as items get checked.
5. **Visual check (detail page)**: navigate into a topic. Verify: 38px ring + meta render, Switch replaces checkbox, sections are interactive, double-click title renames, hover reveals delete X, feedback/notes toggle reveals textareas, material panel buttons polished.
6. **Mobile check**: open Chrome DevTools, set viewport to iPhone 14 Pro (393×852). Verify: header wraps cleanly, stats row wraps, add-topic input takes full width with pills below, topic header still readable, delete X is always visible (no hover required), Switch tap target is comfortable, no horizontal scroll, no auto-zoom on focusing the add-topic input.
7. **Regression**: visit `/learning/import`, run a dry-run + commit; confirm no styling regressions. Visit `/today` and any other page that uses `Button`/`Input`/`Collapsible` — confirm no shared-component regressions.
