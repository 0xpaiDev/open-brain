"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button, buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { ProgressRing } from "@/components/ui/progress-ring";
import { SectionBlock } from "../../_components/section-block";
import { useLearning } from "@/hooks/use-learning";
import { cn } from "@/lib/utils";
import type { LearningMaterial } from "@/lib/types";

export default function TopicDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const {
    topics,
    loading,
    toggleTopicActive,
    createSection,
    deleteSection,
    createItem,
    updateItem,
    deleteItem,
    getMaterial,
    saveMaterial,
    deleteMaterial,
  } = useLearning();

  const topic = topics.find((t) => t.id === id);

  const [material, setMaterial] = useState<LearningMaterial | null>(null);
  const [materialLoading, setMaterialLoading] = useState(true);
  const [editMode, setEditMode] = useState(false);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getMaterial(id).then((m) => {
      if (!cancelled) {
        setMaterial(m);
        setMaterialLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, [id, getMaterial]);

  const handleSave = async () => {
    setSaving(true);
    const result = await saveMaterial(id, { content: editContent });
    if (result) {
      setMaterial(result);
      setEditMode(false);
    }
    setSaving(false);
  };

  const handleDelete = async () => {
    if (!confirm("Delete this material? This cannot be undone.")) return;
    await deleteMaterial(id);
    setMaterial(null);
    setEditMode(false);
  };

  const allItems = topic?.sections.flatMap((s) => s.items) ?? [];
  const totalItems = allItems.length;
  const doneItems = allItems.filter((i) => i.status === "done").length;
  const topicPct = totalItems === 0 ? 0 : doneItems / totalItems;

  const recentFeedback = topic?.sections
    .flatMap((s) => s.items)
    .filter((item) => item.feedback)
    .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
    .slice(0, 5);

  if (loading) {
    return (
      <div className="py-8">
        <p className="text-sm text-on-surface-variant">Loading…</p>
      </div>
    );
  }

  if (!topic) {
    return (
      <div className="py-8 space-y-4">
        <Link href="/learning" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "gap-1")}>
          ← Library
        </Link>
        <p className="text-sm text-red-500">Topic not found.</p>
      </div>
    );
  }

  return (
    <div className="py-6 md:py-8 space-y-5">
      {/* Header */}
      <div className="space-y-3">
        <Link href="/learning" className={cn(buttonVariants({ variant: "ghost", size: "sm" }), "gap-1 -ml-2")}>
          ← Library
        </Link>

        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-start gap-3">
            <ProgressRing size={38} strokeWidth={3} pct={topicPct} className="mt-1" />
            <div>
              <h1 className="text-2xl font-headline font-bold">{topic.name}</h1>
              <p className="text-[12px] text-on-surface-variant mt-0.5">
                {topic.sections.length} section{topic.sections.length !== 1 ? "s" : ""} · {doneItems}/{totalItems} items
                {topic.depth && (
                  <> · <span className="capitalize">{topic.depth}</span></>
                )}
              </p>
              {topic.description && (
                <p className="text-sm text-on-surface-variant mt-1">{topic.description}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2 py-2 -my-2">
            <span className={cn(
              "text-[12px] font-medium",
              topic.is_active ? "text-streak-hit" : "text-on-surface-variant",
            )}>
              {topic.is_active ? "Active" : "Inactive"}
            </span>
            <Switch
              checked={topic.is_active}
              onCheckedChange={(active) => toggleTopicActive(topic.id, active)}
              aria-label="Toggle topic active"
            />
          </div>
        </div>
      </div>

      {/* Material panel */}
      <section className="rounded-[14px] border border-border bg-surface-container p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Material</h2>
          {!editMode && (
            <div className="flex gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setEditContent(material?.content ?? "");
                  setEditMode(true);
                }}
              >
                {material ? "Edit" : "Add"}
              </Button>
              {material && (
                <Button variant="outline" size="sm" onClick={handleDelete}>
                  Delete
                </Button>
              )}
            </div>
          )}
        </div>

        {materialLoading ? (
          <p className="text-sm text-on-surface-variant">Loading material…</p>
        ) : editMode ? (
          <div className="space-y-2">
            <Textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              placeholder="Write material in Markdown…"
              className="font-mono text-base md:text-sm min-h-[200px]"
            />
            <div className="flex gap-2">
              <Button onClick={handleSave} disabled={saving || !editContent.trim()}>
                {saving ? "Saving…" : "Save"}
              </Button>
              <Button variant="outline" onClick={() => setEditMode(false)} disabled={saving}>
                Cancel
              </Button>
            </div>
          </div>
        ) : material ? (
          <div className="max-h-[60vh] overflow-y-auto prose prose-sm dark:prose-invert">
            {/* react-markdown v9 escapes raw HTML by default; do NOT add rehype-raw */}
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{material.content}</ReactMarkdown>
          </div>
        ) : (
          <p className="text-sm text-on-surface-variant">No material yet. Click Add to create one.</p>
        )}

        {material?.source_title && !editMode && (
          <p className="text-xs text-on-surface-variant">
            Source: {material.source_title}
            {material.source_url && /^https?:\/\//.test(material.source_url) && (
              <>
                {" "}
                <a
                  href={material.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline hover:text-primary"
                >
                  ↗
                </a>
              </>
            )}
          </p>
        )}
      </section>

      {/* Sections — interactive (editable mode) */}
      {topic.sections.length > 0 && (
        <section className="rounded-[14px] border border-border bg-surface-container p-4 space-y-3">
          <h2 className="text-base font-semibold">Content</h2>
          <div className="space-y-2">
            {topic.sections.map((section) => (
              <SectionBlock
                key={section.id}
                section={section}
                onAddItem={(title) => createItem(section.id, title)}
                onUpdateItem={updateItem}
                onDeleteItem={deleteItem}
                onDeleteSection={deleteSection}
                editable
              />
            ))}
          </div>
          {/* Add section inline */}
          <AddSectionInline onAdd={(name) => createSection(topic.id, name)} />
        </section>
      )}

      {/* Recent feedback */}
      {recentFeedback && recentFeedback.length > 0 && (
        <section className="rounded-[14px] border border-border bg-surface-container p-4 space-y-2">
          <h2 className="text-base font-semibold">Recent Feedback</h2>
          <ul className="space-y-1.5">
            {recentFeedback.map((item) => (
              <li key={item.id} className="text-sm flex gap-2">
                <span className="shrink-0 text-[10px] font-bold text-on-surface-variant bg-surface-container-high rounded px-1 py-0.5 mt-0.5">F</span>
                <span>
                  <span className="font-medium">{item.title}</span>
                  {" — "}
                  <span className="text-on-surface-variant italic">{item.feedback}</span>
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function AddSectionInline({ onAdd }: { onAdd: (name: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");

  function submit() {
    const trimmed = name.trim();
    if (!trimmed) return;
    onAdd(trimmed);
    setName("");
    setAdding(false);
  }

  if (!adding) {
    return (
      <button
        type="button"
        onClick={() => setAdding(true)}
        className="w-full py-2 rounded-lg border border-dashed border-border text-[12px] text-on-surface-variant hover:text-primary hover:border-primary transition-colors"
      >
        + Add section
      </button>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => { if (!name.trim()) setAdding(false); }}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") { setName(""); setAdding(false); }
        }}
        placeholder="Section name…"
        className="flex-1 bg-surface-container-high rounded px-2 py-1 text-base md:text-sm outline-none focus:ring-1 ring-primary"
      />
      <button
        type="button"
        onClick={submit}
        disabled={!name.trim()}
        className="text-xs text-primary font-semibold disabled:opacity-40 hover:opacity-75 transition-opacity"
      >
        Add
      </button>
    </div>
  );
}
