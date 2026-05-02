"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { ItemRow } from "./item-row";
import type { LearningItem, LearningSection } from "@/lib/types";

interface SectionBlockProps {
  section: LearningSection;
  onAddItem?: (title: string) => void;
  onUpdateItem?: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
  onDeleteItem?: (id: string) => void;
  onDeleteSection?: (id: string) => void;
  editable?: boolean;
}

export function SectionBlock({
  section,
  onAddItem,
  onUpdateItem,
  onDeleteItem,
  onDeleteSection,
  editable = false,
}: SectionBlockProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [addingItem, setAddingItem] = useState(false);
  const [newItemTitle, setNewItemTitle] = useState("");

  const doneCount = section.items.filter((i) => i.status === "done").length;
  const totalCount = section.items.length;
  const pct = totalCount === 0 ? 0 : doneCount / totalCount;
  const hasProgress = doneCount > 0;

  function submitNewItem() {
    const trimmed = newItemTitle.trim();
    if (!trimmed || !onAddItem) return;
    onAddItem(trimmed);
    setNewItemTitle("");
    setAddingItem(false);
  }

  return (
    <div className="group/section relative">
      {/* Header */}
      <div
        className="flex items-center gap-2 py-1.5 cursor-pointer select-none"
        onClick={() => setCollapsed((c) => !c)}
      >
        {/* Accent bar showing progress */}
        <div className="w-0.5 self-stretch rounded-full bg-border overflow-hidden shrink-0">
          <div
            className={cn("w-full rounded-full transition-[height] duration-300", pct >= 1 ? "bg-streak-hit" : "bg-primary")}
            style={{ height: `${pct * 100}%` }}
          />
        </div>

        <span className="flex-1 min-w-0 text-[11px] font-semibold uppercase tracking-wider text-on-surface-variant truncate">
          {section.name}
        </span>

        {hasProgress && (
          <span className="shrink-0 text-[10px] font-semibold text-on-surface-variant tabular-nums">
            {doneCount}/{totalCount}
          </span>
        )}

        {/* Delete section */}
        {onDeleteSection && (
          <button
            type="button"
            aria-label={`Delete section ${section.name}`}
            onClick={(e) => { e.stopPropagation(); onDeleteSection(section.id); }}
            className="shrink-0 size-4 flex items-center justify-center rounded text-on-surface-variant hover:text-tertiary transition-colors opacity-100 sm:opacity-0 sm:group-hover/section:opacity-100"
          >
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none" aria-hidden="true">
              <path d="M1 1L9 9M9 1L1 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        )}

        {/* Chevron */}
        <svg
          width="10"
          height="6"
          viewBox="0 0 10 6"
          fill="none"
          aria-hidden="true"
          className={cn("shrink-0 text-on-surface-variant transition-transform duration-200", collapsed ? "-rotate-90" : "rotate-0")}
        >
          <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>

      {/* Items */}
      {!collapsed && (
        <div className="ml-3 pl-2 border-l border-border/50 space-y-0.5 pb-1">
          <ul className="space-y-0.5">
            {section.items.map((item) => (
              <ItemRow
                key={item.id}
                item={item}
                onUpdate={onUpdateItem}
                onDelete={onDeleteItem}
                editable={editable}
              />
            ))}
          </ul>

          {/* Add item */}
          {onAddItem && (
            addingItem ? (
              <div className="flex items-center gap-1.5 pt-1">
                <input
                  autoFocus
                  value={newItemTitle}
                  onChange={(e) => setNewItemTitle(e.target.value)}
                  onBlur={() => {
                    if (!newItemTitle.trim()) setAddingItem(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitNewItem();
                    if (e.key === "Escape") { setNewItemTitle(""); setAddingItem(false); }
                  }}
                  placeholder="Item title…"
                  className="flex-1 bg-surface-container-high rounded px-2 py-1 text-base md:text-sm outline-none focus:ring-1 ring-primary"
                />
                <button
                  type="button"
                  onClick={submitNewItem}
                  disabled={!newItemTitle.trim()}
                  className="text-xs text-primary font-semibold disabled:opacity-40 hover:opacity-75 transition-opacity"
                >
                  Add
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setAddingItem(true)}
                className="mt-1 text-[11px] text-on-surface-variant hover:text-primary transition-colors"
              >
                + Add item
              </button>
            )
          )}
        </div>
      )}
    </div>
  );
}
