"use client";

import { useRef, useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import type { LearningItem } from "@/lib/types";

interface ItemRowProps {
  item: LearningItem;
  onUpdate?: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
  onDelete?: (id: string) => void;
  editable?: boolean;
}

export function ItemRow({ item, onUpdate, onDelete, editable = false }: ItemRowProps) {
  const [editingTitle, setEditingTitle] = useState(false);
  const [editTitle, setEditTitle] = useState(item.title);
  const [showFeedback, setShowFeedback] = useState(false);
  const [feedback, setFeedback] = useState(item.feedback ?? "");
  const [notes, setNotes] = useState(item.notes ?? "");
  const [animating, setAnimating] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const isDone = item.status === "done";

  function handleCheck() {
    if (!onUpdate) return;
    setAnimating(true);
    onUpdate(item.id, { status: isDone ? "pending" : "done" });
    setTimeout(() => setAnimating(false), 200);
  }

  function handleTitleDoubleClick() {
    if (!onUpdate) return;
    setEditTitle(item.title);
    setEditingTitle(true);
    setTimeout(() => inputRef.current?.select(), 0);
  }

  function commitTitle() {
    if (!onUpdate) return;
    const trimmed = editTitle.trim();
    if (trimmed && trimmed !== item.title) {
      onUpdate(item.id, { title: trimmed });
    }
    setEditingTitle(false);
  }

  return (
    <li className="group/item text-sm">
      <div className="flex items-center gap-2 py-0.5">
        {/* Custom checkbox */}
        <button
          type="button"
          role="checkbox"
          aria-checked={isDone}
          aria-label={`Mark ${item.title} ${isDone ? "incomplete" : "complete"}`}
          onClick={handleCheck}
          disabled={!onUpdate}
          className={cn(
            "shrink-0 size-[18px] rounded-[4px] border flex items-center justify-center transition-colors",
            animating && "animate-ob-checkPop",
            isDone
              ? "bg-primary border-primary"
              : "border-border bg-transparent hover:border-primary",
            !onUpdate && "cursor-default",
          )}
        >
          {isDone && (
            <svg width="10" height="8" viewBox="0 0 10 8" fill="none" aria-hidden="true">
              <path d="M1 4L3.5 6.5L9 1" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
        </button>

        {/* Title — double-click to rename */}
        <div className="flex-1 min-w-0">
          {editingTitle ? (
            <input
              ref={inputRef}
              value={editTitle}
              onChange={(e) => setEditTitle(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitTitle();
                if (e.key === "Escape") { setEditTitle(item.title); setEditingTitle(false); }
              }}
              className="w-full bg-surface-container-high rounded px-1.5 py-0.5 text-base md:text-sm outline-none focus:ring-1 ring-primary"
            />
          ) : (
            <span
              onDoubleClick={handleTitleDoubleClick}
              title={onUpdate ? "Double-click to rename" : undefined}
              className={cn(
                "block truncate select-none",
                isDone ? "line-through text-on-surface-variant" : "",
                onUpdate ? "cursor-text" : "",
              )}
            >
              {item.title}
            </span>
          )}
        </div>

        {/* Feedback toggle (editable mode only) */}
        {editable && onUpdate && (
          <button
            type="button"
            aria-label="Toggle feedback/notes"
            onClick={() => setShowFeedback((s) => !s)}
            className="shrink-0 text-[10px] text-on-surface-variant hover:text-primary transition-colors px-1"
          >
            ▾
          </button>
        )}

        {/* Delete X */}
        {onDelete && (
          <button
            type="button"
            aria-label={`Delete ${item.title}`}
            onClick={() => onDelete(item.id)}
            className="shrink-0 size-4 flex items-center justify-center rounded text-on-surface-variant hover:text-tertiary transition-colors opacity-100 sm:opacity-0 sm:group-hover/item:opacity-100"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
              <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        )}
      </div>

      {/* Feedback/notes — only on detail page (editable) */}
      {editable && showFeedback && onUpdate && (
        <div className="mt-1.5 ml-6 space-y-1.5">
          <Textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            onBlur={() => {
              if (feedback !== (item.feedback ?? "")) {
                onUpdate(item.id, { feedback });
              }
            }}
            placeholder="Feedback (too easy / just right / too hard)"
            rows={2}
          />
          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={() => {
              if (notes !== (item.notes ?? "")) {
                onUpdate(item.id, { notes });
              }
            }}
            placeholder="Notes"
            rows={2}
          />
        </div>
      )}
    </li>
  );
}
