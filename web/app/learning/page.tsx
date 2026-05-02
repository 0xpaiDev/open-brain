"use client";

import { useState } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionBlock } from "./_components/section-block";
import { useLearning } from "@/hooks/use-learning";
import type { LearningItem, LearningTopic } from "@/lib/types";

export default function LearningPage() {
  const {
    topics,
    loading,
    error,
    createTopic,
    toggleTopicActive,
    createSection,
    createItem,
    updateItem,
    triggerRefresh,
  } = useLearning();

  const [newTopicName, setNewTopicName] = useState("");

  return (
    <div className="py-8 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">Learning Library</h1>
          <p className="text-on-surface-variant text-sm mt-1">
            Topics, sections, and items. Active topics feed into the morning todo list.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <Button onClick={triggerRefresh} variant="outline">
            Refresh today
          </Button>
          <Link href="/learning/import" className={buttonVariants({ variant: "outline" })}>
            Import
          </Link>
        </div>
      </div>

      <form
        className="flex gap-2 items-center"
        onSubmit={(e) => {
          e.preventDefault();
          if (newTopicName.trim()) {
            createTopic(newTopicName.trim());
            setNewTopicName("");
          }
        }}
      >
        <Input
          value={newTopicName}
          onChange={(e) => setNewTopicName(e.target.value)}
          placeholder="New topic name"
          className="max-w-sm"
        />
        <Button type="submit" disabled={!newTopicName.trim()}>
          Add topic
        </Button>
      </form>

      {loading && <p className="text-sm text-on-surface-variant">Loading…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}

      <div className="space-y-4">
        {topics.map((topic) => (
          <TopicCard
            key={topic.id}
            topic={topic}
            onToggle={(active) => toggleTopicActive(topic.id, active)}
            onAddSection={(name) => createSection(topic.id, name)}
            onAddItem={(sectionId, title) => createItem(sectionId, title)}
            onUpdateItem={updateItem}
          />
        ))}
        {!loading && topics.length === 0 && (
          <p className="text-sm text-on-surface-variant">
            No topics yet. Create one to start.
          </p>
        )}
      </div>
    </div>
  );
}

function TopicCard({
  topic,
  onToggle,
  onAddSection,
  onAddItem,
  onUpdateItem,
}: {
  topic: LearningTopic;
  onToggle: (active: boolean) => void;
  onAddSection: (name: string) => void;
  onAddItem: (sectionId: string, title: string) => void;
  onUpdateItem: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
}) {
  const [sectionName, setSectionName] = useState("");
  return (
    <section className="rounded-lg border border-outline-variant bg-surface-container p-4 space-y-3">
      <header className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          <Link
            href={`/learning/topics/${topic.id}`}
            className="text-lg font-semibold hover:text-primary transition-colors cursor-pointer"
          >
            {topic.name}
          </Link>
          <span className="text-xs rounded-full px-2 py-0.5 bg-accent/20 text-accent">
            {topic.depth}
          </span>
          {!topic.is_active && (
            <span className="text-xs rounded-full px-2 py-0.5 bg-muted text-muted-foreground">
              inactive
            </span>
          )}
          {topic.has_material && (
            <span className="text-xs rounded-full px-2 py-0.5 bg-secondary/30 text-secondary">
              material
            </span>
          )}
        </div>
        <label className="text-sm flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={topic.is_active}
            onChange={(e) => onToggle(e.target.checked)}
          />
          Active
        </label>
      </header>

      <div className="space-y-2 pl-2">
        {topic.sections.map((section) => (
          <SectionBlock
            key={section.id}
            section={section}
            onAddItem={(title) => onAddItem(section.id, title)}
            onUpdateItem={onUpdateItem}
          />
        ))}
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (sectionName.trim()) {
              onAddSection(sectionName.trim());
              setSectionName("");
            }
          }}
        >
          <Input
            value={sectionName}
            onChange={(e) => setSectionName(e.target.value)}
            placeholder="New section"
            className="max-w-xs"
          />
          <Button type="submit" variant="outline" size="sm" disabled={!sectionName.trim()}>
            Add section
          </Button>
        </form>
      </div>
    </section>
  );
}
