"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useLearning } from "@/hooks/use-learning";
import type { LearningItem, LearningSection, LearningTopic } from "@/lib/types";

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
        <Button onClick={triggerRefresh} variant="outline">
          Refresh today
        </Button>
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
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-semibold">{topic.name}</h2>
          <span className="text-xs rounded-full px-2 py-0.5 bg-accent/20 text-accent">
            {topic.depth}
          </span>
          {!topic.is_active && (
            <span className="text-xs rounded-full px-2 py-0.5 bg-muted text-muted-foreground">
              inactive
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

function SectionBlock({
  section,
  onAddItem,
  onUpdateItem,
}: {
  section: LearningSection;
  onAddItem: (title: string) => void;
  onUpdateItem: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
}) {
  const [title, setTitle] = useState("");
  return (
    <div className="rounded border border-outline-variant/50 p-3 space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">{section.name}</h3>
      <ul className="space-y-1">
        {section.items.map((item) => (
          <ItemRow key={item.id} item={item} onUpdate={onUpdateItem} />
        ))}
      </ul>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim()) {
            onAddItem(title.trim());
            setTitle("");
          }
        }}
      >
        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="New item"
        />
        <Button type="submit" variant="outline" size="sm" disabled={!title.trim()}>
          Add
        </Button>
      </form>
    </div>
  );
}

function ItemRow({
  item,
  onUpdate,
}: {
  item: LearningItem;
  onUpdate: (
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
        <input
          type="checkbox"
          checked={item.status === "done"}
          onChange={(e) =>
            onUpdate(item.id, { status: e.target.checked ? "done" : "pending" })
          }
          aria-label={`Mark ${item.title} ${item.status === "done" ? "incomplete" : "complete"}`}
        />
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
        </div>
      )}
    </li>
  );
}
