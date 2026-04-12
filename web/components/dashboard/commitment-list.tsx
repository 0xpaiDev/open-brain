"use client";

import { useState } from "react";
import { Dumbbell, Flame, TrendingUp } from "lucide-react";
import { useCommitments } from "@/hooks/use-commitments";
import type { CommitmentResponse, CommitmentEntry } from "@/lib/types";

// ── Streak dots ──────────────────────────────────────────────────────────────

function StreakDots({ entries, today }: { entries: CommitmentEntry[]; today: string }) {
  // Show the last 7 entries up to today
  const recent = entries
    .filter((e) => e.entry_date <= today)
    .sort((a, b) => a.entry_date.localeCompare(b.entry_date))
    .slice(-7);

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {recent.map((entry) => (
        <span
          key={entry.id}
          className={`inline-block w-2 h-2 rounded-full ${
            entry.status === "hit"
              ? "bg-streak-hit"
              : entry.status === "miss"
                ? "bg-streak-miss"
                : "bg-streak-pending"
          }`}
          title={`${entry.entry_date}: ${entry.status} (${entry.logged_count})`}
        />
      ))}
    </div>
  );
}

// ── Log input ────────────────────────────────────────────────────────────────

function LogInput({
  commitmentId,
  onLog,
}: {
  commitmentId: string;
  onLog: (id: string, count: number) => Promise<unknown>;
}) {
  const [pending, setPending] = useState(false);

  const handleLog = async (count: number) => {
    setPending(true);
    try {
      await onLog(commitmentId, count);
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {[5, 10, 25].map((n) => (
        <button
          key={n}
          disabled={pending}
          onClick={() => handleLog(n)}
          className="bg-surface-container-high text-on-surface-variant rounded-full px-3 h-8 text-base md:text-sm font-body
            hover:bg-primary-container hover:text-on-primary-container active:scale-95 transition-all
            disabled:opacity-50 cursor-pointer"
        >
          +{n}
        </button>
      ))}
    </div>
  );
}

// ── Commitment card ──────────────────────────────────────────────────────────

function CommitmentCard({
  commitment,
  onLog,
}: {
  commitment: CommitmentResponse;
  onLog: (id: string, count: number) => Promise<unknown>;
}) {
  const today = new Date().toISOString().slice(0, 10);

  const todayEntry = commitment.entries.find((e) => e.entry_date === today);
  const totalDays =
    Math.ceil(
      (new Date(commitment.end_date).getTime() - new Date(commitment.start_date).getTime()) /
        (1000 * 60 * 60 * 24),
    ) + 1;
  const elapsedDays =
    Math.ceil(
      (new Date(today).getTime() - new Date(commitment.start_date).getTime()) /
        (1000 * 60 * 60 * 24),
    ) + 1;
  const dayNumber = Math.max(1, Math.min(elapsedDays, totalDays));

  const logged = todayEntry?.logged_count ?? 0;
  const progress = Math.min(logged / commitment.daily_target, 1);
  const isHit = todayEntry?.status === "hit";

  return (
    <div className="bg-surface-container rounded-2xl p-5 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Dumbbell className="w-4 h-4 text-primary" />
          <span className="font-headline text-lg text-on-surface">{commitment.name}</span>
        </div>
        <span className="text-on-surface-variant text-sm font-body">
          Day {dayNumber}/{totalDays}
        </span>
      </div>

      {/* Streak row */}
      <div className="flex items-center justify-between">
        <StreakDots entries={commitment.entries} today={today} />
        {commitment.current_streak > 0 && (
          <div className="flex items-center gap-1 text-streak-hit text-sm">
            <Flame className="w-3.5 h-3.5" />
            <span className="font-body">{commitment.current_streak}-day</span>
          </div>
        )}
      </div>

      {/* Today's progress */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <span className="text-on-surface-variant text-sm font-body">
            Today: {logged}/{commitment.daily_target} {commitment.metric}
          </span>
          {!isHit && todayEntry?.status !== "miss" && (
            <LogInput commitmentId={commitment.id} onLog={onLog} />
          )}
          {isHit && (
            <span className="text-streak-hit text-sm font-body flex items-center gap-1">
              Done
            </span>
          )}
        </div>

        {/* Progress bar */}
        <div className="h-2 rounded-full bg-surface-container-high overflow-hidden">
          <div
            className={`h-full rounded-full transition-[width] duration-300 ease-out ${
              isHit ? "bg-streak-hit" : "bg-primary-container"
            }`}
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </div>
    </div>
  );
}

// ── Aggregate commitment card ────────────────────────────────────────────────

function PaceBadge({ pace }: { pace: Record<string, number> | null }) {
  if (!pace || pace.overall === undefined) {
    return (
      <span className="rounded-full px-2 py-0.5 text-xs font-body bg-outline/20 text-outline">
        No data
      </span>
    );
  }

  const overall = pace.overall;
  if (overall >= 1.0) {
    return (
      <span className="rounded-full px-2 py-0.5 text-xs font-body bg-streak-hit/20 text-streak-hit">
        Ahead
      </span>
    );
  }
  if (overall >= 0.7) {
    return (
      <span className="rounded-full px-2 py-0.5 text-xs font-body bg-amber-500/20 text-amber-500">
        Behind
      </span>
    );
  }
  return (
    <span className="rounded-full px-2 py-0.5 text-xs font-body bg-streak-miss/20 text-streak-miss">
      Behind
    </span>
  );
}

const METRIC_LABELS: Record<string, string> = {
  km: "km",
  tss: "TSS",
  minutes: "min",
  hours: "hrs",
  elevation_m: "m elev",
};

function AggregateCommitmentCard({ commitment }: { commitment: CommitmentResponse }) {
  const today = new Date().toISOString().slice(0, 10);
  const targets = commitment.targets ?? {};
  const progress = commitment.progress ?? {};

  const totalDays =
    Math.ceil(
      (new Date(commitment.end_date).getTime() - new Date(commitment.start_date).getTime()) /
        (1000 * 60 * 60 * 24),
    ) + 1;
  const elapsedDays =
    Math.ceil(
      (new Date(today).getTime() - new Date(commitment.start_date).getTime()) /
        (1000 * 60 * 60 * 24),
    ) + 1;
  const dayNumber = Math.max(1, Math.min(elapsedDays, totalDays));
  const daysLeft = Math.max(0, totalDays - dayNumber);

  return (
    <div className="bg-surface-container rounded-2xl p-5 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-primary" />
          <span className="font-headline text-lg text-on-surface">{commitment.name}</span>
        </div>
        <span className="text-on-surface-variant text-sm font-body">
          Day {dayNumber}/{totalDays}
        </span>
      </div>

      {/* Pace badge + deadline */}
      <div className="flex items-center justify-between">
        <PaceBadge pace={commitment.pace} />
        <span className="text-on-surface-variant text-sm font-body">
          {daysLeft > 0 ? `${daysLeft} days left` : "Ended"}
        </span>
      </div>

      {/* Per-metric progress bars */}
      <div className="space-y-2">
        {Object.entries(targets).map(([metric, target]) => {
          const actual = progress[metric] ?? 0;
          const pct = target > 0 ? Math.min(actual / target, 1) : 0;
          const metricPace = commitment.pace?.[metric] ?? 0;
          const barColor =
            metricPace >= 1.0
              ? "bg-streak-hit"
              : metricPace >= 0.7
                ? "bg-amber-500"
                : "bg-streak-miss";

          return (
            <div key={metric}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-on-surface-variant text-sm font-body">
                  {actual.toFixed(1)}/{target} {METRIC_LABELS[metric] ?? metric}
                </span>
                <span className="text-on-surface-variant text-xs font-body">
                  {(pct * 100).toFixed(0)}%
                </span>
              </div>
              <div className="h-2 rounded-full bg-surface-container-high overflow-hidden">
                <div
                  className={`h-full rounded-full motion-safe:transition-[width] motion-safe:duration-300 motion-safe:ease-out ${barColor}`}
                  style={{ width: `${pct * 100}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Commitment list (main export) ────────────────────────────────────────────

export function CommitmentList() {
  const { commitments, loading, logCount } = useCommitments();

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2].map((n) => (
          <div key={n} className="h-36 bg-surface-container rounded-2xl animate-pulse" />
        ))}
      </div>
    );
  }

  if (commitments.length === 0) return null;

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Dumbbell className="w-5 h-5 text-primary" />
        <h2 className="text-lg font-headline font-semibold text-on-surface">Commitments</h2>
        <span className="bg-primary-container text-on-primary-container text-xs font-body rounded-full px-2 py-0.5">
          {commitments.length}
        </span>
      </div>
      {commitments.map((c) =>
        c.cadence === "aggregate" ? (
          <AggregateCommitmentCard key={c.id} commitment={c} />
        ) : (
          <CommitmentCard key={c.id} commitment={c} onLog={logCount} />
        ),
      )}
    </div>
  );
}
