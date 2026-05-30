"use client";

import { useState, useEffect, useRef } from "react";
import type { TraceListItem } from "@/lib/types";
import type { TraceFilters } from "@/hooks/use-traces";
import { Button } from "@/components/ui/button";

interface TraceListProps {
  items: TraceListItem[];
  total: number;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  filters: TraceFilters;
  onFiltersChange: (f: TraceFilters) => void;
  onTraceClick: (id: string) => void;
  selectedTraceId: string | null;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    success: "bg-primary/10 text-primary",
    failed: "bg-error/10 text-error",
    running: "bg-tertiary/10 text-tertiary",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-label ${styles[status] ?? "bg-surface-container-high text-on-surface-variant"}`}
    >
      {status}
    </span>
  );
}

function TriggerTypeBadge({ type }: { type: string }) {
  const styles: Record<string, string> = {
    cron: "bg-secondary/10 text-secondary-foreground",
    chat: "bg-tertiary/10 text-tertiary",
    http: "bg-outline-variant/20 text-on-surface-variant",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${styles[type] ?? "bg-surface-container-high text-on-surface-variant"}`}
    >
      {type}
    </span>
  );
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDurationMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function formatCost(costStr: string | null): string {
  if (!costStr) return "—";
  const n = parseFloat(costStr);
  if (n === 0) return "$0";
  if (n < 0.001) return `$${n.toFixed(6)}`;
  return `$${n.toFixed(4)}`;
}

export function TraceList({
  items,
  total,
  loading,
  error,
  hasMore,
  loadMore,
  filters,
  onFiltersChange,
  onTraceClick,
  selectedTraceId,
}: TraceListProps) {
  const [loadingMore, setLoadingMore] = useState(false);
  const [triggerNameInput, setTriggerNameInput] = useState(
    filters.trigger_name ?? "",
  );
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onFiltersChangeRef = useRef(onFiltersChange);
  useEffect(() => { onFiltersChangeRef.current = onFiltersChange; });

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const val = triggerNameInput.trim() || null;
      if (val !== (filters.trigger_name ?? null)) {
        onFiltersChangeRef.current({ ...filters, trigger_name: val });
      }
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [triggerNameInput, filters]);

  if (error) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center text-center">
        <span className="material-symbols-outlined text-error text-2xl mb-2">
          error
        </span>
        <p className="text-sm text-error">{error}</p>
      </div>
    );
  }

  const hasFilters =
    filters.trigger_type || filters.status || filters.trigger_name ||
    filters.date_from || filters.date_to;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={filters.trigger_type ?? ""}
          onChange={(e) =>
            onFiltersChange({
              ...filters,
              trigger_type: e.target.value || null,
            })
          }
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="Filter by trigger type"
        >
          <option value="">All types</option>
          <option value="cron">cron</option>
          <option value="chat">chat</option>
          <option value="http">http</option>
        </select>

        <select
          value={filters.status ?? ""}
          onChange={(e) =>
            onFiltersChange({ ...filters, status: e.target.value || null })
          }
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="running">running</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
        </select>

        <input
          type="text"
          value={triggerNameInput}
          onChange={(e) => setTriggerNameInput(e.target.value)}
          placeholder="Filter by name…"
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface placeholder:text-on-surface-variant/50 min-w-0 flex-1 md:flex-none md:w-40"
          aria-label="Filter by trigger name"
        />

        <input
          type="date"
          value={filters.date_from ?? ""}
          onChange={(e) => onFiltersChange({ ...filters, date_from: e.target.value || null })}
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="From date"
        />
        <input
          type="date"
          value={filters.date_to ?? ""}
          onChange={(e) => onFiltersChange({ ...filters, date_to: e.target.value || null })}
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="To date"
        />

        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setTriggerNameInput("");
              onFiltersChange({
                ...filters,
                trigger_type: null,
                status: null,
                trigger_name: null,
                date_from: null,
                date_to: null,
              });
            }}
            className="text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Clear
          </button>
        )}

        <span className="text-xs text-on-surface-variant ml-auto">
          {total} trace{total === 1 ? "" : "s"}
        </span>
      </div>

      {loading ? (
        <div className="space-y-0.5" role="status" aria-busy="true">
          {[1, 2, 3, 4, 5].map((n) => (
            <div key={n} className="flex items-center gap-3 px-3 py-2.5">
              <div className="flex-1 space-y-1.5">
                <div className="h-4 w-48 bg-surface-container-high rounded-lg animate-pulse" />
                <div className="h-3 w-32 bg-surface-container-high rounded-lg animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="py-8 text-center">
          <span className="material-symbols-outlined text-on-surface-variant text-3xl mb-2 block">
            manage_search
          </span>
          <p className="text-on-surface-variant text-sm">
            {hasFilters ? "No traces match the selected filters" : "No traces found"}
          </p>
        </div>
      ) : (
        <div className="space-y-0.5">
          {items.map((trace) => (
            <button
              key={trace.id}
              type="button"
              onClick={() => onTraceClick(trace.id)}
              className={`w-full text-left flex items-start gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors ${
                selectedTraceId === trace.id
                  ? "bg-primary/5 ring-1 ring-primary/20"
                  : ""
              }`}
            >
              <div className="flex-1 min-w-0 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <TriggerTypeBadge type={trace.trigger_type} />
                  <span className="text-sm font-medium text-on-surface truncate">
                    {trace.trigger_name}
                  </span>
                  <StatusBadge status={trace.status} />
                </div>
                <div className="flex items-center gap-3 text-xs text-on-surface-variant flex-wrap">
                  <span>{formatTime(trace.started_at)}</span>
                  <span>{formatDurationMs(trace.duration_ms)}</span>
                  <span>{formatCost(trace.total_cost_usd)}</span>
                  {trace.llm_call_count > 0 && (
                    <span>{trace.llm_call_count} LLM</span>
                  )}
                  {trace.tool_call_count > 0 && (
                    <span>{trace.tool_call_count} tools</span>
                  )}
                </div>
              </div>
            </button>
          ))}
        </div>
      )}

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
            {loadingMore ? "Loading…" : "Load more"}
          </Button>
        </div>
      )}
    </div>
  );
}
