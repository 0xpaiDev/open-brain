"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TodoItem, TodoListResponse } from "@/lib/types";
import { toast } from "sonner";

export const PRIORITY_ORDER: Record<string, number> = { high: 0, normal: 1, low: 2 };

export function sortOpenTodos(todos: TodoItem[]): TodoItem[] {
  return [...todos].sort((a, b) => {
    const pDiff = (PRIORITY_ORDER[a.priority] ?? 1) - (PRIORITY_ORDER[b.priority] ?? 1);
    if (pDiff !== 0) return pDiff;

    if (a.due_date && b.due_date) return a.due_date.localeCompare(b.due_date);
    if (a.due_date) return -1;
    if (b.due_date) return 1;

    return a.created_at.localeCompare(b.created_at);
  });
}

/** Get Monday 00:00 of the week containing `date`. ISO weeks start on Monday. */
function getMonday(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  const day = d.getDay();
  // getDay(): 0=Sun 1=Mon ... 6=Sat → offset to Monday
  const diff = day === 0 ? 6 : day - 1;
  d.setDate(d.getDate() - diff);
  return d;
}

/** Filter todos due within the current ISO week (Mon–Sun), including overdue within the week. */
export function filterThisWeekTodos(todos: TodoItem[]): TodoItem[] {
  const now = new Date();
  const monday = getMonday(now);
  const nextMonday = new Date(monday);
  nextMonday.setDate(nextMonday.getDate() + 7);

  return todos.filter((todo) => {
    if (!todo.due_date) return false;
    const due = new Date(todo.due_date);
    due.setHours(0, 0, 0, 0);
    return due >= monday && due < nextMonday;
  });
}

export interface DoneGroup {
  label: string;
  todos: TodoItem[];
}

/** Group done todos by completion period. Uses `updated_at` as proxy for completion time. */
export function groupDoneTodos(todos: TodoItem[]): DoneGroup[] {
  if (todos.length === 0) return [];

  const now = new Date();
  const thisMonday = getMonday(now);
  const lastMonday = new Date(thisMonday);
  lastMonday.setDate(lastMonday.getDate() - 7);

  const groups = new Map<string, TodoItem[]>();

  for (const todo of todos) {
    const completed = new Date(todo.updated_at);
    completed.setHours(0, 0, 0, 0);

    let key: string;
    if (completed >= thisMonday) {
      key = "This Week";
    } else if (completed >= lastMonday) {
      key = "Last Week";
    } else {
      key = completed.toLocaleDateString([], { month: "long", year: "numeric" });
    }

    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(todo);
  }

  return Array.from(groups.entries()).map(([label, todos]) => ({ label, todos }));
}

/** Filter todos relevant to "today": overdue, due today, or in active date range. */
export function filterTodayTodos(todos: TodoItem[]): TodoItem[] {
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return todos.filter((todo) => {
    if (todo.due_date) {
      const due = new Date(todo.due_date);
      due.setHours(0, 0, 0, 0);
      // Overdue or due today
      if (due <= today) return true;
      // Active range: start_date <= today <= due_date
      if (todo.start_date) {
        const start = new Date(todo.start_date);
        start.setHours(0, 0, 0, 0);
        if (start <= today && today <= due) return true;
      }
    }
    return false;
  });
}

interface UseTodosReturn {
  openTodos: TodoItem[];
  doneTodos: TodoItem[];
  loading: boolean;
  error: string | null;
  completeTodo: (id: string) => Promise<void>;
  addTodo: (description: string, priority: "high" | "normal" | "low", dueDate?: string, startDate?: string, label?: string) => Promise<void>;
  deferTodo: (id: string, dueDate: string, reason?: string) => Promise<void>;
  loadMoreDone: () => Promise<void>;
  hasMoreDone: boolean;
}

const DONE_PAGE_SIZE = 20;

export function useTodos(): UseTodosReturn {
  const [openTodos, setOpenTodos] = useState<TodoItem[]>([]);
  const [doneTodos, setDoneTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMoreDone, setHasMoreDone] = useState(false);
  const [doneOffset, setDoneOffset] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function fetchTodos() {
      try {
        const [openRes, doneRes] = await Promise.all([
          api<TodoListResponse>("GET", "/v1/todos?status=open&limit=50"),
          api<TodoListResponse>("GET", `/v1/todos?status=done&limit=${DONE_PAGE_SIZE}`),
        ]);
        if (!cancelled) {
          setOpenTodos(sortOpenTodos(openRes.todos));
          setDoneTodos(doneRes.todos);
          setDoneOffset(doneRes.todos.length);
          setHasMoreDone(doneRes.todos.length >= DONE_PAGE_SIZE);
        }
      } catch {
        if (!cancelled) setError("Failed to load tasks");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchTodos();
    return () => {
      cancelled = true;
    };
  }, []);

  const completeTodo = useCallback(async (id: string) => {
    const todo = openTodos.find((t) => t.id === id);
    if (!todo) return;

    // Optimistic update
    setOpenTodos((prev) => prev.filter((t) => t.id !== id));
    setDoneTodos((prev) => [{ ...todo, status: "done" as const }, ...prev]);

    try {
      await api<TodoItem>("PATCH", `/v1/todos/${id}`, { status: "done" });
      toast("Task completed", {
        action: {
          label: "Undo",
          onClick: () => {
            // Inline undo — captures `todo` directly, avoids stale closure
            setDoneTodos((prev) => prev.filter((t) => t.id !== id));
            setOpenTodos((prev) => sortOpenTodos([...prev, { ...todo, status: "open" as const }]));
            api<TodoItem>("PATCH", `/v1/todos/${id}`, { status: "open" }).catch(() => {
              setOpenTodos((prev) => prev.filter((t) => t.id !== id));
              setDoneTodos((prev) => [{ ...todo, status: "done" as const }, ...prev]);
              toast.error("Failed to undo");
            });
          },
        },
        duration: 5000,
      });
    } catch {
      // Rollback
      setOpenTodos((prev) => sortOpenTodos([...prev, todo]));
      setDoneTodos((prev) => prev.filter((t) => t.id !== id));
      toast.error("Failed to complete task");
    }
  }, [openTodos]);

  const addTodo = useCallback(async (
    description: string,
    priority: "high" | "normal" | "low",
    dueDate?: string,
    startDate?: string,
    label?: string,
  ) => {
    try {
      const body: Record<string, unknown> = { description, priority };
      if (dueDate) body.due_date = dueDate;
      if (startDate) body.start_date = startDate;
      if (label) body.label = label;

      const created = await api<TodoItem>("POST", "/v1/todos", body);
      setOpenTodos((prev) => sortOpenTodos([...prev, created]));
      toast.success("Task added");
    } catch {
      toast.error("Failed to add task");
    }
  }, []);

  const deferTodo = useCallback(async (id: string, dueDate: string, reason?: string) => {
    const prevOpen = openTodos;
    // Optimistic: update due_date in place, re-sort
    setOpenTodos((prev) =>
      sortOpenTodos(prev.map((t) => (t.id === id ? { ...t, due_date: dueDate } : t)))
    );

    try {
      const body: Record<string, unknown> = { due_date: dueDate };
      if (reason) body.reason = reason;
      await api<TodoItem>("PATCH", `/v1/todos/${id}`, body);
      toast.success("Task deferred");
    } catch {
      setOpenTodos(prevOpen);
      toast.error("Failed to defer task");
    }
  }, [openTodos]);

  const loadMoreDone = useCallback(async () => {
    try {
      const res = await api<TodoListResponse>(
        "GET",
        `/v1/todos?status=done&limit=${DONE_PAGE_SIZE}&offset=${doneOffset}`
      );
      setDoneTodos((prev) => [...prev, ...res.todos]);
      setDoneOffset((prev) => prev + res.todos.length);
      setHasMoreDone(res.todos.length >= DONE_PAGE_SIZE);
    } catch {
      toast.error("Failed to load more tasks");
    }
  }, [doneOffset]);

  return { openTodos, doneTodos, loading, error, completeTodo, addTodo, deferTodo, loadMoreDone, hasMoreDone };
}
