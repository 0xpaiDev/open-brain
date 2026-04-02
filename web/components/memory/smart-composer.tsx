"use client";

import { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

interface SmartComposerProps {
  onIngest: (
    text: string,
    source?: string,
    metadata?: Record<string, unknown>,
  ) => Promise<boolean>;
}

export function SmartComposer({ onIngest }: SmartComposerProps) {
  const [text, setText] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleTextSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || submitting) return;

    setSubmitting(true);
    const success = await onIngest(
      text.trim(),
      sourceLabel.trim() || "dashboard",
    );
    setSubmitting(false);

    if (success) {
      setText("");
      setSourceLabel("");
    }
  }

  async function handleLinkSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim() || submitting) return;

    setSubmitting(true);
    const success = await onIngest(url.trim(), "web-link", { url: url.trim() });
    setSubmitting(false);

    if (success) {
      setUrl("");
    }
  }

  return (
    <div className="bg-surface-container rounded-2xl p-6 relative overflow-hidden">
      {/* Progress bar */}
      {submitting && (
        <div className="absolute top-0 left-0 right-0 h-1 bg-primary/30">
          <div className="h-full bg-primary animate-pulse w-full" />
        </div>
      )}

      <Tabs defaultValue={0}>
        <TabsList>
          <TabsTrigger value={0}>
            <span className="material-symbols-outlined text-sm mr-1">
              edit_note
            </span>
            Text
          </TabsTrigger>
          <TabsTrigger value={1}>
            <span className="material-symbols-outlined text-sm mr-1">
              link
            </span>
            Link
          </TabsTrigger>
          <TabsTrigger value={2}>
            <span className="material-symbols-outlined text-sm mr-1">
              image
            </span>
            Media
          </TabsTrigger>
        </TabsList>

        {/* Text tab */}
        <TabsContent value={0}>
          <form onSubmit={handleTextSubmit} className="flex flex-col gap-4 pt-4">
            <Textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="What do you want to remember?"
              className="min-h-[120px] bg-surface-container-low border-outline-variant/15 text-on-surface placeholder:text-outline/50 resize-none"
            />
            <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center">
              <Input
                value={sourceLabel}
                onChange={(e) => setSourceLabel(e.target.value)}
                placeholder="Source label (optional)"
                className="flex-1 bg-surface-container-low border-outline-variant/15 text-on-surface placeholder:text-outline/50"
              />
              <button
                type="submit"
                disabled={!text.trim() || submitting}
                className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2.5 px-6 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap"
              >
                <span className="material-symbols-outlined text-sm">
                  neurology
                </span>
                Commit Memory
              </button>
            </div>
          </form>
        </TabsContent>

        {/* Link tab */}
        <TabsContent value={1}>
          <form onSubmit={handleLinkSubmit} className="flex flex-col gap-4 pt-4">
            <Input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://..."
              className="bg-surface-container-low border-outline-variant/15 text-on-surface placeholder:text-outline/50"
            />
            <div className="flex justify-end">
              <button
                type="submit"
                disabled={!url.trim() || submitting}
                className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2.5 px-6 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap"
              >
                <span className="material-symbols-outlined text-sm">link</span>
                Commit Link
              </button>
            </div>
          </form>
        </TabsContent>

        {/* Media tab */}
        <TabsContent value={2}>
          <div className="flex flex-col items-center justify-center py-12 border-2 border-dashed border-outline-variant/20 rounded-xl mt-4 relative">
            <span className="material-symbols-outlined text-4xl text-outline-variant/40 mb-3">
              cloud_upload
            </span>
            <p className="text-sm text-outline font-body">
              Media upload coming soon
            </p>
            <span className="absolute top-3 right-3 text-[10px] font-label font-semibold tracking-wider uppercase px-2 py-0.5 rounded-full bg-tertiary/15 text-tertiary">
              Coming Soon
            </span>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
