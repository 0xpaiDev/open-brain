"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SectionBlock } from "../../_components/section-block";
import { useLearning } from "@/hooks/use-learning";
import type { LearningMaterial } from "@/lib/types";

export default function TopicDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { topics, loading, toggleTopicActive, getMaterial, saveMaterial, deleteMaterial } =
    useLearning();

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
        <Link
          href="/learning"
          className="text-sm text-on-surface-variant hover:text-primary transition-colors"
        >
          ← Library
        </Link>
        <p className="text-sm text-red-500">Topic not found.</p>
      </div>
    );
  }

  return (
    <div className="py-8 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <Link
            href="/learning"
            className="text-sm text-on-surface-variant hover:text-primary transition-colors"
          >
            ← Library
          </Link>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-2xl font-headline font-bold">{topic.name}</h1>
            <span className="text-xs rounded-full px-2 py-0.5 bg-accent/20 text-accent">
              {topic.depth}
            </span>
            {!topic.is_active && (
              <span className="text-xs rounded-full px-2 py-0.5 bg-muted text-muted-foreground">
                inactive
              </span>
            )}
          </div>
          {topic.description && (
            <p className="text-sm text-on-surface-variant">{topic.description}</p>
          )}
        </div>
        <label className="text-sm flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={topic.is_active}
            onChange={(e) => toggleTopicActive(topic.id, e.target.checked)}
          />
          Active
        </label>
      </div>

      {/* Material panel */}
      <section className="rounded-lg border border-outline-variant bg-surface-container p-4 space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-base font-semibold">Material</h2>
          {!editMode && (
            <div className="flex gap-2">
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
              <Button
                variant="outline"
                onClick={() => setEditMode(false)}
                disabled={saving}
              >
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

      {/* Sections (read-only) */}
      {topic.sections.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-base font-semibold">Content</h2>
          <div className="space-y-2">
            {topic.sections.map((section) => (
              <SectionBlock key={section.id} section={section} />
            ))}
          </div>
        </section>
      )}

      {/* Recent feedback */}
      {recentFeedback && recentFeedback.length > 0 && (
        <section className="rounded-lg border border-outline-variant bg-surface-container p-4 space-y-2">
          <h2 className="text-base font-semibold">Recent Feedback</h2>
          <ul className="space-y-1">
            {recentFeedback.map((item) => (
              <li key={item.id} className="text-sm">
                <span className="font-medium">{item.title}</span>
                {" — "}
                <span className="text-on-surface-variant italic">{item.feedback}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
