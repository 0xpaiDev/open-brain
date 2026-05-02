# Learning Library V2 — Part 2: Frontend (Import Page + Topic Detail Page) — Multi-Agent

You will work through this task in sequential roles. Do not skip ahead.
Optional roles (marked "conditional") are included only when relevant — if absent, proceed to the next numbered role.
Review roles (5 and 6) may loop back for fixes, up to 2 cycles each.
The goal: a polished web UI that lets the user paste curriculum JSON into an import page, preview a dry-run, commit, and then open any topic in a dedicated detail page that renders its source material as markdown — plus a small badge on the existing tree view indicating which topics carry material.

---

## Business context (read once, then put on your shelf)

Open Brain has a Learning Library — a three-level curriculum tree (topics → sections → items) used to drive a daily todo cron. Part 1 of V2 (already merged) added a backend bulk-import API (`POST /v1/learning/import?dry_run=...`) and per-topic markdown materials (one-to-one, full CRUD via `/v1/learning/topics/{id}/material`). The user can already import via curl, but the UX target is paste-into-app, not paste-into-curl.

This is Part 2: build the two new web pages that consume Part 1's API, refactor the existing tree view to surface material presence, and provide a place for the user to re-read source material when reviewing a topic later.

The full spec is archived at [prompts/old/learning-import-and-materials.md](prompts/old/learning-import-and-materials.md) — sections relevant to Part 2 are Step 8 (frontend) and Step 10 (verification). Steps 1–7 and 9 are Part 1 and are already merged.

This prompt is Part 2 only. Do NOT modify the backend, do NOT alter the migration or service layer, do NOT add new endpoints — those are merged and frozen. If during exploration you find a backend gap, flag it as a CRITICAL ARCHITECTURAL issue in Role 5 and stop; do not silently extend Part 1.

---

## Project context (grounding for all roles)

### Part 1 — already merged, treat as fixed contract

The following endpoints exist on `/v1/learning/*` and are tested. Consume them; do NOT re-implement. Verify with a curl ping if uncertain.

```
POST   /v1/learning/import?dry_run={true|false}
        body: { topics: [ { name, description?, depth, sections: [ { name, items: [ { title } ] } ], material? } ] }
        response: { dry_run, topics_created, sections_created, items_created, materials_created, topics_skipped: [{name, reason}], created_topic_ids: [] }
        rate limit: 5/minute

GET    /v1/learning/topics/{topic_id}/material
        response: MaterialOut (or null body, depending on Part 1's final shape — verify)

PATCH  /v1/learning/topics/{topic_id}/material
        body: { content, source_type?, source_url?, source_title?, metadata? }
        response: MaterialOut (creates if missing, updates if present)

DELETE /v1/learning/topics/{topic_id}/material?confirm=true → 204

GET    /v1/learning  (existing — now includes topic.has_material: bool on every topic)
```

**MaterialOut shape:**
```
{ id, topic_id, content, source_type, source_url, source_title, metadata, created_at, updated_at }
```

### Relevant conventions

The Implementer must verify each item before marking the corresponding step complete.

1. **Mobile input font-size ≥ 16px.** Every `<input>`, `<textarea>`, `<select>` must use `text-base md:text-sm` (not bare `text-sm`). Safari/Chrome auto-zoom on inputs with font-size < 16px. Base components in `web/components/ui/` already comply; the import page's JSON paste textarea and the topic-detail material editor must too.
2. **No duplicate DOM for responsive layouts.** JSDOM ignores CSS `hidden` / `sm:hidden` so duplicate elements break Vitest. Use single-DOM + responsive classes (`flex-wrap` etc.).
3. **Code references in text use markdown links** when surfacing in the chat UI — N/A for this task; this is a VSCode-extension chat convention only.
4. **Toast on error** via `sonner` — match existing pattern in `useLearning()`. The existing hook calls `toast.error(...)` after a failed `api()` call; new actions should follow.
5. **Re-fetch tree after mutation.** V1 pattern: each mutation calls the API, then `fetchTree()` to refresh local state. Match this for `saveMaterial` / `importCurriculum` (post-success).
6. **`react-markdown` v9 escapes raw HTML by default.** Do NOT add `rehype-raw`. Add a one-line comment beside the renderer site explaining the omission is intentional, so a future contributor doesn't add it back.
7. **No new environment variables.** This is a pure UI build; no `NEXT_PUBLIC_*` additions.
8. **Match existing route folder casing.** Dynamic routes use bracket convention `[id]`. The detail page lives at `web/app/learning/topics/[id]/page.tsx`.
9. **Match existing API helper.** `web/lib/api.ts` exposes a typed `api()` function used by every hook. Do not introduce `fetch()` directly.
10. **Confirm-on-delete pattern.** V1 deletes show a `confirm(...)` browser prompt before firing. Material delete should do the same.

### Architecture snapshot (frontend, V1 — verify with the Explorer)

- [web/app/learning/page.tsx](web/app/learning/page.tsx) (~267 lines): contains `LearningPage`, `TopicCard`, `SectionBlock`, `ItemRow`. The latter two need to be extracted into `web/app/learning/_components/` and made reusable across the tree page and the new topic-detail page.
- [web/hooks/use-learning.ts](web/hooks/use-learning.ts) (~141 lines): the single source for learning state. Returns `{ topics, loading, error, refresh, createTopic, toggleTopicActive, createSection, createItem, updateItem, triggerRefresh }`. Each action calls `api(...)` then `fetchTree()`. We extend this with: `getMaterial`, `saveMaterial`, `deleteMaterial`, `importCurriculum`.
- [web/lib/types.ts](web/lib/types.ts): contains `LearningTopic`, `LearningSection`, `LearningItem`, `LearningTreeResponse`. Extend with `has_material: boolean` on `LearningTopic`, plus new types for material + import request/response.
- [web/lib/api.ts](web/lib/api.ts): typed `api()` helper. Reuse.
- `web/components/ui/textarea.tsx`, `web/components/ui/button.tsx`, `web/components/ui/input.tsx`: shadcn-style primitives. Use them.
- The sidebar nav already has a "Learning" entry — no new nav work needed.

### Recent changes

Last 14 days touching the affected area:
- **Part 1 of this V2 work just merged** — backend now exposes `POST /v1/learning/import` and material CRUD, plus the `has_material` flag on `GET /v1/learning`. This is the contract you are consuming.
- `feat(ui): focus card range selection and task action enhancements` (7093301) — `task-list.tsx`, no learning impact.
- `feat(ui): focus mode and project grouping polish` (350cb23) — `task-list.tsx`, no learning impact.
- `feat(todos): project grouping with redesigned task dashboard` (e599864) — `task-list.tsx`, no learning impact.

Frontend learning UI itself has not changed since V1 ship.

### Locked design decisions (do not relitigate)

| Decision | Choice |
|---|---|
| Markdown lib | `react-markdown@^9` + `remark-gfm@^4`. No `rehype-raw`. |
| Material editor | Inline `<Textarea>` toggled by an "Edit" button; not a modal. |
| Material container | `max-h-[60vh] overflow-y-auto prose prose-sm dark:prose-invert` |
| Import flow | Two-pane page: paste JSON left, preview right. "Validate (dry run)" first; "Import" gated on a successful dry-run with `topics_created > 0`. |
| Topic detail data source | The cached `useLearning()` tree (no extra fetch for the topic). Material is fetched lazily on detail-page mount. |
| Tree view material indicator | Small `text-xs rounded-full px-2 py-0.5 bg-secondary/30` badge labeled "material" next to topic name. |
| Frontend tests | None added — there is no Vitest coverage for `/learning` today. Note this gap explicitly in the PR description; rely on Step 10 manual checklist. |

---

## ROLE 1 — EXPLORER

Explore the codebase. Do not assume anything about structure — discover it. The Architecture snapshot above is your starting point, not the final word — verify it.

Find and read:

1. **Full content of [web/app/learning/page.tsx](web/app/learning/page.tsx)**. Map every component (top-level + nested). Identify the line ranges for `SectionBlock` and `ItemRow` so you can extract them cleanly. Note: do they receive props for `onAddItem` / `onUpdateItem`, or do they import from a hook directly? The refactor must make these props optional so the topic-detail page can render the same components in a more read-only mode.

2. **Full content of [web/hooks/use-learning.ts](web/hooks/use-learning.ts)**. Note: the exact return type shape, the `api()` call signature being used (HTTP verb position, body shape), how errors are surfaced (toast vs returned). Plan the four new methods (`getMaterial`, `saveMaterial`, `deleteMaterial`, `importCurriculum`) to match the existing style exactly.

3. **[web/lib/types.ts](web/lib/types.ts) lines 58–91** plus surrounding context. Confirm the existing types match the snapshot. Plan the new types.

4. **[web/lib/api.ts](web/lib/api.ts)**. Note the function signature: is it `api(method, path, body?)` or `api({ method, path, body })`? Does it accept query params, or do you build them into the path string? This determines how you pass `?dry_run=true`.

5. **[web/package.json](web/package.json)**. Note the React, Next.js, and TypeScript versions. Confirm `react-markdown` and `remark-gfm` are NOT yet present. Check whether `@tailwindcss/typography` is installed (the spec relies on `prose` classes for material rendering — if it's not there, the material panel won't get nice typography unless you install it or fall back to manual styling).

6. **Existing dynamic routes**. Search for any folder named `[id]` or `[*Id]` under `web/app/` — find one and read its `page.tsx` to learn the project's conventions for `params` typing (React 19 made `params` a Promise — verify the project's pattern).

7. **`web/components/ui/textarea.tsx`** and **`web/components/ui/button.tsx`**. Confirm the variants and class conventions. The import page uses `variant="outline"` for the "Refresh today"-adjacent button and the import button is the existing default style.

8. **The `Toaster` setup** — typically `sonner` mounted in `web/app/layout.tsx`. Confirm presence so toast calls work without extra wiring.

9. **`tailwind.config.ts`** — confirm `prose` / `prose-invert` are accessible (i.e., `@tailwindcss/typography` plugin is registered). If it's not, surface as a Skeptic challenge.

10. **The existing sidebar nav** — find the file (likely `web/components/sidebar.tsx` or similar). The "Library" link already points to `/learning`. The new pages are sub-routes (`/learning/import`, `/learning/topics/[id]`) — they don't need new nav entries, but verify by reading the sidebar source that a deep link from a topic-detail page back to `/learning` will work as expected.

11. **Environment of the API base URL.** The `api()` helper either uses a relative path (`/v1/...`) for same-origin or a base URL from env. Confirm so the import page's "validate" button hits the right host.

Also trace for each item:
- Where it is created
- Where it is mutated
- Where it is consumed
- Any related tests (likely none for `/learning` per the spec)

Map the data flow end-to-end:
- **Tree view** → `useLearning()` → `GET /v1/learning` → state → render. Material badge added in render only.
- **Detail page** → cached topic from `useLearning()` + lazy `getMaterial()` call → render markdown.
- **Import page** → user pastes JSON → "Validate" → `POST /v1/learning/import?dry_run=true` → render counts → "Import" → `POST .../import?dry_run=false` → toast + `router.push('/learning')` + tree refresh.

Produce a findings report with:
- Exact file paths
- Relevant code snippets (just the patterns to match)
- Data-flow description
- Honest assessment of structure
- Any surprises or mismatches vs the Architecture snapshot above (especially: React 19 `params` as Promise, `@tailwindcss/typography` presence, `api()` helper query-param convention)

Stop. Do not proceed to Role 2 until the findings report is complete.

---

## ROLE 2 — SKEPTIC

Read Role 1's findings report. Your job is to break its assumptions — but only with evidence.

### Grounding rules
- Every challenge must cite specific evidence from the Explorer's findings (file path, code snippet, version number)
- Label each challenge: **HIGH** (contradicting evidence found), **MEDIUM** (ambiguous evidence), **LOW** (speculation)
- For LOW challenges: go back to the codebase and upgrade to MEDIUM/HIGH, or drop with "Insufficient evidence, not blocking"
- Do not carry LOW challenges forward to the Architect

Challenge specifically:

- **`react-markdown@^9` peer-deps with React 19.** Verify the React version in `web/package.json`. `react-markdown` v9's peer is `react: '>=18'`, so React 19 should work without `--legacy-peer-deps` — but verify by reading the v9 release notes or trying the install. If it errors, the Architect plans the fallback. If it doesn't, drop the fallback claim.

- **`@tailwindcss/typography` may not be installed.** The spec uses `prose prose-sm dark:prose-invert` classes for the material panel. If the plugin is missing, those classes are silent no-ops — the material renders with default styling but unreadable code blocks. Cite evidence: read `tailwind.config.ts` and check the `plugins` array.

- **Refactor regression risk.** Extracting `SectionBlock` / `ItemRow` from `web/app/learning/page.tsx` into `_components/` is "pure code move", but the spec says the action callbacks become optional. If existing callers stop receiving props (e.g., a parent stops threading `onAddItem`), the tree page's add-item form silently breaks. Re-read the existing page to identify every prop currently passed and confirm the optional change preserves V1 behavior.

- **`useLearning()` cache survival across navigation.** Next.js App Router: client-side `Link` navigation typically preserves component state if the parent layout persists. If the parent of `/learning` and `/learning/topics/[id]` is the same layout segment, the hook's tree is reused. If they are siblings under different layouts, the detail page lands with an empty cache and `topics.find(...)` returns undefined — broken. Verify the layout structure.

- **React 19 `params` is a Promise.** Next.js 15 with React 19 made dynamic route `params` a Promise (you `use(params)` or `await params`). If the explorer found Next.js 15+ and didn't already see this pattern in another `[id]` route, the topic-detail page must follow it.

- **Rate limit on `POST /v1/learning/import` (5/min).** The "Validate" button can be clicked rapidly during JSON-debugging. Six clicks in a minute = 429. Is the import page resilient? Plan for a friendly toast on 429 not a generic error.

- **Mobile input font-size enforcement.** The spec requires `text-base md:text-sm` on the JSON paste textarea and the material editor textarea. If the developer types `text-sm` from muscle memory, mobile zoom-in regression. Verify by running the build and grepping the resulting components.

- **Empty-tree case.** If the user has zero topics and visits `/learning/topics/<some-id>`, the cached tree is empty, the detail page can't find the topic, and shows "topic not found". Should the detail page fall back to a direct `GET /v1/learning/topics/{id}`? Spec says no (use cached tree only) — confirm this is acceptable for the user's flow.

For each challenge, label HIGH / MEDIUM / LOW → upgraded or dropped.

For MEDIUM/HIGH:
- Revisit the codebase if needed
- Update findings with corrected understanding

Stop. Present the reconciled findings (HIGH and MEDIUM only) before Role 3 begins.

---

## ROLE 3 — SENIOR ARCHITECT

Read the reconciled findings. Design the implementation. Do not write code yet.

Produce a concrete implementation plan covering:

1. **Type extensions in `web/lib/types.ts`** — exact fields for `LearningMaterial`, `LearningImportRequest`, `LearningImportResult`, `ImportSkip`. Plus the addition of `has_material: boolean` on `LearningTopic`. Decide whether the import payload's `ImportItem` / `ImportSection` etc. get their own types or are inlined.

2. **Hook extension in `web/hooks/use-learning.ts`**:
   - `getMaterial(topicId)` → `GET /v1/learning/topics/{id}/material`. Return type includes the null-body case.
   - `saveMaterial(topicId, body)` → `PATCH .../material`. Returns updated `MaterialOut`.
   - `deleteMaterial(topicId)` → `DELETE .../material?confirm=true`.
   - `importCurriculum(json, { dryRun })` → `POST /v1/learning/import?dry_run=...`.
   - Each follows the existing `try { await api(...) } catch (e) { toast.error(...) }` pattern. After successful (non-dry-run) import: re-fetch tree.

3. **npm install plan.** `cd web && npm install --save react-markdown@^9 remark-gfm@^4`. Add `@tailwindcss/typography` if Skeptic confirmed it's missing. Use `--legacy-peer-deps` only if Skeptic confirmed React 19 conflict.

4. **Component extraction**: move `SectionBlock` to `web/app/learning/_components/section-block.tsx` and `ItemRow` to `web/app/learning/_components/item-row.tsx`. State exactly which props become optional and the default behavior when missing (e.g., when `onAddItem` is undefined, the "+ Add item" form is not rendered).

5. **Topic detail page** at `web/app/learning/topics/[id]/page.tsx`. Layout:
   - **Header**: back link "← Library" → `/learning`, topic name, depth badge, active toggle.
   - **Material panel**: heading "Material", body via `react-markdown` + `remark-gfm`, `<div class="max-h-[60vh] overflow-y-auto prose prose-sm dark:prose-invert">`. "Edit" button toggles a `<Textarea class="text-base md:text-sm">`. "Save" calls `saveMaterial`. "Delete" → `confirm(...)` → `deleteMaterial`.
   - **Sections + items**: render `SectionBlock` for each, in the read-only mode (no add-item callback).
   - **Recent feedback**: small panel listing items with non-null `feedback`, latest first. Pull from the cached topic — no extra fetch.
   - Topic source: `useLearning().topics.find(t => t.id === id)`. Material source: state populated by `useEffect(() => { getMaterial(id).then(setMaterial) }, [id])`.
   - React 19 `params` handling per Skeptic's verdict.

6. **Import page** at `web/app/learning/import/page.tsx`. Layout:
   - **Header**: title, link to `/docs/learning-import-template.md` (if served as static) or a copy-paste of the template inline (decide based on whether `docs/` is served by Next.js — likely not; render a `<details>` with the template inline, sourced from a constant).
   - **Left pane**: `<Textarea class="font-mono text-base md:text-sm h-[60vh]">` for JSON paste.
   - **Right pane**: preview, initially empty. After "Validate (dry run)" click, render the `ImportResult` summary (e.g., "Will create: 3 topics, 12 sections, 45 items, 3 materials. Skipped: 1 (name_collision: pgvector)"). On JSON parse error or 422, show inline error.
   - **Buttons**: "Validate (dry run)" (always enabled when JSON-paste is non-empty), "Import" (disabled until a successful dry-run with `topics_created > 0`).
   - **On successful import**: `toast.success('Imported {N} topics')` + `router.push('/learning')` + `useLearning().refresh()` (or rely on the next page mount to refetch).
   - **429 handling**: toast "Too many imports — wait a minute".

7. **Tree view updates** in `web/app/learning/page.tsx`:
   - Wrap each topic title in `<Link href={\`/learning/topics/${topic.id}\`}>...</Link>`. Preserve existing inline edits / toggles — clicking the title navigates; clicking the toggle still toggles.
   - When `topic.has_material`: render the material badge.
   - Header: add `<Button asChild variant="outline"><Link href="/learning/import">Import</Link></Button>` next to the existing "Refresh today" button.

8. **Test plan**: per locked decision, **no new Vitest tests**. Instead, the Implementer writes a manual verification checklist into the PR description matching spec Step 10 (10 numbered checks). The Reviewer (Role 5) verifies the checklist is present and the boxes are credibly checked.

9. **What stays unchanged**:
   - Backend (entire `src/` tree) — Part 1 is frozen.
   - The daily learning cron behavior.
   - `useLearning()` existing methods and their callers (only additions, no edits).
   - V1 components beyond the `SectionBlock` / `ItemRow` extraction (which is a pure move).
   - Sidebar navigation.

10. **Constraints & Safety**:
    - Performance: large material content (>100KB markdown) will stutter on mobile. Fixed-height scrollable container only (`max-h-[60vh]`); do not chunk.
    - Backward compat: V1 tree view must continue to work for users who never use import.
    - Failure modes: 422 (validation), 429 (rate limit), 404 (topic missing), 500 (server) — all surface via toast.
    - Rollback strategy: revert the merge commit; no data migration to undo. Backend Part 1 stays running.
    - Accessibility: the topic-detail page must be keyboard navigable (back link focusable, edit textarea focusable). The material panel uses `prose` styles which include reasonable contrast.

For each decision:
- Provide reasoning
- If multiple approaches exist, list them and justify the chosen one

Stop. Present the plan. Do not implement until Role 4 begins.

If recalled by Role 5 for an architectural revision:
- Read the specific concern raised
- Update only the affected sections of the plan
- Note what changed and why
- Return to Role 4 to re-implement the affected parts

---

## ROLE 3.5 — SENIOR UI/UX EXPERT (conditional — included because this task has UI surface)

> Requires the UI/UX Pro Max skill installed at `~/.claude/skills/ui-ux-pro-max/`.

Read the Architect's plan. Before any implementation begins, generate a design system reference for the new UI components.

### Step 1 — Generate design system

Run the design system generator:
```bash
python3 ~/.claude/skills/ui-ux-pro-max/scripts/search.py "learning library curriculum reading material markdown two-pane import" --design-system -p "open-brain"
```

### Step 2 — Evaluate and adapt

Review the generated design system against:
- Existing UI patterns in the codebase (the V1 `web/app/learning/page.tsx`, the existing `task-list.tsx` in `web/components/`, color tokens defined in `web/app/globals.css` and `tailwind.config.ts`)
- The project's current design language: shadcn/ui primitives, neutral grays, badge style, button variants
- The Architect's plan constraints (the markdown panel, the two-pane import layout, the material-presence badge)

**Consistency rule**: A new feature must look like it belongs, not like a redesign.
- Keep existing color tokens (`secondary/30` for the badge per spec is consistent with existing pill styles in the app)
- Keep existing typography
- Adopt only the recommendations that fill gaps:
  - The two-pane import preview is novel for this app — pull layout patterns from the design system
  - Markdown rendering (prose styles) is novel — confirm the `@tailwindcss/typography` settings the design system suggests
  - Empty-state for the right preview pane is novel — adopt the recommendation

### Step 3 — Produce a design brief

Output a concise design brief for the Implementer containing:

- **Color tokens** — mapped to existing CSS variables. New tokens only if the design system flags an unfilled gap.
- **Typography** — the prose styles (`prose-sm`) and the JSON paste textarea (mono font, `text-base md:text-sm`). No new global text styles.
- **Component patterns** — the two-pane layout (`grid grid-cols-1 lg:grid-cols-2 gap-4`), the badge (`text-xs rounded-full px-2 py-0.5 bg-secondary/30`), the material panel container.
- **Interaction patterns** — hover states for the topic-title link (subtle underline or color shift), focus states for textareas, loading state for the import button (disabled + spinner), empty state for the right preview pane ("Paste JSON and click Validate to preview").
- **Anti-patterns** — no modal dialogs (inline edits only); no horizontal scroll on mobile; no hard-coded colors outside the token system.
- **Pre-delivery checklist** — relevant items:
  - Contrast ratios pass on `bg-secondary/30` badge
  - Cursor-pointer on clickable topic titles
  - Focus rings visible on textareas and buttons
  - Reduced-motion handling (no large animations introduced)
  - Material panel scrolls without trapping focus

The Implementer treats this brief as a constraint alongside the Architect's plan.

Stop. Present the design brief before Role 4 begins.

---

## ROLE 4 — IMPLEMENTER

Read the architect's plan and the design brief from Role 3.5. Both are binding constraints.

### Step 1 — Verification checklist (this task's "tests first" surrogate)

Per the locked decision (no Vitest coverage exists for `/learning`), this step replaces unit tests with the manual end-to-end checklist from spec Step 10. Add it to the PR description at the start, so the reviewer can tick boxes after implementation:

```
## Manual verification checklist (Step 10 from spec)
- [ ] alembic upgrade head — migration 0015 runs cleanly (verify Part 1 still applies)
- [ ] make start brings up local stack
- [ ] /learning/import: paste a small valid JSON → Validate → counts match
- [ ] DB row count unchanged after dry-run (psql query)
- [ ] Click Import → success toast + redirect to /learning → topic appears with "material" badge
- [ ] Click topic title → /learning/topics/{id} → markdown renders with code blocks + lists
- [ ] Edit material → Save → reload → update persists
- [ ] /today shows the new topic's items as todos with the yellow "Learning" badge after Refresh
- [ ] Complete one learning todo with feedback="just_right" → item marked done + feedback shows on detail page
- [ ] DELETE /v1/learning/topics/{id}?confirm=true (curl) → cascade removes material row (verify in psql)
```

### Step 2 — Install npm dependencies

```bash
cd web && npm install --save react-markdown@^9 remark-gfm@^4
```

If Skeptic flagged `@tailwindcss/typography` as missing, also `npm install --save @tailwindcss/typography` and register it in `tailwind.config.ts`.

If install errors with peer-dependency conflicts, retry with `--legacy-peer-deps`.

Confirm the `package-lock.json` updates and the new entries in `web/package.json` `dependencies`.

### Step 3 — Type extensions

Edit [web/lib/types.ts](web/lib/types.ts):
- Add `has_material: boolean` to `LearningTopic`
- Add `LearningMaterial`, `LearningImportRequest`, `LearningImportResult`, `ImportSkip` types matching the Pydantic shapes in Part 1.

### Step 4 — Hook extension

Edit [web/hooks/use-learning.ts](web/hooks/use-learning.ts):
- Add `getMaterial(topicId)`, `saveMaterial(topicId, body)`, `deleteMaterial(topicId)`, `importCurriculum(json, { dryRun })`.
- Match existing toast-on-error pattern.
- Re-fetch tree only after non-dry-run import success and after material save/delete.

### Step 5 — Component extraction (refactor)

Move `SectionBlock` and `ItemRow` from [web/app/learning/page.tsx](web/app/learning/page.tsx) into:
- `web/app/learning/_components/section-block.tsx`
- `web/app/learning/_components/item-row.tsx`

Make action callbacks (`onAddItem`, `onUpdateItem`, etc.) optional props. When missing, the corresponding control (e.g. "+ Add item" form) does not render. Update imports in `page.tsx`. Run `npm run build` (or `npm run lint`) to confirm no regressions in the existing tree view.

### Step 6 — Topic detail page

Create [web/app/learning/topics/[id]/page.tsx](web/app/learning/topics/[id]/page.tsx) per Architect's plan. Components:
- Header (back link, name, depth badge, active toggle)
- Material panel (markdown view + edit toggle + save/delete)
- Sections + items (read-only `SectionBlock` rendering)
- Recent feedback panel

The single-line comment beside the `<ReactMarkdown>` call: `{/* react-markdown v9 escapes raw HTML by default; do NOT add rehype-raw */}`.

### Step 7 — Import page

Create [web/app/learning/import/page.tsx](web/app/learning/import/page.tsx) per Architect's plan. Components:
- JSON paste textarea (left pane)
- Preview pane (right)
- Validate + Import buttons
- Error/429 toast handling

### Step 8 — Tree view updates

Edit [web/app/learning/page.tsx](web/app/learning/page.tsx):
- Wrap topic title in `<Link>`
- Render material badge when `has_material`
- Add "Import" button next to "Refresh today"

### Step 9 — Manual end-to-end verification

Walk through the Step 10 checklist live (per the spec). Tick each box. Take screenshots if it helps document the verification (optional).

### Final verification

- Run `npm run build` — clean compile
- Run `npm run lint` — clean
- Visit each of the three routes (`/learning`, `/learning/import`, `/learning/topics/<id>`) in the running dev server
- Test on mobile viewport (Chrome DevTools, 375px wide) — confirm no zoom-on-focus on the JSON paste textarea or material editor textarea
- Re-read the business context. Verify the implementation matches the original intent.

Final check — most important constraint: **after a successful import, the user lands on `/learning` and sees the new topic with the material badge, then can click into the detail page and re-read the markdown.** This is the entire UX target of V2.

Stop. Do not consider the task complete until reviewed.

If recalled by Role 5 or Role 6 for fixes:
- Read the specific issues listed
- Apply fixes to the affected code only
- Do not refactor or change unrelated code
- Summarize what changed and why
- Return to Role 5 for re-review

### Out of scope (DO NOT TOUCH in Part 2)

Reject any urge to:
- Modify `src/` (any backend file — Part 1 owns this entirely; if backend gap, escalate to Role 5 as CRITICAL ARCHITECTURAL)
- Add new endpoints or schemas
- Add Vitest tests (locked decision — manual checklist only)
- Add quiz/flashcard features (out of scope per spec line 16)
- Add multi-source-per-topic UI (spec line 369 — single material per topic)
- Add `rehype-raw` to react-markdown (spec line 364 — security hardening)
- Update the daily cron logic

---

## ROLE 5 — REVIEWER

Review the implementation as if this were a production PR. Be critical and precise.

**Review cycle: 1 of 2 maximum.**

Inputs:
- Architect's plan
- Design brief (Role 3.5)
- Full diff of changes
- Implementer's summary
- The completed Step 10 checklist in the PR description

Evaluate across:

1. **Correctness** — does the implementation fully satisfy the plan? Logical errors, missing cases?
2. **Scope adherence** — anything modified outside Part 2's scope (especially the backend)? Anything missing from the spec's frontend section?
3. **Code quality** — readability, structure, naming. Consistency with existing learning V1 patterns.
4. **Safety** — null handling, error boundaries, async race conditions (e.g., user clicks Import twice fast), backward compatibility (V1 tree behavior unchanged).
5. **System impact** — hidden coupling, performance (markdown render cost on large content), bundle size impact of `react-markdown`.
6. **Tests & validation** — Step 10 checklist completed and credibly evidenced (screenshots, log snippets, or descriptive notes per item)? Note explicitly there is no Vitest coverage gap that should grow further — flag this as a future debt item.
7. **Skeptic's concerns (cross-reference Role 2)** — each MEDIUM/HIGH item from Role 2 either addressed in code or consciously accepted with rationale. Flag silent ignores.
8. **Plan fidelity (cross-reference Role 3)** — implementation matches the Architect's plan; any deviation documented.
9. **Convention compliance (cross-reference Project Context)** — verify each of the 10 conventions in the checklist:
   - [ ] All `<input>`, `<textarea>` use `text-base md:text-sm`
   - [ ] Single DOM (no responsive duplicates that would break tests)
   - [ ] Toast-on-error pattern matches existing hook style
   - [ ] Tree refetch after non-dry-run import + after material mutations
   - [ ] No `rehype-raw`; comment present beside `<ReactMarkdown>`
   - [ ] No new env vars
   - [ ] Dynamic route folder is `[id]`
   - [ ] All API calls go through `web/lib/api.ts` helper
   - [ ] Confirm-on-delete preserved
   - [ ] React 19 `params` handled correctly (per Skeptic)
10. **Design compliance (cross-reference Role 3.5)**:
    - [ ] Color tokens match the brief (`bg-secondary/30` badge, etc.)
    - [ ] Typography matches the brief
    - [ ] Two-pane layout matches the brief
    - [ ] Anti-patterns avoided (no modals, no horizontal scroll, no hardcoded colors)
    - [ ] Pre-delivery checklist items satisfied
11. **Spec critical-files coverage** — cross-reference spec lines 380–397: every file listed under Part 2 (`web/lib/types.ts`, `web/hooks/use-learning.ts`, `web/app/learning/page.tsx`, `_components/section-block.tsx`, `_components/item-row.tsx`, `topics/[id]/page.tsx`, `import/page.tsx`, `web/package.json`) appears in the diff. Flag any missing file.

Output:
- Issues grouped by severity: CRITICAL / MAJOR / MINOR
- Concrete suggested fixes for CRITICAL and MAJOR
- For each CRITICAL: classify as IMPLEMENTATION (code bug) or ARCHITECTURAL (design flaw)

Loop-back rules:
- **CRITICAL IMPLEMENTATION** → return to Role 4. After fixes, return here. Increment cycle.
- **CRITICAL ARCHITECTURAL** → return to Role 3. After plan revision + Role 4 re-implements, return here. Increment cycle.
- **Backend gap discovered** (a frontend feature requires a Part 1 endpoint that doesn't exist) → mark **BLOCKED**, escalate to user — do NOT silently extend Part 1.
- **Cycle 2 with unresolved CRITICAL** → mark **BLOCKED**. Stop.
- **No CRITICAL** → proceed to Role 6.

---

## ROLE 6 — SECURITY REVIEWER

Review through a security lens.

**Review cycle: 1 of 2 maximum.**

Evaluate for this task specifically:

- **Markdown XSS via `react-markdown`.** v9 escapes raw HTML by default. Confirm `rehype-raw` is NOT in the imports anywhere. The material content is user-typed (or LLM-generated, then user-pasted) — must NOT bypass the escape. Search the diff for `rehype-raw` and confirm absence.

- **JSON paste payload.** The user pastes potentially-LLM-generated JSON into a textarea. The textarea content is sent to `POST /v1/learning/import` (server-side validated by Pydantic). The browser does not eval or render this JSON before send — confirm. The preview pane renders only `ImportResult` (from server response), not the user's input echoed back, so reflected XSS is impossible.

- **`source_url` in MaterialOut.** If a user imports material with a malicious `source_url` (e.g., `javascript:alert(1)`), and the topic-detail page renders `source_url` as an anchor, that's an XSS sink. Confirm:
  - Either the URL is validated against `https?://` on render, OR
  - Rendered with `rel="noopener noreferrer"` and a check, OR
  - Not rendered as a link at all (just display text).

- **DOM injection via topic name.** Topic names display as text (not `dangerouslySetInnerHTML`). Confirm no `dangerouslySetInnerHTML` anywhere in the diff.

- **Rate-limit handling.** 429 from `/v1/learning/import` triggers a friendly toast, not silent failure. Confirm.

Additionally evaluate (standard checklist):
- Authentication & authorization — all API calls go through the existing `api()` helper which carries the API key. New routes inherit auth. Confirm no `fetch()` direct calls bypass this.
- Input validation — server-side Pydantic catches bad JSON. Client-side: the textarea is just a string; no client-side validation needed beyond "is it valid JSON" before posting.
- Dependencies — `react-markdown@^9`, `remark-gfm@^4`, optionally `@tailwindcss/typography`. Confirm none have known CVEs (npm audit). All three are well-maintained projects.
- HTTPS — relies on existing infra (Caddy in prod, devserver locally). No change.
- Secrets — none introduced.

Output:
- **CRITICAL** — must fix (XSS, auth bypass, data exposure)
- **ADVISORY** — risks to document (e.g., `source_url` rendered without strict validation as a known acceptable risk)
- **HARDENING** — optional improvements (e.g., add `target="_blank" rel="noopener noreferrer"` defensively even if URL is validated)

Loop-back rules:
- **CRITICAL** → return to Role 4. After fixes, return to Role 5 → Role 6. Increment cycle.
- **Cycle 2 unresolved CRITICAL** → mark **BLOCKED**. Stop.
- **No CRITICAL** → final security sign-off.

---

## Completion

**TASK COMPLETE** when Role 5 and Role 6 both approve with no CRITICAL issues. Open a PR titled `feat(learning): bulk import page + topic detail with materials` with:
- Diff summary
- The Step 10 manual verification checklist (with checkboxes)
- Notable design decisions (markdown lib choice, no Vitest, optional callback refactor)
- Known gap: no Vitest coverage for `/learning` — same as V1 ship; not regressing, but not improving either

**BLOCKED** if any reviewer's cycle cap (2) is reached with unresolved CRITICAL issues, or if a backend gap is discovered — stop and escalate to the user.

After merge, the V2 Learning Library feature is fully shipped end-to-end.
