"use client";

import { useState } from "react";
import { useTodos, filterTodayTodos, filterThisWeekTodos, groupDoneTodos } from "@/hooks/use-todos";
import { useTodoLabels } from "@/hooks/use-todo-labels";
import type { TodoItem, TodoLabel } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

export function formatDateButtonText(dateStr: string): string {
  if (!dateStr) return "No date";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(dateStr + "T00:00:00");
  date.setHours(0, 0, 0, 0);
  const diff = Math.floor((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function getDueBadge(dueDate: string | null, startDate?: string | null): { label: string; className: string } | null {
  if (!dueDate) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);

  // Active badge for date ranges: start_date <= today <= due_date
  if (startDate) {
    const start = new Date(startDate);
    start.setHours(0, 0, 0, 0);
    if (today >= start && today <= due) {
      return { label: "Active", className: "bg-primary/10 text-primary" };
    }
  }

  const diffDays = Math.floor((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays < 0) return { label: "Overdue", className: "bg-error/10 text-error" };
  if (diffDays === 0) return { label: "Today", className: "bg-tertiary/10 text-tertiary" };
  if (diffDays === 1) return { label: "Tomorrow", className: "bg-primary/10 text-primary" };

  return {
    label: due.toLocaleDateString([], { month: "short", day: "numeric" }),
    className: "bg-surface-container-high text-on-surface-variant",
  };
}

function priorityBorderClass(priority: string): string {
  switch (priority) {
    case "high":
      return "border-l-[3px] border-l-tertiary";
    case "normal":
      return "border-l-[3px] border-l-outline-variant";
    default:
      return "border-l-[3px] border-l-transparent";
  }
}

function DeferPopover({
  todoId,
  onDefer,
}: {
  todoId: string;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
}) {
  const [deferDate, setDeferDate] = useState("");
  const [deferReason, setDeferReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [open, setOpen] = useState(false);

  async function handleSubmit() {
    if (!deferDate) return;
    setSubmitting(true);
    try {
      await onDefer(todoId, deferDate, deferReason || undefined);
      setOpen(false);
      setDeferDate("");
      setDeferReason("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button
            type="button"
            aria-label="Defer task"
            className="min-w-8 min-h-8 flex items-center justify-center rounded-md hover:bg-surface-container-high transition-colors"
          />
        }
      >
        <span className="material-symbols-outlined text-on-surface-variant text-base">calendar_month</span>
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Defer Task</DialogTitle>
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
          <Button
            variant="outline"
            size="sm"
            onClick={() => setOpen(false)}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!deferDate || submitting}
            onClick={handleSubmit}
          >
            Defer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function DatePickerDialog({
  dueDate,
  startDate,
  isRange,
  onApply,
  disabled,
}: {
  dueDate: string;
  startDate: string;
  isRange: boolean;
  onApply: (dueDate: string, startDate: string, isRange: boolean) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [localDue, setLocalDue] = useState(dueDate);
  const [localStart, setLocalStart] = useState(startDate);
  const [localRange, setLocalRange] = useState(isRange);

  function handleOpenChange(next: boolean) {
    if (next) {
      setLocalDue(dueDate);
      setLocalStart(startDate);
      setLocalRange(isRange);
    }
    setOpen(next);
  }

  function handleApply() {
    onApply(localDue, localRange ? localStart : "", localRange);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <button
            type="button"
            disabled={disabled}
            className="flex items-center gap-1 text-sm px-3 py-1 h-7 rounded-full border border-input bg-transparent hover:bg-muted transition-colors"
            aria-label="Pick date"
          />
        }
      >
        <span className="material-symbols-outlined text-base">calendar_month</span>
        <span>{formatDateButtonText(dueDate)}</span>
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Due Date</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <Input
            type="date"
            value={localDue}
            onChange={(e) => setLocalDue(e.target.value)}
            aria-label="Due date"
          />
          <label className="flex items-center gap-2 text-sm text-on-surface-variant">
            <input
              type="checkbox"
              checked={localRange}
              onChange={(e) => setLocalRange(e.target.checked)}
              className="accent-primary"
            />
            Date range
          </label>
          {localRange && (
            <Input
              type="date"
              value={localStart}
              onChange={(e) => setLocalStart(e.target.value)}
              aria-label="Start date"
            />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleApply}>
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TaskRow({
  todo,
  onComplete,
  onDefer,
}: {
  todo: TodoItem;
  onComplete: (id: string) => void;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
}) {
  const [completing, setCompleting] = useState(false);
  const badge = getDueBadge(todo.due_date, todo.start_date);

  function handleCheck() {
    setCompleting(true);
    // Animate then complete
    setTimeout(() => onComplete(todo.id), 300);
  }

  return (
    <div
      className={`flex items-center gap-3 py-2 px-3 rounded-lg hover:bg-surface-container-high/50 transition-all ${priorityBorderClass(
        todo.priority
      )} ${completing ? "opacity-50" : ""}`}
    >
      <button
        type="button"
        role="checkbox"
        aria-checked={completing}
        aria-label={`Complete: ${todo.description}`}
        onClick={handleCheck}
        disabled={completing}
        className="min-w-11 min-h-11 flex items-center justify-center shrink-0"
      >
        <span className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all ${
          completing
            ? "bg-primary border-primary"
            : "border-outline-variant hover:border-primary"
        }`}>
          {completing && (
            <span className="material-symbols-outlined text-on-primary text-xs">check</span>
          )}
        </span>
      </button>

      <span
        className={`flex-1 text-sm transition-all ${
          completing ? "line-through text-on-surface-variant" : "text-on-surface"
        }`}
      >
        {todo.description}
      </span>

      <DeferPopover todoId={todo.id} onDefer={onDefer} />

      {todo.label && (
        <span className="text-xs rounded-full px-2 py-0.5 shrink-0 font-label bg-surface-container-high text-on-surface-variant">
          {todo.label}
        </span>
      )}

      {badge && (
        <span className={`text-xs rounded-full px-2 py-0.5 shrink-0 font-label ${badge.className}`}>
          {badge.label}
        </span>
      )}
    </div>
  );
}

function DoneTaskRow({ todo }: { todo: TodoItem }) {
  return (
    <div className="flex items-center gap-3 py-1.5 px-3 opacity-60">
      <div className="w-5 h-5 rounded-full bg-primary/30 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-primary text-xs">check</span>
      </div>
      <span className="flex-1 text-sm text-on-surface-variant line-through">
        {todo.description}
      </span>
    </div>
  );
}

function getTomorrowDateString(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

function AddTaskForm({
  onAdd,
  labels,
}: {
  onAdd: (description: string, priority: "high" | "normal" | "low", dueDate?: string, startDate?: string, label?: string) => Promise<void>;
  labels: TodoLabel[];
}) {
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"high" | "normal" | "low">("normal");
  const [dueDate, setDueDate] = useState(getTomorrowDateString());
  const [startDate, setStartDate] = useState("");
  const [isRange, setIsRange] = useState(false);
  const [label, setLabel] = useState("");
  const [adding, setAdding] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = description.trim();
    if (!trimmed) return;

    setAdding(true);
    try {
      await onAdd(
        trimmed,
        priority,
        dueDate || undefined,
        isRange && startDate ? startDate : undefined,
        label || undefined,
      );
      setDescription("");
      setDueDate(getTomorrowDateString());
      setStartDate("");
      setPriority("normal");
      setIsRange(false);
      setLabel("");
    } finally {
      setAdding(false);
    }
  }

  function handleDateApply(newDue: string, newStart: string, newRange: boolean) {
    setDueDate(newDue);
    setStartDate(newStart);
    setIsRange(newRange);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-2 mt-4 pt-4 border-t border-outline-variant/20"
    >
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Add a task..."
        className="w-full"
        disabled={adding}
      />

      <div className="flex items-center gap-2">
        <Select value={priority} onValueChange={(v) => setPriority(v as "high" | "normal" | "low")}>
          <SelectTrigger size="sm" className="w-24 rounded-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="high">High</SelectItem>
            <SelectItem value="normal">Normal</SelectItem>
            <SelectItem value="low">Low</SelectItem>
          </SelectContent>
        </Select>

        {labels.length > 0 && (
          <Select value={label} onValueChange={(v) => setLabel(v ?? "")}>
            <SelectTrigger size="sm" className="w-28 rounded-full" aria-label="Label">
              <SelectValue placeholder="Label" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">None</SelectItem>
              {labels.map((l) => (
                <SelectItem key={l.name} value={l.name}>
                  <span className="flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: l.color }} />
                    {l.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <DatePickerDialog
          dueDate={dueDate}
          startDate={startDate}
          isRange={isRange}
          onApply={handleDateApply}
          disabled={adding}
        />

        <Button
          type="submit"
          size="sm"
          disabled={adding || !description.trim()}
          className="rounded-full active:scale-95 transition-transform ml-auto"
        >
          <span className="material-symbols-outlined text-base">add</span>
          Add
        </Button>
      </div>
    </form>
  );
}

function TaskSkeleton() {
  return (
    <div className="bg-surface-container rounded-2xl p-6 space-y-3" role="status" aria-busy="true">
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

function TaskListContent({
  todos,
  completeTodo,
  deferTodo,
  emptyMessage,
}: {
  todos: TodoItem[];
  completeTodo: (id: string) => Promise<void>;
  deferTodo: (id: string, dueDate: string, reason?: string) => Promise<void>;
  emptyMessage: string;
}) {
  if (todos.length === 0) {
    return (
      <p className="text-on-surface-variant text-sm py-4 text-center">
        {emptyMessage}
      </p>
    );
  }
  return (
    <div className="space-y-0.5">
      {todos.map((todo) => (
        <TaskRow key={todo.id} todo={todo} onComplete={completeTodo} onDefer={deferTodo} />
      ))}
    </div>
  );
}

export function TaskList() {
  const { openTodos, doneTodos, loading, error, completeTodo, addTodo, deferTodo, loadMoreDone, hasMoreDone } = useTodos();
  const { labels } = useTodoLabels();
  const [searchQuery, setSearchQuery] = useState("");
  const [activeLabels, setActiveLabels] = useState<Set<string>>(new Set());
  const [loadingMore, setLoadingMore] = useState(false);

  const todayTodos = filterTodayTodos(openTodos);
  const weekTodos = filterThisWeekTodos(openTodos);
  const doneGroups = groupDoneTodos(doneTodos);

  // Derive unique labels from open todos for filter chips
  const todoLabels = Array.from(new Set(openTodos.map((t) => t.label).filter(Boolean) as string[]));

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

  async function handleLoadMore() {
    setLoadingMore(true);
    try {
      await loadMoreDone();
    } finally {
      setLoadingMore(false);
    }
  }

  if (loading) return <TaskSkeleton />;
  if (error) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center text-center" role="alert">
        <span className="material-symbols-outlined text-error text-2xl mb-2">error</span>
        <p className="text-sm text-error">{error}</p>
      </div>
    );
  }

  return (
    <div className="bg-surface-container rounded-2xl p-6">
      <div className="flex items-center gap-2 mb-3">
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

      {/* Search bar */}
      <Input
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        placeholder="Search tasks..."
        className="mb-2"
        aria-label="Search tasks"
      />

      {/* Label filter chips */}
      {todoLabels.length > 0 && (
        <div className="flex items-center gap-1.5 mb-2 flex-wrap">
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
          <TabsList variant="line" className="mb-2">
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
            <TaskListContent
              todos={applyFilters(todayTodos)}
              completeTodo={completeTodo}
              deferTodo={deferTodo}
              emptyMessage="Nothing due today — nice!"
            />
          </TabsContent>
          <TabsContent value={1}>
            <TaskListContent
              todos={applyFilters(weekTodos)}
              completeTodo={completeTodo}
              deferTodo={deferTodo}
              emptyMessage="Nothing due this week"
            />
          </TabsContent>
          <TabsContent value={2}>
            <TaskListContent
              todos={applyFilters(openTodos)}
              completeTodo={completeTodo}
              deferTodo={deferTodo}
              emptyMessage="No open tasks"
            />
          </TabsContent>
        </Tabs>
      )}

      {doneTodos.length > 0 && (
        <Collapsible defaultOpen={false}>
          <CollapsibleTrigger className="flex items-center gap-2 py-2 text-sm font-medium text-on-surface-variant hover:text-on-surface transition-colors w-full mt-3">
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

      <AddTaskForm onAdd={addTodo} labels={labels} />
    </div>
  );
}
