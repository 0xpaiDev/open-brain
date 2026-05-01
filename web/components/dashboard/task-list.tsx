"use client";

import { useEffect, useMemo, useState } from "react";
import { useTodos, filterTodayTodos, filterThisWeekTodos, groupDoneTodos } from "@/hooks/use-todos";
import { useTodoLabels } from "@/hooks/use-todo-labels";
import { useProjectLabels } from "@/hooks/use-project-labels";
import type { TodoItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { FocusCard } from "./focus-card";
import { ProjectGroup } from "./project-group";
import { DoneTaskRow } from "./task-row";
import { AddTaskForm } from "./add-task-form";
import { groupTodosByProject, PERSONAL } from "./task-utils";

// Re-exports preserved for tests.
export { formatDateButtonText, getDueBadge } from "./task-utils";

const FOCUS_KEY = "ob:todo:focusId";
const COLLAPSED_KEY = "ob:todo:collapsedProjects";

function tomorrowIsoDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function DeferAllPopover({
  count,
  onConfirm,
}: {
  count: number;
  onConfirm: (dueDate: string, reason?: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [deferDate, setDeferDate] = useState(tomorrowIsoDate());
  const [deferReason, setDeferReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!deferDate) return;
    setSubmitting(true);
    try {
      await onConfirm(deferDate, deferReason || undefined);
      setOpen(false);
      setDeferReason("");
      setDeferDate(tomorrowIsoDate());
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setDeferDate(tomorrowIsoDate());
      }}
    >
      <DialogTrigger
        render={
          <Button variant="outline" size="sm" aria-label={`Defer all ${count} tasks`}>
            <span className="material-symbols-outlined text-base mr-1">event_repeat</span>
            Defer all
          </Button>
        }
      />
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>
            Defer all {count} task{count === 1 ? "" : "s"}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <Input
            type="date"
            value={deferDate}
            onChange={(e) => setDeferDate(e.target.value)}
            aria-label="New due date"
          />
          <textarea
            value={deferReason}
            onChange={(e) => setDeferReason(e.target.value)}
            placeholder="Reason (optional)"
            className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary resize-none"
            rows={2}
            aria-label="Defer reason"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" disabled={!deferDate || submitting} onClick={handleSubmit}>
            Defer all
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TaskSkeleton() {
  return (
    <div
      className="bg-surface-container rounded-2xl p-6 space-y-3"
      role="status"
      aria-busy="true"
    >
      <div className="h-5 w-20 bg-surface-container-high rounded-lg animate-pulse" />
      {[1, 2, 3].map((n) => (
        <div key={n} className="flex items-center gap-3">
          <div className="w-5 h-5 rounded-full bg-surface-container-high animate-pulse" />
          <div className="h-4 flex-1 bg-surface-container-high rounded-lg animate-pulse" />
        </div>
      ))}
    </div>
  );
}

function loadCollapsed(): Set<string> {
  if (typeof window === "undefined") return new Set();
  try {
    const raw = window.localStorage.getItem(COLLAPSED_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.filter((x) => typeof x === "string")) : new Set();
  } catch {
    return new Set();
  }
}

function loadFocusId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(FOCUS_KEY);
  } catch {
    return null;
  }
}

export function TaskList() {
  const {
    openTodos,
    doneTodos,
    loading,
    error,
    completeTodo,
    addTodo,
    deferTodo,
    deferAll,
    editTodo,
    deleteTodo,
    loadMoreDone,
    hasMoreDone,
  } = useTodos();
  const { labels } = useTodoLabels();
  const { labels: projectLabels } = useProjectLabels();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeLabels, setActiveLabels] = useState<Set<string>>(new Set());
  const [loadingMore, setLoadingMore] = useState(false);
  const [focusId, setFocusIdState] = useState<string | null>(null);
  const [collapsed, setCollapsedState] = useState<Set<string>>(new Set());

  // Hydrate persisted UI state on mount (avoids SSR mismatch).
  useEffect(() => {
    setFocusIdState(loadFocusId());
    setCollapsedState(loadCollapsed());
  }, []);

  // Persist focus.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      if (focusId) window.localStorage.setItem(FOCUS_KEY, focusId);
      else window.localStorage.removeItem(FOCUS_KEY);
    } catch {
      // localStorage may be unavailable; degrade silently.
    }
  }, [focusId]);

  // Persist collapsed groups.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed]));
    } catch {
      // ignore
    }
  }, [collapsed]);

  const todayTodos = filterTodayTodos(openTodos);
  const weekTodos = filterThisWeekTodos(openTodos);
  const doneGroups = groupDoneTodos(doneTodos);

  const todoLabels = Array.from(
    new Set(openTodos.map((t) => t.label).filter(Boolean) as string[]),
  );

  const colorMap = useMemo(() => {
    const m: Record<string, string> = {};
    for (const p of projectLabels) m[p.name] = p.color;
    return m;
  }, [projectLabels]);

  // Adapt the new options-based editTodo signature back to the
  // (id, desc, dueDate, reason?) shape used by TaskRow / ProjectGroup so
  // those components remain unaware of project plumbing on the edit path.
  const editAdapter = (
    id: string,
    description: string,
    dueDate: string | null,
    reason?: string,
  ) => editTodo(id, description, dueDate, reason ? { reason } : {});

  function applyFilters(todos: TodoItem[]): TodoItem[] {
    let filtered = todos;
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      filtered = filtered.filter((t) => t.description.toLowerCase().includes(q));
    }
    if (activeLabels.size > 0) {
      filtered = filtered.filter((t) => t.label && activeLabels.has(t.label));
    }
    return filtered;
  }

  function toggleLabel(label: string) {
    setActiveLabels((prev) => {
      const next = new Set(prev);
      if (next.has(label)) next.delete(label);
      else next.add(label);
      return next;
    });
  }

  function toggleCollapsed(name: string) {
    setCollapsedState((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  // Stale focusId guard: if the persisted id no longer matches an open todo,
  // treat focus as empty.
  const focusedTodo = focusId
    ? openTodos.find((t) => t.id === focusId) ?? null
    : null;
  const effectiveFocusId = focusedTodo ? focusedTodo.id : null;

  function handleSelectFocus(id: string) {
    setFocusIdState((prev) => (prev === id ? null : id));
  }

  function handleClearFocus() {
    setFocusIdState(null);
  }

  function handleCompleteFromFocus(id: string) {
    setFocusIdState(null);
    void completeTodo(id);
  }

  // Per-project total across the OPEN list (not just the active tab) — used
  // by ProjectGroup as the progress-bar denominator so a group still shows
  // signal when filtered down.
  const allOpenByProject = useMemo(() => {
    const m: Record<string, number> = {};
    for (const t of openTodos) {
      const k = t.project ?? PERSONAL;
      m[k] = (m[k] ?? 0) + 1;
    }
    return m;
  }, [openTodos]);

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      await loadMoreDone();
    } finally {
      setLoadingMore(false);
    }
  }

  function renderGrouped(todosForTab: TodoItem[]) {
    const visible = applyFilters(todosForTab);
    const buckets = groupTodosByProject(visible, colorMap);

    if (buckets.length === 0) {
      return (
        <p className="text-on-surface-variant text-sm py-4 text-center">
          No tasks here — nice!
        </p>
      );
    }

    return (
      <>
        {buckets.map((b) => (
          <ProjectGroup
            key={b.key}
            name={b.key}
            color={b.color}
            todos={b.todos}
            totalInProject={allOpenByProject[b.key] ?? b.todos.length}
            collapsed={collapsed.has(b.key)}
            focusId={effectiveFocusId}
            onToggleCollapsed={() => toggleCollapsed(b.key)}
            onSelectFocus={handleSelectFocus}
            onComplete={(id) => {
              if (effectiveFocusId === id) setFocusIdState(null);
              void completeTodo(id);
            }}
            onEdit={editAdapter}
            onDelete={async (id) => {
              if (effectiveFocusId === id) setFocusIdState(null);
              await deleteTodo(id);
            }}
            onAdd={addTodo}
            labels={labels}
            projects={projectLabels}
          />
        ))}
      </>
    );
  }

  if (loading) return <TaskSkeleton />;
  if (error) {
    return (
      <div
        className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center text-center"
        role="alert"
      >
        <span className="material-symbols-outlined text-error text-2xl mb-2">error</span>
        <p className="text-sm text-error">{error}</p>
      </div>
    );
  }

  const focusedProject = focusedTodo
    ? focusedTodo.project ?? PERSONAL
    : undefined;
  const focusedColor = focusedProject ? colorMap[focusedProject] : undefined;

  return (
    <div className="bg-surface-container rounded-2xl p-6 space-y-4">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-lg">checklist</span>
        <h2 className="text-sm font-label font-medium text-on-surface-variant uppercase tracking-wider">
          Tasks
        </h2>
        {openTodos.length > 0 && (
          <span className="bg-primary/10 text-primary rounded-full px-2 py-0.5 text-xs font-label">
            {openTodos.length}
          </span>
        )}
      </div>

      <FocusCard
        todo={focusedTodo}
        accentColor={focusedColor}
        projectLabel={focusedProject}
        onClear={handleClearFocus}
        onComplete={handleCompleteFromFocus}
        onDefer={deferTodo}
        onDelete={async (id) => {
          setFocusIdState(null);
          await deleteTodo(id);
        }}
      />

      <Input
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search tasks..."
        aria-label="Search tasks"
      />

      {todoLabels.length > 0 && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {todoLabels.map((l) => (
            <button
              key={l}
              type="button"
              onClick={() => toggleLabel(l)}
              className={`text-xs rounded-full px-2.5 py-1 font-label transition-colors ${
                activeLabels.has(l)
                  ? "bg-primary text-on-primary"
                  : "bg-surface-container-high text-on-surface-variant hover:bg-surface-container-highest"
              }`}
            >
              {l}
            </button>
          ))}
          {activeLabels.size > 0 && (
            <button
              type="button"
              onClick={() => setActiveLabels(new Set())}
              className="text-xs text-on-surface-variant hover:text-on-surface transition-colors"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {openTodos.length === 0 && doneTodos.length === 0 ? (
        <p className="text-on-surface-variant text-sm py-4 text-center">
          No tasks yet. Add one below!
        </p>
      ) : (
        <Tabs defaultValue={0}>
          <TabsList variant="line">
            <TabsTrigger value={0}>
              Today
              {todayTodos.length > 0 && (
                <span className="bg-tertiary/10 text-tertiary rounded-full px-1.5 py-0.5 text-xs font-label ml-1">
                  {todayTodos.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value={1}>
              This Week
              {weekTodos.length > 0 && (
                <span className="bg-primary/10 text-primary rounded-full px-1.5 py-0.5 text-xs font-label ml-1">
                  {weekTodos.length}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value={2}>
              All
              {openTodos.length > 0 && (
                <span className="bg-primary/10 text-primary rounded-full px-1.5 py-0.5 text-xs font-label ml-1">
                  {openTodos.length}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
          <TabsContent value={0}>
            {(() => {
              const visibleToday = applyFilters(todayTodos);
              return (
                <>
                  {visibleToday.length > 1 && (
                    <div className="flex justify-end mb-2">
                      <DeferAllPopover
                        count={visibleToday.length}
                        onConfirm={(dueDate, reason) =>
                          deferAll(visibleToday.map((t) => t.id), dueDate, reason)
                        }
                      />
                    </div>
                  )}
                  {renderGrouped(todayTodos)}
                </>
              );
            })()}
          </TabsContent>
          <TabsContent value={1}>{renderGrouped(weekTodos)}</TabsContent>
          <TabsContent value={2}>{renderGrouped(openTodos)}</TabsContent>
        </Tabs>
      )}

      {doneTodos.length > 0 && (
        <Collapsible defaultOpen={false}>
          <CollapsibleTrigger className="flex items-center gap-2 py-2 text-sm font-medium text-on-surface-variant hover:text-on-surface transition-colors w-full">
            <span className="material-symbols-outlined text-base">expand_more</span>
            History ({doneTodos.length})
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="mt-1">
              {doneGroups.map((group) => (
                <Collapsible key={group.label} defaultOpen>
                  <CollapsibleTrigger className="flex items-center gap-2 py-1.5 text-sm text-on-surface-variant hover:text-on-surface transition-colors w-full">
                    <span className="material-symbols-outlined text-base">expand_more</span>
                    {group.label} ({group.todos.length})
                  </CollapsibleTrigger>
                  <CollapsibleContent>
                    <div className="space-y-0.5 mt-1">
                      {group.todos.map((todo) => (
                        <DoneTaskRow key={todo.id} todo={todo} />
                      ))}
                    </div>
                  </CollapsibleContent>
                </Collapsible>
              ))}
              {hasMoreDone && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleLoadMore}
                  disabled={loadingMore}
                  className="w-full mt-2 text-on-surface-variant"
                >
                  {loadingMore ? "Loading..." : "Load more"}
                </Button>
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      <AddTaskForm onAdd={addTodo} labels={labels} projects={projectLabels} />
    </div>
  );
}
