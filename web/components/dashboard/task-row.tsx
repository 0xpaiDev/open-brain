"use client";

import { useEffect, useState } from "react";
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
import { BottomSheet } from "@/components/ui/bottom-sheet";


export function DoneTaskRow({ todo }: { todo: TodoItem }) {
  return (
    <div className="flex items-center gap-3 py-1.5 px-3 opacity-60">
      <div className="w-5 h-5 rounded-full bg-primary/30 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-primary text-xs">check</span>
      </div>
      <span className="flex-1 text-sm text-on-surface-variant line-through">
        {todo.description}
      </span>
    </div>
  );
}

function DeferPopover({
  todoId,
  onDefer,
}: {
  todoId: string;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
}) {
  const [deferDate, setDeferDate] = useState("");
  const [deferReason, setDeferReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [open, setOpen] = useState(false);

  async function handleSubmit() {
    if (!deferDate) return;
    setSubmitting(true);
    try {
      await onDefer(todoId, deferDate, deferReason || undefined);
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
            aria-label="Defer task"
            className="min-w-8 min-h-8 flex items-center justify-center rounded-md hover:bg-surface-container-high transition-colors"
          />
        }
      >
        <span className="material-symbols-outlined text-on-surface-variant text-base">
          calendar_month
        </span>
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

function EditTodoSheet({
  todo,
  open,
  onOpenChange,
  onSave,
  onDelete,
}: {
  todo: TodoItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (description: string, dueDate: string | null, reason: string | null) => Promise<void>;
  onDelete: () => Promise<void>;
}) {
  const originalDue = todo.due_date ? todo.due_date.split("T")[0] : "";
  const [editDescription, setEditDescription] = useState(todo.description);
  const [editDueDate, setEditDueDate] = useState(originalDue);
  const [editReason, setEditReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setEditDescription(todo.description);
      setEditDueDate(todo.due_date ? todo.due_date.split("T")[0] : "");
      setEditReason("");
    }
  }, [open, todo.description, todo.due_date]);

  const dueChanged = editDueDate !== originalDue;
  const canSave = editDescription.trim().length > 0 && !saving;

  async function handleSave() {
    if (!canSave) return;
    setSaving(true);
    try {
      await onSave(
        editDescription.trim(),
        editDueDate || null,
        dueChanged && editReason.trim() ? editReason.trim() : null,
      );
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    setSaving(true);
    try {
      await onDelete();
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <BottomSheet open={open} onOpenChange={onOpenChange} ariaLabel="Edit task">
      <div className="flex flex-col gap-3 pt-4">
        <h2 className="font-heading text-base font-medium text-on-surface">Edit task</h2>

        <label className="flex flex-col gap-1 text-sm text-on-surface-variant">
          Title
          <input
            type="text"
            value={editDescription}
            onChange={(e) => setEditDescription(e.target.value)}
            aria-label="Task title"
            className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm text-on-surface-variant">
          Due date
          <input
            type="date"
            value={editDueDate}
            onChange={(e) => setEditDueDate(e.target.value)}
            aria-label="Task due date"
            className="w-full rounded-md border border-outline-variant bg-surface px-3 py-2 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </label>

        {dueChanged && (
          <label className="flex flex-col gap-1 text-sm text-on-surface-variant">
            Reason (optional)
            <textarea
              value={editReason}
              onChange={(e) => setEditReason(e.target.value)}
              placeholder="Why are you moving this date?"
              rows={2}
              aria-label="Reason for defer"
              className="w-full resize-none rounded-md border border-outline-variant bg-surface px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-on-surface-variant focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </label>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={handleDelete}
          disabled={saving}
          className="text-error hover:bg-error/10"
          aria-label="Delete task"
        >
          <span className="material-symbols-outlined text-[18px] mr-1">delete</span>
          Delete
        </Button>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onOpenChange(false)}
            disabled={saving}
          >
            Cancel
          </Button>
          <Button type="button" size="sm" onClick={handleSave} disabled={!canSave}>
            Save
          </Button>
        </div>
      </div>
    </BottomSheet>
  );
}

export interface TaskRowProps {
  todo: TodoItem;
  focused: boolean;
  accentColor?: string;
  onSelectFocus: (id: string) => void;
  onComplete: (id: string) => void;
  onDefer: (id: string, dueDate: string, reason?: string) => Promise<void>;
  onEdit: (id: string, description: string, dueDate: string | null, reason?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}

export function TaskRow({
  todo,
  focused,
  accentColor,
  onSelectFocus,
  onComplete,
  onDefer,
  onEdit,
  onDelete,
}: TaskRowProps) {
  const [completing, setCompleting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editDescription, setEditDescription] = useState(todo.description);
  const [editDueDate, setEditDueDate] = useState(
    todo.due_date ? todo.due_date.split("T")[0] : "",
  );
  const [saving, setSaving] = useState(false);
  function handleCheck(e: React.MouseEvent) {
    e.stopPropagation();
    setCompleting(true);
    setTimeout(() => onComplete(todo.id), 300);
  }

  function startEditing(e: React.MouseEvent) {
    e.stopPropagation();
    setEditDescription(todo.description);
    setEditDueDate(todo.due_date ? todo.due_date.split("T")[0] : "");
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setEditDescription(todo.description);
    setEditDueDate(todo.due_date ? todo.due_date.split("T")[0] : "");
  }

  async function saveInlineEdit() {
    const trimmed = editDescription.trim();
    if (!trimmed) return;
    setSaving(true);
    try {
      await onEdit(todo.id, trimmed, editDueDate || null);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  function handleRowClick() {
    if (editing || completing) return;
    onSelectFocus(todo.id);
  }

  // Per-row tint for focused state, derived from project color.
  const focusedStyle = focused && accentColor
    ? { backgroundColor: `${accentColor}1A`, boxShadow: `inset 3px 0 0 ${accentColor}` }
    : undefined;

  return (
    <>
      <div
        role="button"
        tabIndex={editing ? -1 : 0}
        aria-pressed={focused}
        onClick={handleRowClick}
        onKeyDown={(e) => {
          if (editing) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            handleRowClick();
          }
        }}
        style={focusedStyle}
        className={`group flex items-center gap-3 py-2 px-3 rounded-lg transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary ${completing ? "opacity-50" : ""} ${
          focused
            ? ""
            : "hover:bg-surface-container-high/50"
        }`}
      >
        <button
          type="button"
          role="checkbox"
          aria-checked={completing}
          aria-label={`Complete: ${todo.description}`}
          onClick={handleCheck}
          disabled={completing || editing}
          className="min-w-11 min-h-11 flex items-center justify-center shrink-0"
        >
          <span
            className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all ${
              completing
                ? "bg-primary border-primary"
                : "border-outline-variant hover:border-primary"
            }`}
          >
            {completing && (
              <span className="material-symbols-outlined text-on-primary text-xs">check</span>
            )}
          </span>
        </button>

        {editing ? (
          <div
            className="flex-1 flex items-center gap-2 min-w-0"
            onClick={(e) => e.stopPropagation()}
            onKeyDown={(e) => e.stopPropagation()}
          >
            <input
              type="text"
              value={editDescription}
              onChange={(e) => setEditDescription(e.target.value)}
              aria-label={`Edit title: ${todo.description}`}
              disabled={saving}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void saveInlineEdit();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  cancelEditing();
                }
              }}
              className="flex-1 min-w-0 bg-surface-container rounded-md px-2 py-1 text-base md:text-sm text-on-surface border border-outline-variant focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <input
              type="date"
              value={editDueDate}
              onChange={(e) => setEditDueDate(e.target.value)}
              aria-label="Edit due date"
              disabled={saving}
              className="bg-surface-container rounded-md px-2 py-1 text-base md:text-sm text-on-surface border border-outline-variant focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <Button
              type="button"
              size="sm"
              onClick={saveInlineEdit}
              disabled={!editDescription.trim() || saving}
              aria-label="Save task edit"
            >
              Save
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={cancelEditing}
              disabled={saving}
              aria-label="Cancel task edit"
            >
              Cancel
            </Button>
          </div>
        ) : (
          <span
            className={`flex-1 text-sm transition-all ${
              completing ? "line-through text-on-surface-variant" : "text-on-surface"
            }`}
          >
            {todo.description}
          </span>
        )}

        {!editing && (
          <>
            <span
              className="hidden md:inline-flex"
              onClick={(e) => e.stopPropagation()}
            >
              <DeferPopover todoId={todo.id} onDefer={onDefer} />
            </span>

            {todo.label && (
              <span className="text-xs rounded-full px-2 py-0.5 shrink-0 font-label bg-surface-container-high text-on-surface-variant">
                {todo.label}
              </span>
            )}

            {todo.learning_item_id && (
              <span
                className="text-xs rounded-full px-2 py-0.5 shrink-0 font-label bg-accent/20 text-accent"
                title="Generated from your learning library"
              >
                Learning
              </span>
            )}

            <div
              className="hidden md:flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity"
              onClick={(e) => e.stopPropagation()}
            >
              <button
                type="button"
                onClick={startEditing}
                aria-label={`Edit task: ${todo.description}`}
                className="min-w-11 min-h-11 flex items-center justify-center rounded-md hover:bg-surface-container-high focus-visible:ring-2 focus-visible:ring-primary transition-colors"
              >
                <span className="material-symbols-outlined text-on-surface-variant text-[20px]">
                  edit
                </span>
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  void onDelete(todo.id);
                }}
                aria-label={`Delete task: ${todo.description}`}
                className="min-w-11 min-h-11 flex items-center justify-center rounded-md hover:bg-error/10 focus-visible:ring-2 focus-visible:ring-error transition-colors"
              >
                <span className="material-symbols-outlined text-error text-[20px]">delete</span>
              </button>
            </div>

            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                setSheetOpen(true);
              }}
              aria-label={`More actions for task: ${todo.description}`}
              className="md:hidden min-w-11 min-h-11 flex items-center justify-center rounded-md hover:bg-surface-container-high transition-colors"
            >
              <span className="material-symbols-outlined text-on-surface-variant text-[20px]">
                more_horiz
              </span>
            </button>
          </>
        )}
      </div>

      <EditTodoSheet
        todo={todo}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
        onSave={async (description, dueDate, reason) => {
          await onEdit(todo.id, description, dueDate, reason ?? undefined);
        }}
        onDelete={async () => {
          await onDelete(todo.id);
        }}
      />
    </>
  );
}
