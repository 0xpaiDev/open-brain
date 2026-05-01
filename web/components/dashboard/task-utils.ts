import type { TodoItem } from "@/lib/types";

/** Pseudo-project bucket for todos with project=null. Pinned to the top. */
export const PERSONAL = "Personal" as const;

export function formatDateButtonText(dateStr: string): string {
  if (!dateStr) return "No date";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const date = new Date(dateStr + "T00:00:00");
  date.setHours(0, 0, 0, 0);
  const diff = Math.floor((date.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function getDueBadge(
  dueDate: string | null,
  startDate?: string | null,
): { label: string; className: string } | null {
  if (!dueDate) return null;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);

  if (startDate) {
    const start = new Date(startDate);
    start.setHours(0, 0, 0, 0);
    if (today >= start && today <= due) {
      return { label: "Active", className: "bg-primary/10 text-primary" };
    }
  }

  const diffDays = Math.floor((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
  if (diffDays < 0) return { label: "Overdue", className: "bg-error/10 text-error" };
  if (diffDays === 0) return { label: "Today", className: "bg-tertiary/10 text-tertiary" };
  if (diffDays === 1) return { label: "Tomorrow", className: "bg-primary/10 text-primary" };

  return {
    label: due.toLocaleDateString([], { month: "short", day: "numeric" }),
    className: "bg-surface-container-high text-on-surface-variant",
  };
}

/** Parse a date string that may be ISO datetime or date-only (YYYY-MM-DD). */
function parseDateSafe(dateStr: string): Date | null {
  if (!dateStr) return null;
  // Normalize: full ISO strings already have T, date-only strings need local midnight appended
  const iso = dateStr.includes("T") ? dateStr : dateStr + "T00:00:00";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? null : d;
}

export function getFocusDateLabel(
  dueDate: string | null,
  startDate?: string | null,
): { label: string; className: string } | null {
  if (!dueDate && !startDate) return null;

  if (!dueDate && startDate) {
    // start_date set but no due_date — render start as a single-date label
    return getDueBadge(startDate);
  }

  if (dueDate && startDate) {
    const start = parseDateSafe(startDate);
    const due = parseDateSafe(dueDate);
    if (!start || !due) return getDueBadge(dueDate);

    // Swap inverted range silently so formatter never crashes
    const [earlier, later] = start.getTime() <= due.getTime() ? [start, due] : [due, start];

    if (earlier.getTime() !== later.getTime()) {
      const currentYear = new Date().getFullYear();
      const opts: Intl.DateTimeFormatOptions =
        earlier.getFullYear() !== currentYear || later.getFullYear() !== currentYear
          ? { month: "short", day: "numeric", year: "numeric" }
          : { month: "short", day: "numeric" };
      const s = earlier.toLocaleDateString([], opts);
      const e = later.toLocaleDateString([], opts);
      return { label: `${s} – ${e}`, className: "bg-primary/10 text-primary" };
    }
  }

  return getDueBadge(dueDate!);
}

export function getTomorrowDateString(): string {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return d.toISOString().split("T")[0];
}

export interface ProjectBucket {
  /** Project name; "Personal" for null. */
  key: string;
  /** Color from project_labels.color, or undefined for Personal/unknown. */
  color: string | undefined;
  todos: TodoItem[];
}

/**
 * Group todos by project. Personal (null) is pinned first; the remainder
 * follow alphabetical order. Empty buckets are omitted.
 *
 * `colorMap` maps project name → color. Personal and unknown names get
 * `undefined` color (callers fall back to the design system's default tint).
 */
export function groupTodosByProject(
  todos: TodoItem[],
  colorMap: Record<string, string>,
): ProjectBucket[] {
  const buckets = new Map<string, TodoItem[]>();
  for (const t of todos) {
    const key = t.project ?? PERSONAL;
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key)!.push(t);
  }

  const personal = buckets.get(PERSONAL) ?? [];
  buckets.delete(PERSONAL);

  const sortedRest = [...buckets.entries()].sort(([a], [b]) => a.localeCompare(b));

  const result: ProjectBucket[] = [];
  if (personal.length > 0) {
    result.push({ key: PERSONAL, color: colorMap[PERSONAL], todos: personal });
  }
  for (const [key, ts] of sortedRest) {
    result.push({ key, color: colorMap[key], todos: ts });
  }
  return result;
}
