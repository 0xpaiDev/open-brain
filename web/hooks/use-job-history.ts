"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { JobRunItem, JobHistoryResponse } from "@/lib/types";

const PAGE_SIZE = 50;

interface UseJobHistoryReturn {
  items: JobRunItem[];
  total: number;
  loading: boolean;
  error: string | null;
  loadMore: () => Promise<void>;
  hasMore: boolean;
  refresh: () => Promise<void>;
}

export function useJobHistory(
  jobName: string | null,
  status: string | null,
): UseJobHistoryReturn {
  const [items, setItems] = useState<JobRunItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const buildUrl = useCallback(
    (off: number) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(off));
      if (jobName) params.set("job_name", jobName);
      if (status) params.set("status", status);
      return `/v1/jobs/history?${params.toString()}`;
    },
    [jobName, status],
  );

  // Initial fetch + re-fetch when filters change
  useEffect(() => {
    let cancelled = false;

    async function fetchHistory() {
      setLoading(true);
      setError(null);
      try {
        const res = await api<JobHistoryResponse>("GET", buildUrl(0));
        if (!cancelled) {
          setItems(res.items);
          setTotal(res.total);
          setOffset(res.items.length);
        }
      } catch {
        if (!cancelled) setError("Failed to load job history");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchHistory();
    return () => {
      cancelled = true;
    };
  }, [buildUrl]);

  const hasMore = offset < total;

  const loadMore = useCallback(async () => {
    if (!hasMore) return;
    try {
      const res = await api<JobHistoryResponse>("GET", buildUrl(offset));
      setItems((prev) => [...prev, ...res.items]);
      setTotal(res.total);
      setOffset((prev) => prev + res.items.length);
    } catch {
      setError("Failed to load more job runs");
    }
  }, [hasMore, buildUrl, offset]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api<JobHistoryResponse>("GET", buildUrl(0));
      setItems(res.items);
      setTotal(res.total);
      setOffset(res.items.length);
    } catch {
      setError("Failed to load job history");
    } finally {
      setLoading(false);
    }
  }, [buildUrl]);

  return { items, total, loading, error, loadMore, hasMore, refresh };
}
