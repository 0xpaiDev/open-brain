"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { QueueStatusResponse } from "@/lib/types";

interface UseQueueStatusReturn {
  status: QueueStatusResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useQueueStatus(): UseQueueStatusReturn {
  const [status, setStatus] = useState<QueueStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchStatus() {
      try {
        const res = await api<QueueStatusResponse>("GET", "/v1/queue/status");
        if (!cancelled) setStatus(res);
      } catch {
        if (!cancelled) setError("Failed to load pipeline status");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchStatus();
    return () => {
      cancelled = true;
    };
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api<QueueStatusResponse>("GET", "/v1/queue/status");
      setStatus(res);
    } catch {
      setError("Failed to load pipeline status");
    } finally {
      setLoading(false);
    }
  }, []);

  return { status, loading, error, refresh };
}
