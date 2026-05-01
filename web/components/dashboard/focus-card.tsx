"use client";

import type { TodoItem } from "@/lib/types";
import { getFocusDateLabel, PERSONAL } from "./task-utils";

export interface FocusCardProps {
  todo: TodoItem | null;
  /** Color of the focused todo's project (for the left rail tint). */
  accentColor?: string;
  /** Display name for the project chip; "Personal" when todo.project is null. */
  projectLabel?: string;
  onClear: () => void;
  onComplete: (id: string) => void;
}

export function FocusCard({
  todo,
  accentColor,
  projectLabel,
  onClear,
  onComplete,
}: FocusCardProps) {
  if (!todo) {
    return (
      <div
        className="rounded-2xl border border-dashed border-outline-variant/40 bg-surface-container-low/40 px-5 py-6 flex items-center justify-center text-center"
        aria-label="No focus selected"
      >
        <p className="text-sm text-on-surface-variant">
          No focus selected — tap a task to set focus.
        </p>
      </div>
    );
  }

  const badge = getFocusDateLabel(todo.due_date, todo.start_date);
  const tint = accentColor ?? "var(--color-primary)";
  const cardStyle = accentColor
    ? {
        backgroundColor: `${accentColor}14`,
        boxShadow: `inset 4px 0 0 ${accentColor}`,
      }
    : undefined;

  return (
    <div
      className="rounded-2xl px-5 py-4 bg-surface-container-low ring-1 ring-outline-variant/15 shadow-sm"
      style={cardStyle}
      aria-label="Focused task"
    >
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="flex items-center gap-1.5">
          <span
            className="text-[11px] rounded-full px-2 py-0.5 font-label"
            style={{
              backgroundColor: `${tint}26`,
              color: tint,
            }}
          >
            {projectLabel ?? PERSONAL}
          </span>
          {badge && (
            <span
              className={`text-[11px] rounded-full px-2 py-0.5 font-label ${badge.className}`}
            >
              {badge.label}
            </span>
          )}
        </div>
      </div>

      <p className="text-base font-medium text-on-surface leading-snug mb-3">
        {todo.description}
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onComplete(todo.id)}
          aria-label={`Mark "${todo.description}" done and clear focus`}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-streak-hit/15 text-streak-hit hover:bg-streak-hit/25 transition-colors text-sm font-medium active:scale-95"
        >
          <span className="material-symbols-outlined text-base">check</span>
          Done
        </button>
        <button
          type="button"
          onClick={onClear}
          aria-label="Skip focus (no completion)"
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-surface-container hover:bg-surface-container-high transition-colors text-sm font-medium text-on-surface-variant active:scale-95"
        >
          <span className="material-symbols-outlined text-base">skip_next</span>
          Skip
        </button>
      </div>
    </div>
  );
}
