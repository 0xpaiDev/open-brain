"use client";

import { useState } from "react";
import { toast } from "sonner";
import type { TodoItem } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { getFocusDateLabel, PERSONAL } from "./task-utils";

export interface FocusCardProps {
  todo: TodoItem | null;
  /** Color of the focused todo's project (for the left rail tint). */
  accentColor?: string;
  /** Display name for the project chip; "Personal" when todo.project is null. */
  projectLabel?: string;
  onClear: () => void;
  onComplete: (id: string) => void;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

function DeferDialog({
  todoId,
  onDefer,
}: {
  todoId: string;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [deferDate, setDeferDate] = useState("");
  const [deferReason, setDeferReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit() {
    if (!deferDate) return;
    setSubmitting(true);
    try {
      await onDefer(todoId, deferDate, deferReason || undefined);
      const d = new Date(deferDate + "T00:00:00");
      const label = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
      toast.success(`Deferred to ${label}`);
      setOpen(false);
      setDeferDate("");
      setDeferReason("");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <button
            type="button"
            aria-label="Defer focus todo to a later day"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-surface-container hover:bg-surface-container-high transition-colors text-sm font-medium text-on-surface-variant active:scale-95"
          />
        }
      >
        <span className="material-symbols-outlined text-base">calendar_month</span>
        Defer
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Defer Task</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 py-2">
          <Input
            type="date"
            value={deferDate}
            onChange={(e) => setDeferDate(e.target.value)}
            aria-label="New due date"
          />
          <textarea
            value={deferReason}
            onChange={(e) => setDeferReason(e.target.value)}
            placeholder="Reason (optional)"
            className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary resize-none"
            rows={2}
            aria-label="Defer reason"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" disabled={!deferDate || submitting} onClick={handleSubmit}>
            Defer
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function FocusCard({
  todo,
  accentColor,
  projectLabel,
  onClear: _onClear,
  onComplete,
  onDefer,
  onDelete,
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

  async function handleDelete() {
    if (!confirm(`Delete "${todo!.description}"? This cannot be undone.`)) return;
    await onDelete(todo!.id);
  }

  return (
    <div
      className="rounded-2xl px-5 py-4 bg-surface-container-low ring-1 ring-outline-variant/15 shadow-sm"
      style={cardStyle}
      aria-label="Focused task"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <p className="text-base font-medium text-on-surface leading-snug flex-1 min-w-0">
          {todo.description}
        </p>
        <div className="flex items-center gap-1.5 flex-wrap justify-end shrink-0">
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

      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={() => onComplete(todo.id)}
          aria-label={`Mark "${todo.description}" done and clear focus`}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-streak-hit/15 text-streak-hit hover:bg-streak-hit/25 transition-colors text-sm font-medium active:scale-95"
        >
          <span className="material-symbols-outlined text-base">check</span>
          Done
        </button>
        <DeferDialog todoId={todo.id} onDefer={onDefer} />
        <button
          type="button"
          onClick={() => void handleDelete()}
          aria-label={`Delete "${todo.description}" permanently`}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-full bg-error/10 text-error hover:bg-error/20 transition-colors text-sm font-medium active:scale-95"
        >
          <span className="material-symbols-outlined text-base">delete</span>
          Delete
        </button>
      </div>
    </div>
  );
}
