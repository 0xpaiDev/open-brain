"use client";

import type { MemoryItemResponse, SearchResultItem } from "@/lib/types";
import { MemoryCard } from "./memory-card";
import { Button } from "@/components/ui/button";

interface MemoryBentoGridProps {
  items: (MemoryItemResponse | SearchResultItem)[];
  loading: boolean;
  error?: string | null;
  hasMore: boolean;
  isSearchMode: boolean;
  onLoadMore: () => void;
}

function SkeletonCard() {
  return (
    <div className="bg-surface-container-high rounded-2xl p-5 animate-pulse flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 rounded bg-outline-variant/20" />
        <div className="w-16 h-4 rounded bg-outline-variant/20" />
      </div>
      <div className="space-y-2">
        <div className="h-3 rounded bg-outline-variant/15 w-full" />
        <div className="h-3 rounded bg-outline-variant/15 w-4/5" />
        <div className="h-3 rounded bg-outline-variant/15 w-3/5" />
      </div>
      <div className="h-3 rounded bg-outline-variant/10 w-16 mt-auto" />
    </div>
  );
}

export function MemoryBentoGrid({
  items,
  loading,
  error,
  hasMore,
  isSearchMode,
  onLoadMore,
}: MemoryBentoGridProps) {
  // Loading skeleton
  if (loading && items.length === 0) {
    return (
      <div className="bento-grid" role="status" aria-busy="true">
        {Array.from({ length: 6 }).map((_, i) => (
          <SkeletonCard key={i} />
        ))}
      </div>
    );
  }

  // Error state
  if (error && items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center" role="alert">
        <span className="material-symbols-outlined text-5xl text-error mb-4">
          cloud_off
        </span>
        <p className="text-on-surface-variant font-body text-sm">{error}</p>
      </div>
    );
  }

  // Empty state
  if (!loading && items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <span className="material-symbols-outlined text-5xl text-outline-variant/40 mb-4">
          {isSearchMode ? "search_off" : "database"}
        </span>
        <p className="text-on-surface-variant font-body text-sm">
          {isSearchMode
            ? "No results found. Try a different search."
            : "Your brain is empty \u2014 commit your first memory above."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="bento-grid">
        {items.map((item) => (
          <MemoryCard key={item.id} item={item} />
        ))}
      </div>

      {hasMore && !isSearchMode && (
        <div className="flex justify-center mt-8">
          <Button
            variant="outline"
            onClick={onLoadMore}
            disabled={loading}
            className="px-8"
          >
            {loading ? "Loading..." : "Load more memories"}
          </Button>
        </div>
      )}
    </div>
  );
}
