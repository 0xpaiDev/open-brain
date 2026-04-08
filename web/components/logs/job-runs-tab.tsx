"use client";

import { useState } from "react";
import type { JobRunItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

interface JobRunsTabProps {
  items: JobRunItem[];
  total: number;
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => Promise<void>;
  jobName: string | null;
  setJobName: (v: string | null) => void;
  statusFilter: string | null;
  setStatusFilter: (v: string | null) => void;
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

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function JobRunRow({ run }: { run: JobRunItem }) {
  const hasError = !!run.error_message;

  const row = (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors">
      <span className="material-symbols-outlined text-base text-on-surface-variant">
        {run.status === "failed" ? "error" : run.status === "running" ? "sync" : "check_circle"}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-on-surface">
            {run.job_name}
          </span>
          <StatusBadge status={run.status} />
        </div>
        <p className="text-xs text-on-surface-variant mt-0.5">
          {formatTime(run.started_at)} &middot;{" "}
          {formatDuration(run.duration_seconds)}
        </p>
      </div>
      {hasError && (
        <span className="material-symbols-outlined text-base text-on-surface-variant">
          expand_more
        </span>
      )}
    </div>
  );

  if (!hasError) return row;

  return (
    <Collapsible>
      <CollapsibleTrigger className="w-full text-left">{row}</CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mx-3 mb-2 p-3 rounded-lg bg-error/5 border border-error/10">
          <pre className="text-xs text-error whitespace-pre-wrap break-words font-mono">
            {run.error_message}
          </pre>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

export function JobRunsTab({
  items,
  total,
  loading,
  error,
  hasMore,
  loadMore,
  jobName,
  setJobName,
  statusFilter,
  setStatusFilter,
}: JobRunsTabProps) {
  const [loadingMore, setLoadingMore] = useState(false);

  if (loading) {
    return (
      <div
        className="space-y-2"
        role="status"
        aria-busy="true"
      >
        {[1, 2, 3].map((n) => (
          <div
            key={n}
            className="flex items-center gap-3 px-3 py-2.5"
          >
            <div className="w-5 h-5 rounded-full bg-surface-container-high animate-pulse" />
            <div className="flex-1 space-y-1.5">
              <div className="h-4 w-32 bg-surface-container-high rounded-lg animate-pulse" />
              <div className="h-3 w-48 bg-surface-container-high rounded-lg animate-pulse" />
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

  const hasFilters = jobName !== null || statusFilter !== null;

  return (
    <div className="space-y-3">
      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        <select
          value={jobName ?? ""}
          onChange={(e) => setJobName(e.target.value || null)}
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="Filter by job"
        >
          <option value="">All jobs</option>
          <option value="pulse">pulse</option>
          <option value="importance">importance</option>
          <option value="synthesis">synthesis</option>
        </select>

        <select
          value={statusFilter ?? ""}
          onChange={(e) => setStatusFilter(e.target.value || null)}
          className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
          aria-label="Filter by status"
        >
          <option value="">All statuses</option>
          <option value="success">success</option>
          <option value="failed">failed</option>
          <option value="running">running</option>
        </select>

        {hasFilters && (
          <button
            type="button"
            onClick={() => {
              setJobName(null);
              setStatusFilter(null);
            }}
            className="text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Clear filters
          </button>
        )}

        <span className="text-xs text-on-surface-variant ml-auto">
          {total} run{total === 1 ? "" : "s"}
        </span>
      </div>

      {/* List */}
      {items.length === 0 ? (
        <div className="py-8 text-center">
          <span className="material-symbols-outlined text-on-surface-variant text-3xl mb-2 block">
            history
          </span>
          <p className="text-on-surface-variant text-sm">
            {hasFilters
              ? "No runs match the selected filters"
              : "No job runs found"}
          </p>
          {!hasFilters && (
            <p className="text-on-surface-variant/60 text-xs mt-1">
              Scheduled jobs will appear here after their first execution
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-0.5">
          {items.map((run) => (
            <JobRunRow key={run.id} run={run} />
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
