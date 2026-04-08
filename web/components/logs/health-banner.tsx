"use client";

import type { JobStatusResponse } from "@/lib/types";

interface HealthBannerProps {
  jobStatus: JobStatusResponse | null;
  deadLetterCount: number;
  loading: boolean;
}

type HealthLevel = "healthy" | "warning" | "critical";

function getHealthLevel(
  jobStatus: JobStatusResponse | null,
  deadLetterCount: number,
): HealthLevel {
  if (!jobStatus) return "healthy";

  const overdueJobs = Object.values(jobStatus.jobs).filter((j) => j.overdue);
  const hasDeadLetters = deadLetterCount > 0;

  if (hasDeadLetters || overdueJobs.length > 1) return "critical";
  if (overdueJobs.length === 1) return "warning";
  return "healthy";
}

const healthConfig: Record<
  HealthLevel,
  { icon: string; label: string; className: string }
> = {
  healthy: {
    icon: "check_circle",
    label: "All systems operational",
    className: "bg-primary/10 text-primary border-primary/20",
  },
  warning: {
    icon: "warning",
    label: "Attention needed",
    className: "bg-tertiary/10 text-tertiary border-tertiary/20",
  },
  critical: {
    icon: "error",
    label: "Issues detected",
    className: "bg-error/10 text-error border-error/20",
  },
};

export function HealthBanner({
  jobStatus,
  deadLetterCount,
  loading,
}: HealthBannerProps) {
  if (loading) {
    return (
      <div
        className="rounded-2xl border p-4 bg-surface-container animate-pulse h-14"
        role="status"
        aria-busy="true"
      />
    );
  }

  const level = getHealthLevel(jobStatus, deadLetterCount);
  const config = healthConfig[level];

  const overdueNames = jobStatus
    ? Object.entries(jobStatus.jobs)
        .filter(([, j]) => j.overdue)
        .map(([name]) => name)
    : [];

  const details: string[] = [];
  if (overdueNames.length > 0) {
    details.push(`Overdue: ${overdueNames.join(", ")}`);
  }
  if (deadLetterCount > 0) {
    details.push(
      `${deadLetterCount} unresolved dead letter${deadLetterCount === 1 ? "" : "s"}`,
    );
  }

  return (
    <div
      className={`rounded-2xl border p-4 flex items-center gap-3 ${config.className}`}
    >
      <span className="material-symbols-outlined text-xl">{config.icon}</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{config.label}</p>
        {details.length > 0 && (
          <p className="text-xs opacity-80 mt-0.5">{details.join(" / ")}</p>
        )}
      </div>
    </div>
  );
}
