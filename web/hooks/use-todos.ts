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

interface UseTodosReturn {
  openTodos: TodoItem[];
  doneTodos: TodoItem[];
  loading: boolean;
  error: string | null;
  completeTodo: (id: string) => Promise<void>;
  addTodo: (description: string, priority: "high" | "normal" | "low", dueDate?: string) => Promise<void>;
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
    } catch {
      // Rollback
      setOpenTodos(prevOpen);
      setDoneTodos(prevDone);
      toast.error("Failed to complete task");
    }
  }, [openTodos, doneTodos]);

  const addTodo = useCallback(async (
    description: string,
    priority: "high" | "normal" | "low",
    dueDate?: string,
  ) => {
    try {
      const body: Record<string, unknown> = { description, priority };
      if (dueDate) body.due_date = dueDate;

      const created = await api<TodoItem>("POST", "/v1/todos", body);
      setOpenTodos((prev) => sortOpenTodos([...prev, created]));
      toast.success("Task added");
    } catch {
      toast.error("Failed to add task");
    }
  }, []);

  return { openTodos, doneTodos, loading, error, completeTodo, addTodo };
}
