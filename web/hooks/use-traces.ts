"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TraceListItem, TraceListResponse, KpiResponse } from "@/lib/types";

const PAGE_SIZE = 50;

export interface TraceFilters {
  trigger_type?: string | null;
  status?: string | null;
  trigger_name?: string | null;
  date_from?: string | null;
  date_to?: string | null;
  min_cost?: number | null;
  max_cost?: number | null;
}

interface UseTracesReturn {
  items: TraceListItem[];
  total: number;
  page: number;
  loading: boolean;
  error: string | null;
  loadMore: () => Promise<void>;
  hasMore: boolean;
  refresh: () => Promise<void>;
}

export function useTraces(filters: TraceFilters): UseTracesReturn {
  const [items, setItems] = useState<TraceListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const buildUrl = useCallback(
    (p: number) => {
      const params = new URLSearchParams();
      params.set("page", String(p));
      params.set("page_size", String(PAGE_SIZE));
      if (filters.trigger_type != null) params.set("trigger_type", filters.trigger_type);
      if (filters.status != null) params.set("status", filters.status);
      if (filters.trigger_name != null) params.set("trigger_name", filters.trigger_name);
      if (filters.date_from != null) params.set("date_from", filters.date_from);
      if (filters.date_to != null) params.set("date_to", filters.date_to);
      if (filters.min_cost != null) params.set("min_cost", String(filters.min_cost));
      if (filters.max_cost != null) params.set("max_cost", String(filters.max_cost));
      return `/v1/traces?${params.toString()}`;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      filters.trigger_type,
      filters.status,
      filters.trigger_name,
      filters.date_from,
      filters.date_to,
      filters.min_cost,
      filters.max_cost,
    ],
  );

  // Initial fetch + re-fetch when filters change
  useEffect(() => {
    let cancelled = false;

    async function fetchTraces() {
      setLoading(true);
      setError(null);
      try {
        const res = await api<TraceListResponse>("GET", buildUrl(1));
        if (!cancelled) {
          setItems(res.items);
          setTotal(res.total);
          setPage(1);
        }
      } catch {
        if (!cancelled) setError("Failed to load traces");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchTraces();
    return () => {
      cancelled = true;
    };
  }, [buildUrl]);

  const hasMore = items.length < total;

  const loadMore = useCallback(async () => {
    if (!hasMore || loading) return;
    const nextPage = page + 1;
    try {
      const res = await api<TraceListResponse>("GET", buildUrl(nextPage));
      setItems((prev) => [...prev, ...res.items]);
      setTotal(res.total);
      setPage(nextPage);
    } catch {
      setError("Failed to load more traces");
    }
  }, [hasMore, loading, buildUrl, page]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api<TraceListResponse>("GET", buildUrl(1));
      setItems(res.items);
      setTotal(res.total);
      setPage(1);
    } catch {
      setError("Failed to load traces");
    } finally {
      setLoading(false);
    }
  }, [buildUrl]);

  return { items, total, page, loading, error, loadMore, hasMore, refresh };
}

interface UseKpisReturn {
  kpis: KpiResponse | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useKpis(filters: TraceFilters = {}): UseKpisReturn {
  const [kpis, setKpis] = useState<KpiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchKpis = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filters.date_from != null) params.set("date_from", filters.date_from);
      if (filters.date_to != null) params.set("date_to", filters.date_to);
      const qs = params.toString();
      const url = qs ? `/v1/traces/kpis?${qs}` : "/v1/traces/kpis";
      const res = await api<KpiResponse>("GET", url);
      setKpis(res);
    } catch {
      setError("Failed to load KPIs");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.date_from, filters.date_to]);

  useEffect(() => {
    fetchKpis();
  }, [fetchKpis]);

  return { kpis, loading, error, refresh: fetchKpis };
}
