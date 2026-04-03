"use client";

import { useState } from "react";
import { useTodos, filterTodayTodos } from "@/hooks/use-todos";
import type { TodoItem } from "@/lib/types";
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
            className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary resize-none"
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

      {badge && (
        <span className={`text-xs rounded-full px-2 py-0.5 flex-shrink-0 font-label ${badge.className}`}>
          {badge.label}
        </span>
      )}
    </div>
  );
}

function DoneTaskRow({ todo }: { todo: TodoItem }) {
  return (
    <div className="flex items-center gap-3 py-1.5 px-3 opacity-60">
      <div className="w-5 h-5 rounded-full bg-primary/30 flex items-center justify-center flex-shrink-0">
        <span className="material-symbols-outlined text-primary text-xs">check</span>
      </div>
      <span className="flex-1 text-sm text-on-surface-variant line-through">
        {todo.description}
      </span>
    </div>
  );
}

function AddTaskForm({
  onAdd,
}: {
  onAdd: (description: string, priority: "high" | "normal" | "low", dueDate?: string, startDate?: string) => Promise<void>;
}) {
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"high" | "normal" | "low">("normal");
  const [dueDate, setDueDate] = useState("");
  const [startDate, setStartDate] = useState("");
  const [isRange, setIsRange] = useState(false);
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
      );
      setDescription("");
      setDueDate("");
      setStartDate("");
      setPriority("normal");
      setIsRange(false);
    } finally {
      setAdding(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-outline-variant/20"
    >
      <Input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Add a task..."
        className="flex-1 min-w-[150px]"
        disabled={adding}
      />

      <Select value={priority} onValueChange={(v) => setPriority(v as "high" | "normal" | "low")}>
        <SelectTrigger size="sm" className="w-24">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="high">High</SelectItem>
          <SelectItem value="normal">Normal</SelectItem>
          <SelectItem value="low">Low</SelectItem>
        </SelectContent>
      </Select>

      <button
        type="button"
        onClick={() => setIsRange((v) => !v)}
        className={`text-xs px-2 py-1 rounded-md border transition-colors hidden md:inline-flex ${
          isRange
            ? "border-primary text-primary bg-primary/10"
            : "border-outline-variant text-on-surface-variant hover:border-primary"
        }`}
        title={isRange ? "Switch to single date" : "Switch to date range"}
      >
        {isRange ? "Range" : "Date"}
      </button>

      {isRange ? (
        <>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="w-36 hidden md:block"
            disabled={adding}
            aria-label="From date"
            title="From"
          />
          <span className="text-xs text-on-surface-variant hidden md:inline">to</span>
          <Input
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="w-36 hidden md:block"
            disabled={adding}
            aria-label="Due date"
            title="Due"
          />
        </>
      ) : (
        <Input
          type="date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
          className="w-36 hidden md:block"
          disabled={adding}
        />
      )}

      <Button
        type="submit"
        size="sm"
        disabled={adding || !description.trim()}
        className="active:scale-95 transition-transform"
      >
        <span className="material-symbols-outlined text-base">add</span>
        Add
      </Button>
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
  const { openTodos, doneTodos, loading, error, completeTodo, addTodo, deferTodo } = useTodos();
  const todayTodos = filterTodayTodos(openTodos);

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
              todos={todayTodos}
              completeTodo={completeTodo}
              deferTodo={deferTodo}
              emptyMessage="Nothing due today — nice!"
            />
          </TabsContent>
          <TabsContent value={1}>
            <TaskListContent
              todos={openTodos}
              completeTodo={completeTodo}
              deferTodo={deferTodo}
              emptyMessage="No open tasks"
            />
          </TabsContent>
        </Tabs>
      )}

      {doneTodos.length > 0 && (
        <Collapsible>
          <CollapsibleTrigger className="flex items-center gap-2 mt-3 py-1.5 text-sm text-on-surface-variant hover:text-on-surface transition-colors w-full">
            <span className="material-symbols-outlined text-base">expand_more</span>
            Show {doneTodos.length} completed
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="space-y-0.5 mt-1">
              {doneTodos.map((todo) => (
                <DoneTaskRow key={todo.id} todo={todo} />
              ))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      )}

      <AddTaskForm onAdd={addTodo} />
    </div>
  );
}
