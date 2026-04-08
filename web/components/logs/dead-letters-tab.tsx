"use client";

import { useState } from "react";
import type { DeadLetterItem } from "@/lib/types";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

interface DeadLettersTabProps {
  items: DeadLetterItem[];
  total: number;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  resolved: boolean;
  setResolved: (v: boolean) => void;
  onRetried?: () => void;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function DeadLetterRow({
  item,
  onRetried,
}: {
  item: DeadLetterItem;
  onRetried?: () => void;
}) {
  const hasOutput = !!item.last_output;
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  async function handleRetry(e: React.MouseEvent) {
    e.stopPropagation();
    setRetrying(true);
    setRetryError(null);
    try {
      await api("POST", `/v1/dead-letters/${item.id}/retry`);
      onRetried?.();
    } catch (err) {
      setRetryError(err instanceof Error ? err.message : "Retry failed");
    } finally {
      setRetrying(false);
    }
  }

  const row = (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors">
      <span className="material-symbols-outlined text-base text-error">
        {item.resolved_at ? "check_circle" : "report"}
      </span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-on-surface truncate">{item.error_reason}</p>
        <p className="text-xs text-on-surface-variant mt-0.5">
          {formatTime(item.created_at)} &middot; {item.attempt_count} attempt
          {item.attempt_count === 1 ? "" : "s"} &middot; {item.retry_count}{" "}
          retr{item.retry_count === 1 ? "y" : "ies"}
          {retryError && (
            <span className="text-error ml-2">{retryError}</span>
          )}
        </p>
      </div>
      {!item.resolved_at && (
        <Button
          variant="outline"
          size="sm"
          className="shrink-0 text-xs h-7 px-2"
          onClick={handleRetry}
          disabled={retrying}
        >
          <span className="material-symbols-outlined text-sm mr-1">
            replay
          </span>
          {retrying ? "Retrying..." : "Retry"}
        </Button>
      )}
      {hasOutput && (
        <span className="material-symbols-outlined text-base text-on-surface-variant">
          expand_more
        </span>
      )}
    </div>
  );

  if (!hasOutput) return row;

  return (
    <Collapsible>
      <CollapsibleTrigger className="w-full text-left">{row}</CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mx-3 mb-2 p-3 rounded-lg bg-surface-container-high border border-outline-variant/10">
          <p className="text-[10px] font-label text-on-surface-variant uppercase tracking-wider mb-1">
            Last Output
          </p>
          <pre className="text-xs text-on-surface whitespace-pre-wrap break-words font-mono max-h-48 overflow-y-auto">
            {item.last_output}
          </pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function DeadLettersTab({
  items,
  total,
  loading,
  error,
  hasMore,
  loadMore,
  resolved,
  setResolved,
  onRetried,
}: DeadLettersTabProps) {
  const [loadingMore, setLoadingMore] = useState(false);

  if (loading) {
    return (
      <div className="space-y-2" role="status" aria-busy="true">
        {[1, 2, 3].map((n) => (
          <div key={n} className="flex items-center gap-3 px-3 py-2.5">
            <div className="w-5 h-5 rounded-full bg-surface-container-high animate-pulse" />
            <div className="flex-1 space-y-1.5">
              <div className="h-4 w-48 bg-surface-container-high rounded-lg animate-pulse" />
              <div className="h-3 w-32 bg-surface-container-high rounded-lg animate-pulse" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div
        className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center text-center"
        role="alert"
      >
        <span className="material-symbols-outlined text-error text-2xl mb-2">
          error
        </span>
        <p className="text-sm text-error">{error}</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Filter toggle */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => setResolved(false)}
          className={`rounded-full px-3 py-1 text-xs font-label transition-colors ${
            !resolved
              ? "bg-error/10 text-error"
              : "bg-surface-container-high text-on-surface-variant hover:text-on-surface"
          }`}
        >
          Unresolved
        </button>
        <button
          type="button"
          onClick={() => setResolved(true)}
          className={`rounded-full px-3 py-1 text-xs font-label transition-colors ${
            resolved
              ? "bg-primary/10 text-primary"
              : "bg-surface-container-high text-on-surface-variant hover:text-on-surface"
          }`}
        >
          Resolved
        </button>

        <span className="text-xs text-on-surface-variant ml-auto">
          {total} item{total === 1 ? "" : "s"}
        </span>
      </div>

      {/* List */}
      {items.length === 0 ? (
        <div className="py-8 text-center">
          <span className="material-symbols-outlined text-on-surface-variant text-3xl mb-2 block">
            {resolved ? "inbox" : "check_circle"}
          </span>
          <p className="text-on-surface-variant text-sm">
            {resolved
              ? "No resolved dead letters"
              : "No dead letters"}
          </p>
          {!resolved && (
            <p className="text-on-surface-variant/60 text-xs mt-1">
              All pipeline items processed successfully
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-0.5">
          {items.map((item) => (
            <DeadLetterRow key={item.id} item={item} onRetried={onRetried} />
          ))}
        </div>
      )}

      {/* Load more */}
      {hasMore && (
        <div className="flex justify-center pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={async () => {
              setLoadingMore(true);
              await loadMore();
              setLoadingMore(false);
            }}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading..." : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
