"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type {
  CommitmentResponse,
  CommitmentListResponse,
  CommitmentEntry,
} from "@/lib/types";
import { toast } from "sonner";

export function useCommitments() {
  const [commitments, setCommitments] = useState<CommitmentResponse[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api<CommitmentListResponse>(
        "GET",
        "/v1/commitments?status=active",
      );
      setCommitments(data.commitments);
    } catch {
      // Silently fail on initial load — API may be down
    } finally {
      setLoading(false);
    }
  }, []);

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

  return { commitments, loading, refresh, logCount, abandonCommitment };
}
