# Web Dashboard — Progress & Notes

## Session 1 — Backend Prereqs (2026-04-02)

### Completed

- **Fix: Todo ORDER BY** — Added `.order_by(TodoItem.created_at.desc())` to `list_todos()` in `src/api/routes/todos.py`. Without this, pagination with offset/limit was non-deterministic.

- **New endpoint: `GET /v1/calendar/today`** — File: `src/api/routes/calendar_api.py`. Wraps `fetch_today_events()` with a `status` field (`"ok"` vs `"unavailable"`) so frontend can distinguish "no events" from "calendar not connected". Includes 5-min in-memory TTL cache. Added `is_calendar_available()` helper to `src/integrations/calendar.py`.

- **New endpoint: `GET /v1/memory/recent`** — Added to `src/api/routes/memory.py`. Params: `limit` (1-100, default 20), `offset`, `type_filter`. Queries `memory_items WHERE is_superseded = false`, ordered by `created_at DESC`. Returns `{items: [...], total: int}`.

- **CORS** — Added `dashboard_origins: str = ""` to `src/core/config.py`. Comma-separated origins parsed in `main.py`. Set `DASHBOARD_ORIGINS=http://localhost:3000` in `.env` for dev.

- **Rate limiting** — Added `calendar_limit` (60/min) to `src/api/middleware/rate_limit.py`.

- **Tests** — 14 new tests (5 calendar, 8 memory/recent, 1 todo ordering). Full suite: 680 passed.

### Key Findings for Future Sessions

#### Memory table `type` values (Session 4 depends on this)
The `memory_items.type` column stores: `"memory"`, `"decision"`, `"task"`. These map directly to the bento grid card variants in the frontend spec. The `type_filter` query param on `/v1/memory/recent` accepts any of these values.

#### Route ordering gotcha
`/v1/memory/recent` MUST be registered before `/v1/memory/{memory_id}` in FastAPI, otherwise "recent" is matched as a `memory_id` path parameter and fails UUID validation with 422.

#### SQLite test timing
SQLite's `func.now()` server_default has low resolution — multiple inserts in the same test get identical `created_at` timestamps. For ordering tests, set `created_at` explicitly with spaced-out datetimes.

#### UUID objects in test fixtures
When creating ORM objects directly in tests (not via API), FK columns with `UUID(as_uuid=True)` expect UUID objects, not strings. Use `raw.id` directly (UUID), not `str(raw.id)`.

#### Pre-existing test failures (not introduced by Session 1)
- `test_bot_modules.py::test_core_commands_always_registered_when_modules_disabled` — SQLite + `pool_size`/`max_overflow` incompatibility in `database.py`
- `test_prevention_scripts.py::test_check_env_passes_with_clean_code` — `OPENBRAIN_API_URL` missing from `.env.example`

### Files Modified
- `src/api/routes/todos.py` — ORDER BY fix
- `src/api/routes/memory.py` — `/recent` endpoint + `_memory_item_to_response` helper
- `src/api/routes/calendar_api.py` — **new** calendar endpoint
- `src/integrations/calendar.py` — `is_calendar_available()` helper
- `src/core/config.py` — `dashboard_origins` setting
- `src/api/main.py` — calendar router registration + CORS update
- `src/api/middleware/rate_limit.py` — calendar rate limit
- `tests/test_calendar_api.py` — **new**
- `tests/test_memory_recent.py` — **new**
- `tests/test_todos.py` — ordering test added

---

## Session 2 — Frontend Foundation (2026-04-02)

### Completed

- **Scaffold** — Next.js 16.2.2 with App Router, TypeScript, Tailwind v4 in `/web`. Build compiles cleanly.

- **Dev proxy** — `next.config.ts` rewrites `/v1/:path*` → `http://localhost:8000/v1/:path*`.

- **Design tokens** — All MD3 color tokens from `inspiration.html` ported to `globals.css` `@theme inline` block (Tailwind v4 approach — no `tailwind.config.ts` needed). Fonts: Space Grotesk (headlines), Inter (body/labels). Border radii, Material Symbols font-variation-settings, and bento grid utility classes included. shadcn CSS variables mapped to our MD3 dark palette in `:root` and `.dark` blocks.

- **shadcn/ui** — Initialized with `base-nova` style. Components added: Button, Input, Textarea, Tabs, Dialog, Sonner (toast). Uses `@base-ui/react` (shadcn v4), not Radix.

- **Auth system** — `lib/api.ts` fetch wrapper with `X-API-Key` from localStorage. `AuthProvider` context validates stored key on mount via `GET /v1/pulse/today`. Auth gate dialog: full-screen, non-dismissable, validates key before storing. Gradient "Connect" button with loading spinner.

- **Shared layout** — Three components:
  - `sidebar.tsx` — Desktop only (`hidden md:flex`), fixed w-64, bg `#0e0e0e`, nav links with active state highlighting (filled icons), "Ingest New Memory" gradient CTA
  - `top-nav.tsx` — Fixed, backdrop-blur, "Open Brain" brand, desktop search bar, logout button
  - `bottom-tabs.tsx` — Mobile only (`flex md:hidden`), 5 tab icons matching sidebar

- **Root layout** — `<html class="dark">`, Google Fonts + Material Symbols via CDN `<link>`, `<AuthProvider>` wraps all children. Main content: `ml-0 md:ml-64 pt-16 pb-20 md:pb-8`.

- **Route stubs** — 5 pages: `/dashboard` (Today), `/memory` (Memory Bank), `/chat`, `/analytics`, `/diary` (last 3 are "Coming soon" stubs). Root `/` redirects to `/dashboard`.

### Tech Notes for Future Sessions

#### Next.js 16 + Tailwind v4
This project uses Next.js 16 (not 14) and Tailwind v4. Key differences:
- No `tailwind.config.ts` — design tokens go in `globals.css` `@theme inline {}` block
- CSS uses `@import "tailwindcss"` instead of `@tailwind base/components/utilities`
- `@custom-variant dark (&:is(.dark *))` for dark mode
- PostCSS plugin is `@tailwindcss/postcss`, not `tailwindcss`

#### shadcn/ui v4
- Uses `@base-ui/react` (not `@radix-ui/react-*`)
- Dialog: `DialogPrimitive.Root` accepts `open` and `modal` props directly
- Button uses `class-variance-authority` for variants
- Toast is `sonner` (not `@radix-ui/react-toast`)

#### AuthProvider pattern
- Renders loading spinner while validating stored key
- Renders `AuthGateDialog` when unauthenticated (no children visible)
- Renders children only when authenticated
- `logout()` removes key and resets state — used by top-nav logout button

### Files Created
- `web/next.config.ts` — dev proxy rewrites
- `web/app/globals.css` — design tokens + shadcn vars + base styles
- `web/app/layout.tsx` — root layout with providers
- `web/app/page.tsx` — root redirect to /dashboard
- `web/app/dashboard/page.tsx` — Today stub
- `web/app/memory/page.tsx` — Memory Bank stub
- `web/app/chat/page.tsx` — Chat stub
- `web/app/analytics/page.tsx` — Analytics stub
- `web/app/diary/page.tsx` — Diary stub
- `web/lib/api.ts` — fetch wrapper + auth helpers
- `web/lib/types.ts` — TypeScript interfaces for all API responses
- `web/lib/utils.ts` — cn() utility (shadcn generated)
- `web/components/auth-provider.tsx` — AuthContext + AuthProvider
- `web/components/auth-gate-dialog.tsx` — Full-screen auth dialog
- `web/components/layout/sidebar.tsx` — Desktop sidebar nav
- `web/components/layout/top-nav.tsx` — Top navbar with blur
- `web/components/layout/bottom-tabs.tsx` — Mobile bottom tabs
- `web/components/ui/button.tsx` — shadcn Button
- `web/components/ui/input.tsx` — shadcn Input
- `web/components/ui/textarea.tsx` — shadcn Textarea
- `web/components/ui/tabs.tsx` — shadcn Tabs
- `web/components/ui/dialog.tsx` — shadcn Dialog
- `web/components/ui/sonner.tsx` — shadcn Sonner (toast)
- `web/components.json` — shadcn config

### Gate Status
- [x] `npm run build` compiles cleanly (all 5 routes + root)
- [ ] `npm run dev` serves app, auth dialog appears (needs manual verification)
- [ ] Auth dialog validates key against API (needs running backend)
- [ ] Shell renders with sidebar/nav after auth (needs manual verification)
- [ ] Design tokens match inspiration.html (needs visual comparison)
- [ ] Mobile breakpoint shows bottom tabs (needs manual verification)

---

## Session 3 — Today Tab (2026-04-02)

### Completed

- **Bug fix: TodoListResponse.items → todos** — `web/lib/types.ts` field name didn't match backend's `TodoListResponse.todos`. Fixed before building hooks.

- **Infrastructure: Toaster mount** — `<Toaster />` from sonner was missing from `app/layout.tsx`. Added it so toast notifications work.

- **shadcn components** — Installed Collapsible (calendar mobile) and Select (task priority).

- **Types: PulseUpdate, TodoCreate, TodoUpdate** — Added request body interfaces to `web/lib/types.ts` matching backend Pydantic models.

- **Hook: use-pulse.ts** — Fetches `GET /v1/pulse/today` on mount, handles 404 as valid "no pulse" state. Exposes `createPulse()` (POST) and `submitPulse()` (PATCH with status="completed"). Toast feedback on success/error.

- **Hook: use-calendar.ts** — Fetches `GET /v1/calendar/today` on mount. Returns data with status field for "ok" vs "unavailable" differentiation.

- **Hook: use-todos.ts** — Parallel fetch of open + done todos. Client-side sort: priority (high→normal→low) → due date (soonest, nulls last) → created_at (oldest). Optimistic `completeTodo()` with rollback on error. `addTodo()` inserts into sorted list.

- **Component: morning-pulse.tsx** — 4 states: loading skeleton, no-pulse CTA, form mode (2-column desktop / stacked mobile with AI question blockquote, wake time, sleep quality 1-5, energy level 1-5, notes), summary mode (compact card with star/bolt ratings, truncated Q&A, timestamp).

- **Component: calendar-strip.tsx** — Desktop: horizontal scrollable strip of event pills with current/next event highlighting. Mobile: Collapsible with count badge. Empty states for "no events" vs "calendar not connected". Tomorrow preview row.

- **Component: task-list.tsx** — Open tasks with custom checkbox, priority left borders (high=tertiary, normal=outline-variant, low=transparent), due date badges (Today/Overdue/Tomorrow/date). Strikethrough animation on complete. Done section collapsed by default. Inline add form with Input + Select priority + date input (desktop) + Add button.

- **Dashboard page** — Replaced stub with three panels stacked vertically under "Today" heading with formatted date.

### Files Created
- `web/hooks/use-pulse.ts`
- `web/hooks/use-calendar.ts`
- `web/hooks/use-todos.ts`
- `web/components/dashboard/morning-pulse.tsx`
- `web/components/dashboard/calendar-strip.tsx`
- `web/components/dashboard/task-list.tsx`
- `web/components/ui/collapsible.tsx` (shadcn install)
- `web/components/ui/select.tsx` (shadcn install)

### Files Modified
- `web/app/layout.tsx` — Added Toaster
- `web/lib/types.ts` — Fixed TodoListResponse, added PulseUpdate/TodoCreate/TodoUpdate
- `web/app/dashboard/page.tsx` — Replaced stub with three-panel layout

### Gate Status
- [x] `npm run build` compiles cleanly
- [ ] Pulse form submits and transitions to summary (needs running backend)
- [ ] Tasks check off and new tasks appear (needs running backend)
- [ ] Calendar shows events or appropriate empty state (needs running backend)
- [ ] Mobile layout: panels stack, calendar collapses, no horizontal overflow (needs manual verification)

---

## Session 4 — Memory Tab (2026-04-02)

### Completed

- **Types: SearchResultItem, SearchResponse** — Added to `web/lib/types.ts` for search endpoint responses.

- **Hook: use-memories.ts** — Dual-mode hook: browse mode (`GET /v1/memory/recent`) and search mode (`GET /v1/search`). Supports `typeFilter` and `searchQuery` params. Pagination via `loadMore()` (offset += 20, append). `refresh()` resets and re-fetches. `ingestMemory()` posts to `POST /v1/memory` with toast feedback (distinguishes "queued" vs "duplicate"). Exports `isSearchResult()` type guard.

- **Component: memory-card.tsx** — Card variants by `type` field: "memory" (quote icon, default surface), "decision" (gavel icon, DECISION badge), "task" (task_alt icon, tertiary left border), "context" (info icon, CONTEXT badge). Common: line-clamp-3 content, relative timestamp via inline `timeAgo()` helper, importance score pill. Search results show combined_score as "X% match" badge. Superseded memories get muted opacity.

- **Component: bento-grid.tsx** — Uses existing `.bento-grid` CSS class from globals.css (responsive: auto-fill minmax(300px,1fr) desktop, single column mobile). Loading state: 6 skeleton cards with animate-pulse. Empty state: centered message with database/search_off icon. "Load more" button in browse mode when hasMore.

- **Component: smart-composer.tsx** — Tabbed composer using shadcn Tabs (base-ui, numeric values 0/1/2). Text tab: Textarea + optional source Input + "Commit Memory" gradient button. Link tab: URL input + "Commit Link" button. Media tab: "Coming soon" placeholder with dashed border and cloud_upload icon. Progress bar (h-1 bg-primary animate-pulse) shown during submission. Form clears on success.

- **Memory page orchestrator** — Rewrote `app/memory/page.tsx` as client component. Reads URL searchParams (`?filter=`, `?q=`) via `useSearchParams()`. Passes to `useMemories` hook. Renders SmartComposer + MemoryBentoGrid. Wrapped in `<Suspense>` for Next.js 16 compatibility.

- **Sidebar filters** — On `/memory` route, sidebar shows filter section: "All Memories" / "Decisions" / "Tasks" / "Context". Each links to `/memory?filter={type}`. Active filter highlighted with primary text + surface background. Uses `useSearchParams()` for active state detection.

- **TopNav search** — Wired existing search input: wrapped in `<form>`, useState for query value, navigates to `/memory?q={query}` on submit. X clear button strips `?q` param and returns to browse mode. Mobile search icon navigates to `/memory`.

### Infrastructure

- **Caddy deployed** — `0xpai.com` is live with auto-provisioned Let's Encrypt TLS certificate. Caddyfile reverse-proxies to API container. Security headers (HSTS, X-Content-Type-Options, X-Frame-Options, Referrer-Policy) applied. Port 8000 locked to `127.0.0.1` (traffic must go through Caddy).

- **DOMAIN env var** — Set `DOMAIN=0xpai.com` in VM `.env` at `/opt/open-brain/.env`.

- **Port lockdown** — Changed `docker-compose.yml` API ports from `0.0.0.0:8000:8000` to `127.0.0.1:8000:8000`. Committed and deployed.

### Files Created
- `web/hooks/use-memories.ts`
- `web/components/memory/memory-card.tsx`
- `web/components/memory/bento-grid.tsx`
- `web/components/memory/smart-composer.tsx`

### Files Modified
- `web/lib/types.ts` — Added SearchResultItem, SearchResponse
- `web/app/memory/page.tsx` — Rewrote from stub to orchestrator
- `web/components/layout/sidebar.tsx` — Added memory filter links + useSearchParams
- `web/components/layout/top-nav.tsx` — Wired search input with form submit + clear
- `docker-compose.yml` — API port locked to 127.0.0.1
- `Caddyfile` — Already configured (no changes needed)

### Gate Status
- [x] `npm run build` compiles cleanly (all routes)
- [x] Caddy live at https://0xpai.com with TLS
- [x] API responds through Caddy: `curl https://0xpai.com/ready` → 200
- [ ] Text ingest works (toast confirms, card appears on refresh) — needs manual verification
- [ ] Link ingest works — needs manual verification
- [ ] Type filters narrow the grid — needs manual verification
- [ ] Search returns results and displays them — needs manual verification
- [ ] "Load more" pagination works — needs manual verification
- [ ] Mobile layout is single-column — needs manual verification

---

## Session 5 — Polish + Deployment (2026-04-02)

### Completed

- **Docker: `web/Dockerfile`** — Multi-stage build (deps → builder → runner) using `node:22-alpine`. Stage 1 installs deps via `npm ci`, stage 2 builds with `npm run build` (standalone output), stage 3 copies `.next/standalone`, `.next/static`, `public/` into a minimal runner with non-root user (`nextjs`, UID 1001). Exposes port 3000.

- **Docker: `web/.dockerignore`** — Excludes `node_modules/`, `.next/`, `.git/`, `*.log`, `.env*` from build context.

- **next.config.ts: standalone output** — Added `output: "standalone"` to enable self-contained production builds. Generates `.next/standalone/server.js` with only required `node_modules`.

- **docker-compose.yml: `web` service** — Profile `web`, build context `./web`, port `127.0.0.1:3000:3000` (localhost only, behind Caddy), `HOSTNAME=0.0.0.0` env, healthcheck via wget, resource limits 0.5 CPU / 256M RAM, `openbrain` network.

- **Caddyfile: dual routing** — Replaced single `reverse_proxy api:8000` with path-based `handle` blocks: `/v1/*`, `/ready`, `/health` → `api:8000`; catch-all `handle` → `web:3000`. Security headers, gzip, logging unchanged.

- **Error state: MemoryBentoGrid** — Added `error` prop to `MemoryBentoGridProps`. Shows `cloud_off` icon + error message when API fails and no items loaded. Wired `error` from `useMemories` hook through `memory/page.tsx`.

- **Error state: morning-pulse + task-list** — Added Material Symbols `error` icon before error text in both components. Added `role="alert"` for screen reader announcements. Matches existing calendar-strip pattern.

- **Accessibility: auth dialog** — Added `<label htmlFor="api-key-input" className="sr-only">` and `id` on Input for proper label association. Added `role="alert"` on error paragraph.

- **Accessibility: task checkboxes** — Added `role="checkbox"`, `aria-checked`, `aria-label` with task description. Expanded touch target to 44px (`min-w-11 min-h-11`) while keeping 20px visual circle.

- **Accessibility: loading skeletons** — Added `role="status"` and `aria-busy="true"` to skeleton wrapper divs in PulseSkeleton, CalendarSkeleton, TaskSkeleton, and MemoryBentoGrid skeleton grid.

### Mobile QA (verified in code)

- Bottom tabs: `flex md:hidden` — visible on mobile only ✓
- Sidebar: `hidden md:flex` — desktop only ✓
- Bento grid: single column via `@media (max-width: 768px)` in globals.css ✓
- Calendar: collapsible on mobile, horizontal strip on desktop ✓
- Main content: `pb-20` clears bottom tabs on mobile ✓
- Task date picker: `hidden md:block` — desktop only ✓

### Files Created
- `web/Dockerfile` — multi-stage Next.js standalone build
- `web/.dockerignore` — build context exclusions

### Files Modified
- `web/next.config.ts` — added `output: "standalone"`
- `docker-compose.yml` — added `web` service (profile: web)
- `Caddyfile` — split routing: API + frontend via `handle` blocks
- `web/components/memory/bento-grid.tsx` — added `error` prop + error state UI + skeleton aria-busy
- `web/app/memory/page.tsx` — wired `error` from hook to MemoryBentoGrid
- `web/components/dashboard/morning-pulse.tsx` — error icon + role="alert" + skeleton aria-busy
- `web/components/dashboard/calendar-strip.tsx` — skeleton aria-busy
- `web/components/dashboard/task-list.tsx` — error icon + role="alert" + skeleton aria-busy + checkbox ARIA + 44px touch target
- `web/components/auth-gate-dialog.tsx` — sr-only label + error role="alert"

### Gate Status
- [x] `npm run build` compiles cleanly with standalone output
- [x] `.next/standalone/server.js` generated
- [ ] `docker compose --profile web --profile caddy --profile api up --build` serves dashboard at https://0xpai.com
- [ ] API routes work at https://0xpai.com/v1/*
- [ ] Full flow: auth → dashboard → memory ingest → search
- [ ] No blank panels on API errors
- [ ] Mobile layout correct (needs manual verification on device)
