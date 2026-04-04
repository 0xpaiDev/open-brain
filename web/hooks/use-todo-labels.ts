"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TodoLabel } from "@/lib/types";
import { toast } from "sonner";

interface UseTodoLabelsReturn {
  labels: TodoLabel[];
  loading: boolean;
  createLabel: (name: string, color?: string) => Promise<void>;
  deleteLabel: (name: string) => Promise<void>;
}

export function useTodoLabels(): UseTodoLabelsReturn {
  const [labels, setLabels] = useState<TodoLabel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchLabels() {
      try {
        const data = await api<TodoLabel[]>("GET", "/v1/todo-labels");
        if (!cancelled) setLabels(data);
      } catch {
        // Labels are non-critical — fail silently
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchLabels();
    return () => {
      cancelled = true;
    };
  }, []);

  const createLabel = useCallback(async (name: string, color?: string) => {
    const optimistic: TodoLabel = {
      id: crypto.randomUUID(),
      name,
      color: color || "#6750A4",
      created_at: new Date().toISOString(),
    };
    setLabels((prev) => [...prev, optimistic].sort((a, b) => a.name.localeCompare(b.name)));

    try {
      const created = await api<TodoLabel>("POST", "/v1/todo-labels", { name, color });
      setLabels((prev) => prev.map((l) => (l.id === optimistic.id ? created : l)));
    } catch {
      setLabels((prev) => prev.filter((l) => l.id !== optimistic.id));
      toast.error("Failed to create label");
    }
  }, []);

  const deleteLabel = useCallback(async (name: string) => {
    const removed = labels.find((l) => l.name === name);
    setLabels((prev) => prev.filter((l) => l.name !== name));

    try {
      await api("DELETE", `/v1/todo-labels/${encodeURIComponent(name)}`);
    } catch {
      if (removed) setLabels((prev) => [...prev, removed].sort((a, b) => a.name.localeCompare(b.name)));
      toast.error("Failed to delete label");
    }
  }, [labels]);

  return { labels, loading, createLabel, deleteLabel };
}
