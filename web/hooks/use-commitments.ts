"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type {
  CommitmentResponse,
  CommitmentListResponse,
  CommitmentCreate,
  CommitmentEntry,
  CommitmentExerciseLog,
  ExerciseProgression,
  CommitmentImportResult,
} from "@/lib/types";
import { toast } from "sonner";

export function useCommitments(statusFilter: "active" | "all" = "active") {
  const [commitments, setCommitments] = useState<CommitmentResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api<CommitmentListResponse>(
        "GET",
        `/v1/commitments?status=${statusFilter}`,
      );
      setCommitments(data.commitments);
    } catch {
      // Silently fail on initial load — API may be down
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logCount = useCallback(
    async (commitmentId: string, count: number) => {
      try {
        const entry = await api<CommitmentEntry>(
          "POST",
          `/v1/commitments/${commitmentId}/log`,
          { count },
        );

        // Optimistic update: patch the entry into local state
        setCommitments((prev) =>
          prev.map((c) => {
            if (c.id !== commitmentId) return c;
            return {
              ...c,
              current_streak:
                entry.status === "hit" ? c.current_streak + 1 : c.current_streak,
              entries: c.entries.map((e) =>
                e.entry_date === entry.entry_date ? entry : e,
              ),
            };
          }),
        );

        if (entry.status === "hit") {
          toast.success("Target hit!");
        }

        return entry;
      } catch (err) {
        toast.error("Failed to log");
        throw err;
      }
    },
    [],
  );

  const abandonCommitment = useCallback(
    async (commitmentId: string) => {
      try {
        await api("PATCH", `/v1/commitments/${commitmentId}`, {
          status: "abandoned",
        });
        setCommitments((prev) => prev.filter((c) => c.id !== commitmentId));
        toast.success("Commitment abandoned");
      } catch {
        toast.error("Failed to abandon commitment");
      }
    },
    [],
  );

  const createCommitment = useCallback(
    async (data: CommitmentCreate) => {
      try {
        const created = await api<CommitmentResponse>(
          "POST",
          "/v1/commitments",
          data,
        );
        setCommitments((prev) => [created, ...prev]);
        toast.success("Commitment created!");
        return created;
      } catch {
        toast.error("Failed to create commitment");
        return null;
      }
    },
    [],
  );

  const logExercise = useCallback(
    async (
      commitmentId: string,
      exerciseId: string,
      data: { reps?: number; sets?: number; weight_kg?: number; duration_minutes?: number; notes?: string },
    ) => {
      try {
        const log = await api<CommitmentExerciseLog>(
          "POST",
          `/v1/commitments/${commitmentId}/exercises/${exerciseId}/log`,
          data,
        );
        await refresh();
        return log;
      } catch (err) {
        toast.error("Failed to log exercise");
        throw err;
      }
    },
    [refresh],
  );

  const deleteExerciseLog = useCallback(
    async (commitmentId: string, exerciseId: string, logId: string) => {
      try {
        await api("DELETE", `/v1/commitments/${commitmentId}/exercises/${exerciseId}/logs/${logId}`);
        await refresh();
      } catch {
        toast.error("Failed to delete log");
      }
    },
    [refresh],
  );

  const getProgression = useCallback(
    async (commitmentId: string): Promise<ExerciseProgression[]> => {
      return api<ExerciseProgression[]>("GET", `/v1/commitments/${commitmentId}/progression`);
    },
    [],
  );

  const importPlan = useCallback(
    async (payload: unknown, dryRun: boolean): Promise<CommitmentImportResult> => {
      const result = await api<CommitmentImportResult>(
        "POST",
        `/v1/commitments/import?dry_run=${dryRun}`,
        payload,
      );
      if (!dryRun && !result.already_exists) {
        await refresh();
      }
      return result;
    },
    [refresh],
  );

  return { commitments, loading, refresh, logCount, abandonCommitment, createCommitment, logExercise, deleteExerciseLog, getProgression, importPlan };
}
