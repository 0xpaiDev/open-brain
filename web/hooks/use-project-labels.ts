"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ProjectLabel } from "@/lib/types";
import { toast } from "sonner";

interface UseProjectLabelsReturn {
  labels: ProjectLabel[];
  loading: boolean;
  createLabel: (name: string, color?: string) => Promise<void>;
  deleteLabel: (name: string) => Promise<void>;
  renameLabel: (oldName: string, newName: string, color?: string) => Promise<boolean>;
}

export function useProjectLabels(): UseProjectLabelsReturn {
  const [labels, setLabels] = useState<ProjectLabel[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchLabels() {
      try {
        const data = await api<ProjectLabel[]>("GET", "/v1/project-labels");
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
    const optimistic: ProjectLabel = {
      id: crypto.randomUUID(),
      name,
      color: color || "#6750A4",
      created_at: new Date().toISOString(),
    };
    setLabels((prev) => [...prev, optimistic].sort((a, b) => a.name.localeCompare(b.name)));

    try {
      const created = await api<ProjectLabel>("POST", "/v1/project-labels", { name, color });
      setLabels((prev) => prev.map((l) => (l.id === optimistic.id ? created : l)));
    } catch {
      setLabels((prev) => prev.filter((l) => l.id !== optimistic.id));
      toast.error("Failed to create project label");
    }
  }, []);

  const deleteLabel = useCallback(async (name: string) => {
    const removed = labels.find((l) => l.name === name);
    setLabels((prev) => prev.filter((l) => l.name !== name));

    try {
      await api("DELETE", `/v1/project-labels/${encodeURIComponent(name)}`);
    } catch {
      if (removed) setLabels((prev) => [...prev, removed].sort((a, b) => a.name.localeCompare(b.name)));
      toast.error("Failed to delete project label");
    }
  }, [labels]);

  const renameLabel = useCallback(
    async (oldName: string, newName: string, color?: string): Promise<boolean> => {
      const trimmed = newName.trim();
      if (!trimmed) return false;

      const original = labels;
      // Optimistic: replace name (and color if provided) in place, re-sort.
      setLabels((prev) =>
        [...prev]
          .map((l) =>
            l.name === oldName
              ? { ...l, name: trimmed, color: color ?? l.color }
              : l,
          )
          .sort((a, b) => a.name.localeCompare(b.name)),
      );

      try {
        const body: Record<string, string> = {};
        if (trimmed !== oldName) body.new_name = trimmed;
        if (color) body.color = color;
        const updated = await api<ProjectLabel>(
          "PATCH",
          `/v1/project-labels/${encodeURIComponent(oldName)}`,
          body,
        );
        setLabels((prev) =>
          prev.map((l) => (l.name === trimmed ? updated : l)).sort((a, b) =>
            a.name.localeCompare(b.name),
          ),
        );
        return true;
      } catch (err) {
        setLabels(original);
        const message =
          err instanceof Error && err.message.includes("409")
            ? `A project named "${trimmed}" already exists`
            : "Failed to rename project";
        toast.error(message);
        return false;
      }
    },
    [labels],
  );

  return { labels, loading, createLabel, deleteLabel, renameLabel };
}
