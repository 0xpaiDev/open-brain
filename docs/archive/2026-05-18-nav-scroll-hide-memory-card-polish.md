---\nstatus: shipped\ncreated: 2026-05-18\nshipped: 2026-05-18\n---

# Nav Scroll-Hide + Memory Card Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide top nav + mobile bottom tabs on scroll-down, reveal on scroll-up; clean up memory card visuals (remove left border, add missing badges, add HIGH badge for high-importance todo/task cards).

**Architecture:** A new `useScrollVisibility` hook encapsulates scroll-direction detection and returns a single boolean. `TopNav` and `BottomTabs` consume the hook independently and apply CSS `translate` transforms. Memory card changes are pure data + JSX in `TYPE_CONFIG` and the render function — no new files needed.

**Tech Stack:** React 19, Next.js, TypeScript, Tailwind v4, Vitest + @testing-library/react

---

## File Map

| Action | File |
|--------|------|
| Create | `web/hooks/use-scroll-visibility.ts` |
| Create | `web/__tests__/hooks/use-scroll-visibility.test.ts` |
| Modify | `web/components/layout/top-nav.tsx` |
| Modify | `web/components/layout/bottom-tabs.tsx` |
| Modify | `web/components/memory/memory-card.tsx` |

---

## Task 1: `useScrollVisibility` hook — test + implement

**Files:**
- Create: `web/hooks/use-scroll-visibility.ts`
- Create: `web/__tests__/hooks/use-scroll-visibility.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/__tests__/hooks/use-scroll-visibility.test.ts`:

```ts
import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

async function importHook() {
  vi.resetModules();
  const mod = await import("@/hooks/use-scroll-visibility");
  return mod.useScrollVisibility;
}

describe("useScrollVisibility", () => {
  beforeEach(() => {
    // jsdom doesn't fire scroll events — we'll call the listener directly
    vi.spyOn(window, "addEventListener");
    vi.spyOn(window, "removeEventListener");
    Object.defineProperty(window, "scrollY", { writable: true, value: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("starts visible", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());
    expect(result.current).toBe(true);
  });

  test("registers a scroll listener on mount", async () => {
    const useScrollVisibility = await importHook();
    renderHook(() => useScrollVisibility());
    expect(window.addEventListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function),
      { passive: true }
    );
  });

  test("removes scroll listener on unmount", async () => {
    const useScrollVisibility = await importHook();
    const { unmount } = renderHook(() => useScrollVisibility());
    unmount();
    expect(window.removeEventListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function)
    );
  });

  test("hides when scrolling down more than 10px", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    // Get the registered scroll handler
    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    act(() => {
      (window as any).scrollY = 50;
      handler();
    });

    expect(result.current).toBe(false);
  });

  test("shows when scrolling up after scrolling down", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    // Scroll down first
    act(() => {
      (window as any).scrollY = 50;
      handler();
    });
    expect(result.current).toBe(false);

    // Now scroll up
    act(() => {
      (window as any).scrollY = 30;
      handler();
    });
    expect(result.current).toBe(true);
  });

  test("does not hide for small downward scroll (<= 10px)", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    act(() => {
      (window as any).scrollY = 8;
      handler();
    });

    expect(result.current).toBe(true);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run __tests__/hooks/use-scroll-visibility.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

Create `web/hooks/use-scroll-visibility.ts`:

```ts
"use client";

import { useEffect, useRef, useState } from "react";

export function useScrollVisibility(): boolean {
  const [visible, setVisible] = useState(true);
  const lastScrollY = useRef(0);

  useEffect(() => {
    function handleScroll() {
      const currentY = window.scrollY;
      const delta = currentY - lastScrollY.current;

      if (delta > 10) {
        setVisible(false);
      } else if (delta < 0) {
        setVisible(true);
      }

      lastScrollY.current = currentY;
    }

    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  return visible;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run __tests__/hooks/use-scroll-visibility.test.ts
```

Expected: all 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/shu/projects/open-brain && git add web/hooks/use-scroll-visibility.ts web/__tests__/hooks/use-scroll-visibility.test.ts
git commit -m "feat(web): add useScrollVisibility hook"
```

---

## Task 2: Apply scroll-hide to TopNav

**Files:**
- Modify: `web/components/layout/top-nav.tsx`

Current `<header>` className (line 35):
```
"fixed top-0 z-50 w-full flex justify-between items-center px-6 py-3 bg-background/80 backdrop-blur-xl shadow-2xl shadow-black/20 font-headline tracking-tight"
```

- [ ] **Step 1: Wire up the hook and apply transform classes**

Replace the `TopNav` function in `web/components/layout/top-nav.tsx`. Add the import and `visible` state, then update the `<header>` className:

```tsx
"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth-provider";
import { useScrollVisibility } from "@/hooks/use-scroll-visibility";

export function TopNav() {
  const { logout } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");
  const visible = useScrollVisibility();

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("q", trimmed);
      params.delete("filter");
      router.push(`/memory?${params.toString()}`);
    } else {
      clearSearch();
    }
  }

  function clearSearch() {
    setQuery("");
    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    const qs = params.toString();
    router.push(qs ? `/memory?${qs}` : "/memory");
  }

  return (
    <header
      className={`fixed top-0 z-50 w-full flex justify-between items-center px-6 py-3 bg-background/80 backdrop-blur-xl shadow-2xl shadow-black/20 font-headline tracking-tight transition-transform duration-300 ease-in-out ${
        visible ? "translate-y-0" : "-translate-y-full"
      }`}
    >
      <div className="flex items-center gap-4">
        <span className="text-xl font-bold text-primary">Open Brain</span>
      </div>

      <div className="flex items-center gap-6">
        {/* Desktop search bar */}
        <form
          onSubmit={handleSearch}
          className="hidden md:flex items-center bg-surface-container-low px-4 py-1.5 rounded-full border border-outline-variant/15"
        >
          <span className="material-symbols-outlined text-outline text-sm mr-2">
            search
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="bg-transparent border-none focus:ring-0 focus:outline-none text-sm text-on-surface-variant w-64 placeholder:text-outline/50 font-body"
            placeholder="Search memories..."
            type="text"
          />
          {query && (
            <button
              type="button"
              onClick={clearSearch}
              className="text-outline hover:text-on-surface transition-colors ml-1"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          )}
        </form>

        <div className="flex items-center gap-4">
          {/* Mobile search icon */}
          <button
            onClick={() => router.push("/memory")}
            className="md:hidden text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95"
          >
            <span className="material-symbols-outlined">search</span>
          </button>
          <button className="text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button
            onClick={logout}
            className="text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95"
            title="Sign out"
          >
            <span className="material-symbols-outlined">logout</span>
          </button>
          <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-on-primary-container font-bold text-xs">
            S
          </div>
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 2: Run full test suite to verify no regressions**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/shu/projects/open-brain && git add web/components/layout/top-nav.tsx
git commit -m "feat(web): hide top nav on scroll down, reveal on scroll up"
```

---

## Task 3: Apply scroll-hide to BottomTabs

**Files:**
- Modify: `web/components/layout/bottom-tabs.tsx`

- [ ] **Step 1: Wire up the hook and apply transform classes**

Replace the full content of `web/components/layout/bottom-tabs.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useScrollVisibility } from "@/hooks/use-scroll-visibility";

const tabs = [
  { href: "/dashboard", icon: "today", label: "Today" },
  { href: "/memory", icon: "database", label: "Memory" },
  { href: "/chat", icon: "chat", label: "Chat" },
  { href: "/diary", icon: "auto_stories", label: "Diary" },
  { href: "/commitments", icon: "task_alt", label: "Commitments" },
];

export function BottomTabs() {
  const pathname = usePathname();
  const visible = useScrollVisibility();

  return (
    <nav
      className={`flex md:hidden fixed bottom-0 left-0 right-0 z-50 bg-surface-container-lowest border-t border-outline-variant/15 px-2 pt-1 pb-[calc(0.25rem+env(safe-area-inset-bottom,0px))] transition-transform duration-300 ease-in-out ${
        visible ? "translate-y-0" : "translate-y-full"
      }`}
    >
      {tabs.map((tab) => {
        const isActive = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-label transition-colors ${
              isActive ? "text-primary" : "text-outline"
            }`}
          >
            <span
              className="material-symbols-outlined text-xl"
              style={
                isActive
                  ? { fontVariationSettings: '"FILL" 1' }
                  : undefined
              }
            >
              {tab.icon}
            </span>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 2: Run full test suite**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/shu/projects/open-brain && git add web/components/layout/bottom-tabs.tsx
git commit -m "feat(web): hide bottom tabs on scroll down, reveal on scroll up"
```

---

## Task 4: Memory card — remove borders, add badges, add HIGH badge

**Files:**
- Modify: `web/components/memory/memory-card.tsx`

- [ ] **Step 1: Update TYPE_CONFIG and render logic**

Replace the full content of `web/components/memory/memory-card.tsx`:

```tsx
"use client";

import type { MemoryItemResponse, SearchResultItem } from "@/lib/types";
import { isSearchResult } from "@/hooks/use-memories";

function timeAgo(dateStr: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000,
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

const TYPE_CONFIG: Record<
  string,
  { icon: string; badge: string; className: string }
> = {
  memory: {
    icon: "format_quote",
    badge: "MEMORY",
    className: "bg-surface-container-high",
  },
  decision: {
    icon: "gavel",
    badge: "DECISION",
    className: "bg-surface-container-high",
  },
  task: {
    icon: "task_alt",
    badge: "TASK",
    className: "bg-surface-container-high",
  },
  context: {
    icon: "info",
    badge: "CONTEXT",
    className: "bg-surface-container",
  },
  todo: {
    icon: "checklist",
    badge: "TODO",
    className: "bg-surface-container-high",
  },
  todo_completion: {
    icon: "task_alt",
    badge: "DONE",
    className: "bg-surface-container-high",
  },
  daily_pulse: {
    icon: "vitals",
    badge: "PULSE",
    className: "bg-surface-container-high",
  },
};

const HIGH_PRIORITY_TYPES = new Set(["todo", "task"]);

interface MemoryCardProps {
  item: MemoryItemResponse | SearchResultItem;
}

export function MemoryCard({ item }: MemoryCardProps) {
  const config = TYPE_CONFIG[item.type] ?? { ...TYPE_CONFIG.memory, badge: item.type.toUpperCase() };
  const isSuperseded =
    !isSearchResult(item) && (item as MemoryItemResponse).is_superseded;
  const displayText = item.summary ?? item.content;
  const isHighPriority =
    !isSearchResult(item) &&
    HIGH_PRIORITY_TYPES.has(item.type) &&
    (item as MemoryItemResponse).importance_score != null &&
    (item as MemoryItemResponse).importance_score! >= 0.8;

  return (
    <div
      className={`${config.className} rounded-2xl p-5 flex flex-col gap-3 transition-all hover:shadow-lg hover:shadow-black/10 ${
        isSuperseded ? "opacity-50" : ""
      }`}
    >
      {/* Header row: icon + badge + score */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-on-surface-variant text-lg">
            {config.icon}
          </span>
          <span className="text-[10px] font-label font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-secondary/20 text-secondary">
            {config.badge}
          </span>
          {isHighPriority && (
            <span className="text-[10px] font-label font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-400">
              HIGH
            </span>
          )}
          {item.project && (
            <span className="text-[10px] font-label font-semibold tracking-wider px-2 py-0.5 rounded-full bg-primary/15 text-primary">
              {item.project}
            </span>
          )}
        </div>

        {/* Score pill */}
        {isSearchResult(item) ? (
          <span className="text-[10px] font-label font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">
            {Math.round(item.combined_score * 100)}% match
          </span>
        ) : (
          item.importance_score != null && (
            <span className="text-[10px] font-label px-2 py-0.5 rounded-full bg-outline-variant/15 text-on-surface-variant">
              {item.importance_score.toFixed(2)}
            </span>
          )
        )}
      </div>

      {/* Content */}
      <p className="text-sm text-on-surface font-body line-clamp-3 leading-relaxed">
        {displayText}
      </p>

      {/* Footer: timestamp */}
      {!isSearchResult(item) && (
        <span className="text-xs text-outline font-label mt-auto">
          {timeAgo(item.created_at)}
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Run full test suite**

```bash
cd /home/shu/projects/open-brain/web && npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /home/shu/projects/open-brain && git add web/components/memory/memory-card.tsx
git commit -m "feat(web): memory card polish — remove left border, add badges, HIGH badge for important todos"
```

---

## Self-Review Checklist

- [x] `useScrollVisibility` hook: spec says starts true, scroll down >10px → hide, any up → show, passive listener, cleanup. All covered in Task 1.
- [x] TopNav: `transition-transform`, `-translate-y-full` on hide. Covered in Task 2.
- [x] BottomTabs: `transition-transform`, `translate-y-full` on hide. Covered in Task 3.
- [x] `layout.tsx`: spec says no changes needed. Not included.
- [x] Remove `border-l-4 border-l-tertiary` from task/todo/todo_completion. Done in Task 4 TYPE_CONFIG.
- [x] Add `MEMORY` badge to `memory` type, `TASK` badge to `task` type. Done in Task 4.
- [x] HIGH badge: `importance_score >= 0.8` + type in `{todo, task}`. Done in Task 4.
- [x] No placeholders, no TBDs, all code complete.
- [x] `badge` field in TYPE_CONFIG changed from optional `badge?: string` to required `badge: string` — `config.badge` in JSX is now always defined, no conditional needed. Fallback for unknown types generates badge from type name.
