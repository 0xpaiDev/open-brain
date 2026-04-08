"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { DeadLetterItem, DeadLetterListResponse } from "@/lib/types";

const PAGE_SIZE = 50;

interface UseDeadLettersReturn {
  items: DeadLetterItem[];
  total: number;
  loading: boolean;
  error: string | null;
  loadMore: () => Promise<void>;
  hasMore: boolean;
  refresh: () => Promise<void>;
}

export function useDeadLetters(resolved: boolean): UseDeadLettersReturn {
  const [items, setItems] = useState<DeadLetterItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);

  const buildUrl = useCallback(
    (off: number) => {
      const params = new URLSearchParams();
      params.set("limit", String(PAGE_SIZE));
      params.set("offset", String(off));
      params.set("resolved", String(resolved));
      return `/v1/dead-letters?${params.toString()}`;
    },
    [resolved],
  );

  useEffect(() => {
    let cancelled = false;

    async function fetchDeadLetters() {
      setLoading(true);
      setError(null);
      try {
        const res = await api<DeadLetterListResponse>("GET", buildUrl(0));
        if (!cancelled) {
          setItems(res.items);
          setTotal(res.total);
          setOffset(res.items.length);
        }
      } catch {
        if (!cancelled) setError("Failed to load dead letters");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchDeadLetters();
    return () => {
      cancelled = true;
    };
  }, [buildUrl]);

  const hasMore = offset < total;

  const loadMore = useCallback(async () => {
    if (!hasMore) return;
    try {
      const res = await api<DeadLetterListResponse>("GET", buildUrl(offset));
      setItems((prev) => [...prev, ...res.items]);
      setTotal(res.total);
      setOffset((prev) => prev + res.items.length);
    } catch {
      setError("Failed to load more dead letters");
    }
  }, [hasMore, buildUrl, offset]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api<DeadLetterListResponse>("GET", buildUrl(0));
      setItems(res.items);
      setTotal(res.total);
      setOffset(res.items.length);
    } catch {
      setError("Failed to load dead letters");
    } finally {
      setLoading(false);
    }
  }, [buildUrl]);

  return { items, total, loading, error, loadMore, hasMore, refresh };
}
