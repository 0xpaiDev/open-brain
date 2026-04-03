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
  undoComplete: (id: string) => Promise<void>;
  addTodo: (description: string, priority: "high" | "normal" | "low", dueDate?: string, startDate?: string) => Promise<void>;
  deferTodo: (id: string, dueDate: string, reason?: string) => Promise<void>;
}

export function useTodos(): UseTodosReturn {
  const [openTodos, setOpenTodos] = useState<TodoItem[]>([]);
  const [doneTodos, setDoneTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchTodos() {
      try {
        const [openRes, doneRes] = await Promise.all([
          api<TodoListResponse>("GET", "/v1/todos?status=open&limit=50"),
          api<TodoListResponse>("GET", "/v1/todos?status=done&limit=10"),
        ]);
        if (!cancelled) {
          setOpenTodos(sortOpenTodos(openRes.todos));
          setDoneTodos(doneRes.todos);
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

  const undoComplete = useCallback(async (id: string) => {
    const todo = doneTodos.find((t) => t.id === id);
    if (!todo) return;

    const prevOpen = openTodos;
    const prevDone = doneTodos;

    // Optimistic: move back to open
    setDoneTodos((prev) => prev.filter((t) => t.id !== id));
    setOpenTodos((prev) => sortOpenTodos([...prev, { ...todo, status: "open" as const }]));

    try {
      await api<TodoItem>("PATCH", `/v1/todos/${id}`, { status: "open" });
    } catch {
      setOpenTodos(prevOpen);
      setDoneTodos(prevDone);
      toast.error("Failed to undo");
    }
  }, [openTodos, doneTodos]);

  const completeTodo = useCallback(async (id: string) => {
    const prevOpen = openTodos;
    const prevDone = doneTodos;
    const todo = openTodos.find((t) => t.id === id);
    if (!todo) return;

    // Optimistic update
    setOpenTodos((prev) => prev.filter((t) => t.id !== id));
    setDoneTodos((prev) => [{ ...todo, status: "done" as const }, ...prev]);

    try {
      await api<TodoItem>("PATCH", `/v1/todos/${id}`, { status: "done" });
      toast("Task completed", {
        action: { label: "Undo", onClick: () => undoComplete(id) },
        duration: 5000,
      });
    } catch {
      // Rollback
      setOpenTodos(prevOpen);
      setDoneTodos(prevDone);
      toast.error("Failed to complete task");
    }
  }, [openTodos, doneTodos, undoComplete]);

  const addTodo = useCallback(async (
    description: string,
    priority: "high" | "normal" | "low",
    dueDate?: string,
    startDate?: string,
  ) => {
    try {
      const body: Record<string, unknown> = { description, priority };
      if (dueDate) body.due_date = dueDate;
      if (startDate) body.start_date = startDate;

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

  return { openTodos, doneTodos, loading, error, completeTodo, undoComplete, addTodo, deferTodo };
}
