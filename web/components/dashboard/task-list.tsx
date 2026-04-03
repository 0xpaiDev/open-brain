"use client";

import { useState } from "react";
import { useTodos } from "@/hooks/use-todos";
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

export function getDueBadge(dueDate: string | null): { label: string; className: string } | null {
  if (!dueDate) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
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

function TaskRow({
  todo,
  onComplete,
}: {
  todo: TodoItem;
  onComplete: (id: string) => void;
}) {
  const [completing, setCompleting] = useState(false);
  const badge = getDueBadge(todo.due_date);

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
  onAdd: (description: string, priority: "high" | "normal" | "low", dueDate?: string) => Promise<void>;
}) {
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"high" | "normal" | "low">("normal");
  const [dueDate, setDueDate] = useState("");
  const [adding, setAdding] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = description.trim();
    if (!trimmed) return;

    setAdding(true);
    try {
      await onAdd(trimmed, priority, dueDate || undefined);
      setDescription("");
      setDueDate("");
      setPriority("normal");
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

      <Input
        type="date"
        value={dueDate}
        onChange={(e) => setDueDate(e.target.value)}
        className="w-36 hidden md:block"
        disabled={adding}
      />

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

export function TaskList() {
  const { openTodos, doneTodos, loading, error, completeTodo, addTodo } = useTodos();

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
        <div className="space-y-0.5">
          {openTodos.map((todo) => (
            <TaskRow key={todo.id} todo={todo} onComplete={completeTodo} />
          ))}
        </div>
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
