"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TodoItem } from "@/lib/types";
import { toast } from "sonner";

interface UseOverdueReturn {
  overdueTodos: TodoItem[];
  loading: boolean;
  deferOverdue: (id: string, dueDate: string, reason: string) => Promise<void>;
  allHandled: boolean;
}

export function useOverdue(): UseOverdueReturn {
  const [overdueTodos, setOverdueTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchOverdue = useCallback(async () => {
    try {
      const todos = await api<TodoItem[]>("GET", "/v1/todos/overdue-undeferred");
      setOverdueTodos(todos);
    } catch {
      // Silently fail — modal just won't show
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverdue();

    function handleVisibility() {
      if (document.visibilityState === "visible") {
        fetchOverdue();
      }
    }

    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [fetchOverdue]);

  const deferOverdue = useCallback(async (id: string, dueDate: string, reason: string) => {
    try {
      await api<TodoItem>("PATCH", `/v1/todos/${id}`, { due_date: dueDate, reason });
      setOverdueTodos((prev) => prev.filter((t) => t.id !== id));
    } catch {
      toast.error("Failed to defer task");
    }
  }, []);

  const allHandled = !loading && overdueTodos.length === 0;

  return { overdueTodos, loading, deferOverdue, allHandled };
}
