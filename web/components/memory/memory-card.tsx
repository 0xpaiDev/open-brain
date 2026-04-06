"use client";

import type { MemoryItemResponse, SearchResultItem } from "@/lib/types";
import { isSearchResult } from "@/hooks/use-memories";

function timeAgo(dateStr: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000,
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

const TYPE_CONFIG: Record<
  string,
  { icon: string; badge?: string; className: string }
> = {
  memory: {
    icon: "format_quote",
    className: "bg-surface-container-high",
  },
  decision: {
    icon: "gavel",
    badge: "DECISION",
    className: "bg-surface-container-high",
  },
  task: {
    icon: "task_alt",
    className: "bg-surface-container-high border-l-4 border-l-tertiary",
  },
  context: {
    icon: "info",
    badge: "CONTEXT",
    className: "bg-surface-container",
  },
};

interface MemoryCardProps {
  item: MemoryItemResponse | SearchResultItem;
}

export function MemoryCard({ item }: MemoryCardProps) {
  const config = TYPE_CONFIG[item.type] ?? TYPE_CONFIG.memory;
  const isSuperseded =
    !isSearchResult(item) && (item as MemoryItemResponse).is_superseded;
  const displayText = item.summary ?? item.content;

  return (
    <div
      className={`${config.className} rounded-2xl p-5 flex flex-col gap-3 transition-all hover:shadow-lg hover:shadow-black/10 ${
        isSuperseded ? "opacity-50" : ""
      }`}
    >
      {/* Header row: icon + badge + score */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="material-symbols-outlined text-on-surface-variant text-lg">
            {config.icon}
          </span>
          {config.badge && (
            <span className="text-[10px] font-label font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-secondary/20 text-secondary">
              {config.badge}
            </span>
          )}
          {item.project && (
            <span className="text-[10px] font-label font-semibold tracking-wider px-2 py-0.5 rounded-full bg-primary/15 text-primary">
              {item.project}
            </span>
          )}
        </div>

        {/* Score pill */}
        {isSearchResult(item) ? (
          <span className="text-[10px] font-label font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">
            {Math.round(item.combined_score * 100)}% match
          </span>
        ) : (
          item.importance_score != null && (
            <span className="text-[10px] font-label px-2 py-0.5 rounded-full bg-outline-variant/15 text-on-surface-variant">
              {item.importance_score.toFixed(2)}
            </span>
          )
        )}
      </div>

      {/* Content */}
      <p className="text-sm text-on-surface font-body line-clamp-3 leading-relaxed">
        {displayText}
      </p>

      {/* Footer: timestamp */}
      {!isSearchResult(item) && (
        <span className="text-xs text-outline font-label mt-auto">
          {timeAgo(item.created_at)}
        </span>
      )}
    </div>
  );
}
