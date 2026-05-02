"use client";

import { useState } from "react";
import Link from "next/link";
import { ProgressRing } from "@/components/ui/progress-ring";
import { Switch } from "@/components/ui/switch";
import { SectionBlock } from "./section-block";
import { cn } from "@/lib/utils";
import type { LearningItem, LearningTopic } from "@/lib/types";

interface TopicCardProps {
  topic: LearningTopic;
  onToggle: (active: boolean) => void;
  onAddSection: (name: string) => void;
  onDeleteSection: (id: string) => void;
  onAddItem: (sectionId: string, title: string) => void;
  onUpdateItem: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
  onDeleteItem: (id: string) => void;
}

export function TopicCard({
  topic,
  onToggle,
  onAddSection,
  onDeleteSection,
  onAddItem,
  onUpdateItem,
  onDeleteItem,
}: TopicCardProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [addingSectionName, setAddingSectionName] = useState("");
  const [addingSection, setAddingSection] = useState(false);

  const allItems = topic.sections.flatMap((s) => s.items);
  const totalItems = allItems.length;
  const doneItems = allItems.filter((i) => i.status === "done").length;
  const topicPct = totalItems === 0 ? 0 : doneItems / totalItems;
  const isComplete = totalItems > 0 && topicPct >= 1;

  function submitSection() {
    const name = addingSectionName.trim();
    if (!name) return;
    onAddSection(name);
    setAddingSectionName("");
    setAddingSection(false);
  }

  return (
    <section className="group/card rounded-[14px] border border-border bg-surface-container hover:border-surface-container-highest transition-colors animate-ob-fadeIn">
      {/* Header */}
      <header
        className="flex items-center gap-3 p-3.5 md:p-4 cursor-pointer"
        onClick={() => setCollapsed((c) => !c)}
      >
        <ProgressRing size={34} strokeWidth={2.5} pct={topicPct} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Link
              href={`/learning/topics/${topic.id}`}
              onClick={(e) => e.stopPropagation()}
              className="text-[14.5px] font-semibold truncate hover:text-primary transition-colors"
            >
              {topic.name}
            </Link>
            {isComplete && (
              <span className="shrink-0 bg-streak-hit/15 text-streak-hit text-[10px] font-semibold rounded-md px-1.5 py-px">
                Complete
              </span>
            )}
          </div>
          <p className="text-[11px] text-on-surface-variant mt-0.5">
            {topic.sections.length} section{topic.sections.length !== 1 ? "s" : ""} · {doneItems}/{totalItems} items
          </p>
        </div>

        {/* Active toggle — stopPropagation so click doesn't collapse */}
        <div
          onClick={(e) => e.stopPropagation()}
          className="flex items-center gap-2 py-2 -my-2"
        >
          <span
            className={cn(
              "text-[11px] font-medium hidden sm:inline",
              topic.is_active ? "text-streak-hit" : "text-on-surface-variant",
            )}
          >
            {topic.is_active ? "Active" : "Inactive"}
          </span>
          <Switch
            checked={topic.is_active}
            onCheckedChange={onToggle}
            aria-label={`Toggle ${topic.name} active`}
          />
        </div>

        {/* Chevron */}
        <svg
          width="10"
          height="6"
          viewBox="0 0 10 6"
          fill="none"
          aria-hidden="true"
          className={cn(
            "shrink-0 text-on-surface-variant transition-transform duration-200",
            collapsed ? "-rotate-90" : "rotate-0",
          )}
        >
          <path d="M1 1L5 5L9 1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </header>

      {/* Expanded content */}
      {!collapsed && (
        <div className="pb-3">
          {/* Progress bar */}
          {totalItems > 0 && (
            <div className="px-4 mb-3.5">
              <div className="h-0.5 bg-surface-container-high rounded">
                <div
                  className={cn(
                    "h-full rounded transition-[width] duration-[400ms]",
                    topicPct >= 1 ? "bg-streak-hit" : "bg-primary",
                  )}
                  style={{ width: `${topicPct * 100}%` }}
                />
              </div>
            </div>
          )}

          <div className="px-3 space-y-1.5">
            {topic.sections.map((s) => (
              <SectionBlock
                key={s.id}
                section={s}
                onAddItem={(title) => onAddItem(s.id, title)}
                onUpdateItem={onUpdateItem}
                onDeleteItem={onDeleteItem}
                onDeleteSection={onDeleteSection}
              />
            ))}

            {/* Add section */}
            {addingSection ? (
              <div className="flex items-center gap-1.5 pt-1 border-t border-dashed border-border mt-2">
                <input
                  autoFocus
                  value={addingSectionName}
                  onChange={(e) => setAddingSectionName(e.target.value)}
                  onBlur={() => {
                    if (!addingSectionName.trim()) setAddingSection(false);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") submitSection();
                    if (e.key === "Escape") { setAddingSectionName(""); setAddingSection(false); }
                  }}
                  placeholder="Section name…"
                  className="flex-1 bg-surface-container-high rounded px-2 py-1 text-base md:text-sm outline-none focus:ring-1 ring-primary"
                />
                <button
                  type="button"
                  onClick={submitSection}
                  disabled={!addingSectionName.trim()}
                  className="text-xs text-primary font-semibold disabled:opacity-40 hover:opacity-75 transition-opacity"
                >
                  Add
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setAddingSection(true)}
                className="w-full mt-1.5 py-2 rounded-lg border border-dashed border-border text-[12px] text-on-surface-variant hover:text-primary hover:border-primary transition-colors"
              >
                + Add section
              </button>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
