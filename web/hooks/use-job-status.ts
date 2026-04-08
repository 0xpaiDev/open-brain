"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { JobStatusResponse } from "@/lib/types";

interface UseJobStatusReturn {
  jobStatus: JobStatusResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useJobStatus(): UseJobStatusReturn {
  const [jobStatus, setJobStatus] = useState<JobStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchStatus() {
      try {
        const res = await api<JobStatusResponse>("GET", "/v1/jobs/status");
        if (!cancelled) setJobStatus(res);
      } catch {
        if (!cancelled) setError("Failed to load job status");
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
      const res = await api<JobStatusResponse>("GET", "/v1/jobs/status");
      setJobStatus(res);
    } catch {
      setError("Failed to load job status");
    } finally {
      setLoading(false);
    }
  }, []);

  return { jobStatus, loading, error, refresh };
}
