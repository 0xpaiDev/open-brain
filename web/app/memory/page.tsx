"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useMemories } from "@/hooks/use-memories";
import { SmartComposer } from "@/components/memory/smart-composer";
import { MemoryBentoGrid } from "@/components/memory/bento-grid";

function MemoryContent() {
  const searchParams = useSearchParams();
  const typeFilter = searchParams.get("filter") ?? undefined;
  const searchQuery = searchParams.get("q") ?? undefined;
  const projectFilter = searchParams.get("project") ?? undefined;

  const {
    items,
    loading,
    error,
    hasMore,
    isSearchMode,
    loadMore,
    ingestMemory,
  } = useMemories({ typeFilter, searchQuery, projectFilter });

  return (
    <div className="py-8 space-y-8">
      <div>
        <h1 className="text-3xl font-headline font-bold text-primary mb-2">
          Memory Bank
        </h1>
        <p className="text-on-surface-variant text-sm">
          {isSearchMode
            ? `Search results for "${searchQuery}"`
            : typeFilter && projectFilter
              ? `Showing ${typeFilter} memories in ${projectFilter}`
              : typeFilter
                ? `Showing ${typeFilter} memories`
                : projectFilter
                  ? `Showing memories in ${projectFilter}`
                  : "Your knowledge graph, one memory at a time."}
        </p>
      </div>

      <SmartComposer onIngest={ingestMemory} />

      <MemoryBentoGrid
        items={items}
        loading={loading}
        error={error}
        hasMore={hasMore}
        isSearchMode={isSearchMode}
        onLoadMore={loadMore}
      />
    </div>
  );
}

export default function MemoryPage() {
  return (
    <Suspense
      fallback={
        <div className="py-8">
          <h1 className="text-3xl font-headline font-bold text-primary mb-2">
            Memory Bank
          </h1>
          <p className="text-on-surface-variant text-sm">Loading...</p>
        </div>
      }
    >
      <MemoryContent />
    </Suspense>
  );
}
