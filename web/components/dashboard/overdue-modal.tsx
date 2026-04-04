"use client";

import { useState } from "react";
import { useOverdue } from "@/hooks/use-overdue";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";

function OverdueTaskRow({
  todo,
  onDefer,
}: {
  todo: { id: string; description: string; due_date: string | null };
  onDefer: (id: string, dueDate: string, reason: string) => Promise<void>;
}) {
  const [deferDate, setDeferDate] = useState("");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleDefer() {
    if (!deferDate || !reason.trim()) return;
    setSubmitting(true);
    try {
      await onDefer(todo.id, deferDate, reason.trim());
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="rounded-lg border border-outline-variant/30 p-3 space-y-2">
      <p className="text-sm text-on-surface font-medium">{todo.description}</p>
      {todo.due_date && (
        <p className="text-xs text-error">
          Was due {new Date(todo.due_date).toLocaleDateString()}
        </p>
      )}
      <Input
        type="date"
        value={deferDate}
        onChange={(e) => setDeferDate(e.target.value)}
        aria-label="New due date"
        className="w-full"
      />
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Why are you deferring? (required)"
        className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary resize-none"
        rows={2}
        aria-label="Defer reason"
      />
      <Button
        size="sm"
        disabled={!deferDate || !reason.trim() || submitting}
        onClick={handleDefer}
        className="w-full"
      >
        Defer
      </Button>
    </div>
  );
}

export function OverdueModal() {
  const { overdueTodos, loading, deferOverdue, allHandled } = useOverdue();

  if (loading || allHandled) return null;

  return (
    <Dialog open onOpenChange={() => {}}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Overdue Tasks</DialogTitle>
          <DialogDescription>
            These tasks are past due. Defer each one with a new date and reason to continue.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[60vh] overflow-y-auto space-y-3">
          {overdueTodos.map((todo) => (
            <OverdueTaskRow key={todo.id} todo={todo} onDefer={deferOverdue} />
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
