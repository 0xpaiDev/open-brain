"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { ChatSourceItem } from "@/lib/types";

interface ChatSourcesProps {
  sources: ChatSourceItem[];
}

const TYPE_ICONS: Record<string, string> = {
  decision: "gavel",
  task: "task_alt",
  context: "info",
  memory: "database",
};

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

export function ChatSources({ sources }: ChatSourcesProps) {
  if (sources.length === 0) return null;

  return (
    <Collapsible>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-outline hover:text-on-surface-variant transition-colors py-1 cursor-pointer">
        <span className="material-symbols-outlined text-sm">source</span>
        Sources ({sources.length})
        <span className="material-symbols-outlined text-sm">expand_more</span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="mt-2 space-y-2">
          {sources.map((source) => (
            <div
              key={source.id}
              className="rounded-lg border border-outline-variant/15 bg-surface-container-lowest p-3 text-xs"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span className="material-symbols-outlined text-sm text-primary">
                  {TYPE_ICONS[source.type] ?? "article"}
                </span>
                <span className="font-label text-on-surface-variant uppercase tracking-wider">
                  {source.type}
                </span>
                {source.project && (
                  <span className="text-outline px-1.5 py-0.5 rounded bg-surface-container-low">
                    {source.project}
                  </span>
                )}
                <span className="ml-auto text-outline">
                  {(source.combined_score * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-on-surface-variant leading-relaxed">
                {source.summary
                  ? truncate(source.summary, 200)
                  : truncate(source.content, 200)}
              </p>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
