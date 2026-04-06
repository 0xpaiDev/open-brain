"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api } from "@/lib/api";
import type {
  MemoryItemResponse,
  MemoryRecentResponse,
  MemoryIngestResponse,
  SearchResultItem,
  SearchResponse,
} from "@/lib/types";
import { toast } from "sonner";

const PAGE_SIZE = 20;

export function isSearchResult(
  item: MemoryItemResponse | SearchResultItem,
): item is SearchResultItem {
  return "combined_score" in item;
}

interface UseMemoriesParams {
  typeFilter?: string;
  searchQuery?: string;
  projectFilter?: string;
}

interface UseMemoriesReturn {
  items: (MemoryItemResponse | SearchResultItem)[];
  total: number;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  isSearchMode: boolean;
  loadMore: () => void;
  refresh: () => void;
  ingestMemory: (
    text: string,
    source?: string,
    metadata?: Record<string, unknown>,
  ) => Promise<boolean>;
}

export function useMemories({
  typeFilter,
  searchQuery,
  projectFilter,
}: UseMemoriesParams = {}): UseMemoriesReturn {
  const [items, setItems] = useState<(MemoryItemResponse | SearchResultItem)[]>(
    [],
  );
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);

  const isSearchMode = Boolean(searchQuery?.trim());

  // Track current fetch params to detect changes
  const fetchKeyRef = useRef("");

  // Main fetch effect — resets on filter/search change
  useEffect(() => {
    const key = `${typeFilter ?? ""}|${searchQuery ?? ""}|${projectFilter ?? ""}`;
    const isNewKey = key !== fetchKeyRef.current;
    fetchKeyRef.current = key;

    if (isNewKey) {
      setOffset(0);
      setItems([]);
    }

    let cancelled = false;

    async function fetchData() {
      try {
        setLoading(true);
        setError(null);

        if (searchQuery?.trim()) {
          // Search mode
          let searchPath = `/v1/search?q=${encodeURIComponent(searchQuery.trim())}&limit=${PAGE_SIZE}`;
          if (typeFilter) searchPath += `&type_filter=${typeFilter}`;
          if (projectFilter) searchPath += `&project_filter=${encodeURIComponent(projectFilter)}`;

          const res = await api<SearchResponse>("GET", searchPath);
          if (!cancelled) {
            setItems(res.results);
            setTotal(res.results.length);
          }
        } else {
          // Browse mode
          let browsePath = `/v1/memory/recent?limit=${PAGE_SIZE}&offset=0`;
          if (typeFilter) browsePath += `&type_filter=${typeFilter}`;
          if (projectFilter) browsePath += `&project_filter=${encodeURIComponent(projectFilter)}`;

          const res = await api<MemoryRecentResponse>("GET", browsePath);
          if (!cancelled) {
            setItems(res.items);
            setTotal(res.total);
          }
        }
      } catch {
        if (!cancelled) setError("Failed to load memories");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchData();
    return () => {
      cancelled = true;
    };
  }, [typeFilter, searchQuery, projectFilter]);

  const loadMore = useCallback(async () => {
    if (isSearchMode || loadingMore) return;

    const nextOffset = offset + PAGE_SIZE;
    setLoadingMore(true);

    try {
      let path = `/v1/memory/recent?limit=${PAGE_SIZE}&offset=${nextOffset}`;
      if (typeFilter) path += `&type_filter=${typeFilter}`;
      if (projectFilter) path += `&project_filter=${encodeURIComponent(projectFilter)}`;

      const res = await api<MemoryRecentResponse>("GET", path);
      setItems((prev) => [...prev, ...res.items]);
      setOffset(nextOffset);
      setTotal(res.total);
    } catch {
      toast.error("Failed to load more memories");
    } finally {
      setLoadingMore(false);
    }
  }, [isSearchMode, loadingMore, offset, typeFilter, projectFilter]);

  const refresh = useCallback(() => {
    setOffset(0);
    setItems([]);
    // Trigger re-fetch by updating a dependency — we re-run the effect
    // by toggling a state that the effect watches
    fetchKeyRef.current = ""; // Force the effect to treat next run as new
    // We need to trigger the effect — simplest: set items to [] and loading to true
    setLoading(true);

    let cancelled = false;

    async function refetch() {
      try {
        if (isSearchMode && searchQuery?.trim()) {
          let searchPath = `/v1/search?q=${encodeURIComponent(searchQuery.trim())}&limit=${PAGE_SIZE}`;
          if (typeFilter) searchPath += `&type_filter=${typeFilter}`;
          if (projectFilter) searchPath += `&project_filter=${encodeURIComponent(projectFilter)}`;
          const res = await api<SearchResponse>("GET", searchPath);
          if (!cancelled) {
            setItems(res.results);
            setTotal(res.results.length);
          }
        } else {
          let browsePath = `/v1/memory/recent?limit=${PAGE_SIZE}&offset=0`;
          if (typeFilter) browsePath += `&type_filter=${typeFilter}`;
          if (projectFilter) browsePath += `&project_filter=${encodeURIComponent(projectFilter)}`;
          const res = await api<MemoryRecentResponse>("GET", browsePath);
          if (!cancelled) {
            setItems(res.items);
            setTotal(res.total);
          }
        }
      } catch {
        if (!cancelled) setError("Failed to refresh memories");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    refetch();
    return () => {
      cancelled = true;
    };
  }, [isSearchMode, searchQuery, typeFilter, projectFilter]);

  const ingestMemory = useCallback(
    async (
      text: string,
      source?: string,
      metadata?: Record<string, unknown>,
    ): Promise<boolean> => {
      try {
        const body: Record<string, unknown> = { text };
        if (source) body.source = source;
        if (metadata) body.metadata = metadata;

        const res = await api<MemoryIngestResponse>("POST", "/v1/memory", body);

        if (res.status === "duplicate") {
          toast.info("This memory already exists — skipped.");
        } else {
          toast.success("Memory committed — queued for processing.");
        }

        refresh();
        return true;
      } catch {
        toast.error("Failed to commit memory");
        return false;
      }
    },
    [refresh],
  );

  const hasMore = !isSearchMode && items.length < total;

  return {
    items,
    total,
    loading: loading || loadingMore,
    error,
    hasMore,
    isSearchMode,
    loadMore,
    refresh,
    ingestMemory,
  };
}
