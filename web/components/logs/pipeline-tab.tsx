"use client";

import type { QueueStatusResponse } from "@/lib/types";

interface PipelineTabProps {
  status: QueueStatusResponse | null;
  loading: boolean;
  error: string | null;
}

function StatusCard({
  label,
  count,
  icon,
  colorClass,
}: {
  label: string;
  count: number;
  icon: string;
  colorClass: string;
}) {
  return (
    <div className="bg-surface-container rounded-xl p-4 flex items-center gap-3">
      <span className={`material-symbols-outlined text-xl ${colorClass}`}>
        {icon}
      </span>
      <div>
        <p className="text-2xl font-headline font-bold text-on-surface">
          {count}
        </p>
        <p className="text-xs text-on-surface-variant font-label uppercase tracking-wider">
          {label}
        </p>
      </div>
    </div>
  );
}

export function PipelineTab({ status, loading, error }: PipelineTabProps) {
  if (loading) {
    return (
      <div
        className="grid grid-cols-2 md:grid-cols-4 gap-3"
        role="status"
        aria-busy="true"
      >
        {[1, 2, 3, 4].map((n) => (
          <div
            key={n}
            className="bg-surface-container rounded-xl p-4 h-20 animate-pulse"
          />
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

  const s = status ?? {
    pending: 0,
    processing: 0,
    done: 0,
    failed: 0,
    total: 0,
    oldest_locked_at: null,
  };

  const isStale =
    s.oldest_locked_at &&
    Date.now() - new Date(s.oldest_locked_at).getTime() > 10 * 60 * 1000;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatusCard
          label="Pending"
          count={s.pending}
          icon="hourglass_empty"
          colorClass="text-on-surface-variant"
        />
        <StatusCard
          label="Processing"
          count={s.processing}
          icon="sync"
          colorClass="text-tertiary"
        />
        <StatusCard
          label="Done"
          count={s.done}
          icon="check_circle"
          colorClass="text-primary"
        />
        <StatusCard
          label="Failed"
          count={s.failed}
          icon="error"
          colorClass="text-error"
        />
      </div>

      {isStale && (
        <div className="bg-tertiary/10 text-tertiary border border-tertiary/20 rounded-xl p-3 flex items-center gap-2 text-sm">
          <span className="material-symbols-outlined text-base">warning</span>
          <span>
            Worker may be stuck — oldest lock is{" "}
            {Math.round(
              (Date.now() - new Date(s.oldest_locked_at!).getTime()) / 60000,
            )}{" "}
            minutes old
          </span>
        </div>
      )}
    </div>
  );
}
