"use client";

import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";
import type { LearningItem } from "@/lib/types";

export function ItemRow({
  item,
  onUpdate,
}: {
  item: LearningItem;
  onUpdate?: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [feedback, setFeedback] = useState(item.feedback ?? "");
  const [notes, setNotes] = useState(item.notes ?? "");

  return (
    <li className="text-sm">
      <div className="flex items-center gap-2">
        {onUpdate && (
          <input
            type="checkbox"
            checked={item.status === "done"}
            onChange={(e) =>
              onUpdate(item.id, { status: e.target.checked ? "done" : "pending" })
            }
            aria-label={`Mark ${item.title} ${item.status === "done" ? "incomplete" : "complete"}`}
          />
        )}
        <button
          type="button"
          onClick={() => setExpanded((s) => !s)}
          className={`flex-1 text-left cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent rounded px-1 ${
            item.status === "done" ? "line-through text-muted-foreground" : ""
          }`}
        >
          {item.title}
        </button>
      </div>
      {expanded && (
        <div className="mt-2 ml-6 space-y-2">
          {item.feedback && !onUpdate && (
            <p className="text-xs text-on-surface-variant italic">{item.feedback}</p>
          )}
          {onUpdate && (
            <>
              <Textarea
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                onBlur={() => {
                  if (feedback !== (item.feedback ?? "")) {
                    onUpdate(item.id, { feedback });
                  }
                }}
                placeholder="Feedback (calibration — too easy / just right / too hard)"
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
                rows={3}
              />
            </>
          )}
          {!onUpdate && item.notes && (
            <p className="text-xs text-on-surface-variant">{item.notes}</p>
          )}
        </div>
      )}
    </li>
  );
}
