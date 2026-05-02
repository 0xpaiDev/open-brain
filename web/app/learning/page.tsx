"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { StatCard } from "./_components/stat-card";
import { OverallProgressCard } from "./_components/overall-progress-card";
import { TopicCard } from "./_components/topic-card";
import { useLearning } from "@/hooks/use-learning";
import { cn } from "@/lib/utils";

type Filter = "all" | "active" | "inactive";

const FILTER_KEY = "ob:learning:filter";

function isValidFilter(v: unknown): v is Filter {
  return v === "all" || v === "active" || v === "inactive";
}

function FilterPills({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  const opts: { v: Filter; label: string }[] = [
    { v: "all", label: "All" },
    { v: "active", label: "Active" },
    { v: "inactive", label: "Inactive" },
  ];
  return (
    <div role="group" aria-label="Filter topics" className="flex gap-1">
      {opts.map((o) => (
        <button
          key={o.v}
          type="button"
          aria-pressed={value === o.v}
          onClick={() => onChange(o.v)}
          className={cn(
            "rounded-lg border px-3.5 py-1.5 text-[12.5px] transition-all",
            value === o.v
              ? "bg-primary text-primary-foreground border-primary font-semibold"
              : "bg-surface-container border-border text-on-surface-variant hover:bg-surface-container-high",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function LearningPage() {
  const {
    topics,
    loading,
    error,
    createTopic,
    toggleTopicActive,
    createSection,
    deleteSection,
    createItem,
    updateItem,
    deleteItem,
    triggerRefresh,
  } = useLearning();

  const [newTopicName, setNewTopicName] = useState("");
  const [filter, setFilter] = useState<Filter>(() => {
    if (typeof window === "undefined") return "all";
    const stored = localStorage.getItem(FILTER_KEY);
    return isValidFilter(stored) ? stored : "all";
  });

  useEffect(() => {
    localStorage.setItem(FILTER_KEY, filter);
  }, [filter]);

  const stats = useMemo(() => {
    const topicCount = topics.length;
    const activeCount = topics.filter((t) => t.is_active).length;
    const allItems = topics.flatMap((t) => t.sections.flatMap((s) => s.items));
    const totalItems = allItems.length;
    const doneItems = allItems.filter((i) => i.status === "done").length;
    const overallPct = totalItems === 0 ? 0 : doneItems / totalItems;
    return { topicCount, activeCount, totalItems, doneItems, overallPct };
  }, [topics]);

  const filteredTopics = useMemo(() => {
    if (filter === "active") return topics.filter((t) => t.is_active);
    if (filter === "inactive") return topics.filter((t) => !t.is_active);
    return topics;
  }, [topics, filter]);

  return (
    <div className="py-6 md:py-8 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl md:text-3xl font-headline font-bold">Learning Library</h1>
          <p className="text-sm text-on-surface-variant mt-1">
            Topics, sections, and items. Active topics feed into the morning todo list.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={triggerRefresh}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Refresh today
          </button>
          <Link href="/learning/import" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Import
          </Link>
        </div>
      </div>

      {/* Stats row */}
      <div className="flex flex-wrap gap-2.5">
        <StatCard value={stats.topicCount} label="Topics" />
        <StatCard value={stats.activeCount} label="Active" accent />
        <StatCard value={`${stats.doneItems}/${stats.totalItems}`} label="Items done" />
        <div className="flex-1 min-w-[160px]">
          <OverallProgressCard pct={stats.overallPct} />
        </div>
      </div>

      {/* Add topic + filters */}
      <div className="flex flex-col sm:flex-row gap-2.5">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const name = newTopicName.trim();
            if (name) {
              createTopic(name);
              setNewTopicName("");
            }
          }}
          className="flex-1 flex rounded-[9px] border border-border bg-surface-container overflow-hidden focus-within:border-primary transition-colors"
        >
          <input
            value={newTopicName}
            onChange={(e) => setNewTopicName(e.target.value)}
            placeholder="New topic name…"
            className="flex-1 bg-transparent px-3.5 py-2.5 text-base md:text-sm outline-none"
          />
          <button
            type="submit"
            disabled={!newTopicName.trim()}
            className="bg-primary text-primary-foreground px-4 text-sm font-semibold disabled:opacity-50 hover:opacity-85 transition-opacity"
          >
            Add topic
          </button>
        </form>
        <FilterPills value={filter} onChange={setFilter} />
      </div>

      {loading && <p className="text-sm text-on-surface-variant">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      {/* Topic list */}
      <div className="space-y-3">
        {filteredTopics.map((t) => (
          <TopicCard
            key={t.id}
            topic={t}
            onToggle={(active) => toggleTopicActive(t.id, active)}
            onAddSection={(name) => createSection(t.id, name)}
            onDeleteSection={deleteSection}
            onAddItem={(sectionId, title) => createItem(sectionId, title)}
            onUpdateItem={updateItem}
            onDeleteItem={deleteItem}
          />
        ))}
        {!loading && filteredTopics.length === 0 && (
          <p className="text-sm text-on-surface-variant text-center py-12">
            {filter === "all"
              ? "No topics yet. Create one to start."
              : `No ${filter} topics.`}
          </p>
        )}
      </div>
    </div>
  );
}
