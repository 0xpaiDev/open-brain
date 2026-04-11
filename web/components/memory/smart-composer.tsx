"use client";

import { useState, useEffect, useRef } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { useProjectLabels } from "@/hooks/use-project-labels";
import { useSpeechRecognition } from "@/hooks/use-speech-recognition";
import { toast } from "sonner";
import type { VoiceCommandResponse } from "@/lib/types";

interface SmartComposerProps {
  onIngest: (
    text: string,
    source?: string,
    metadata?: Record<string, unknown>,
  ) => Promise<boolean>;
  onVoiceCommand: (transcript: string) => Promise<VoiceCommandResponse | null>;
}

export function SmartComposer({ onIngest, onVoiceCommand }: SmartComposerProps) {
  const [text, setText] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [selectedProject, setSelectedProject] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { labels: projectLabels } = useProjectLabels();
  const {
    isSupported: speechSupported,
    isListening,
    transcript,
    interimTranscript,
    error: speechError,
    startListening,
    stopListening,
    resetTranscript,
  } = useSpeechRecognition();

  // Elapsed timer while listening
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    if (isListening) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [isListening]);

  function formatElapsed(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  }

  async function handleVoiceSubmit() {
    if (!transcript.trim() || submitting) return;
    setSubmitting(true);
    const result = await onVoiceCommand(transcript.trim());
    setSubmitting(false);

    if (result === null) {
      toast.error("Failed to process voice command");
      return;
    }

    switch (result.action) {
      case "created":
      case "completed":
      case "memory":
        toast.success(result.message);
        resetTranscript();
        break;
      case "ambiguous":
        toast.warning(result.message);
        // Keep transcript — user may want to rephrase and retry
        break;
    }
  }

  async function handleTextSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || submitting) return;

    setSubmitting(true);
    const metadata: Record<string, unknown> | undefined = selectedProject
      ? { project: selectedProject }
      : undefined;
    const success = await onIngest(
      text.trim(),
      sourceLabel.trim() || "dashboard",
      metadata,
    );
    setSubmitting(false);

    if (success) {
      setText("");
      setSourceLabel("");
      // Keep selectedProject — user likely wants to keep ingesting to the same project
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
        <TabsList className="h-10 rounded-xl p-1">
          <TabsTrigger value={0} className="rounded-lg px-4 py-1.5 gap-2">
            <span className="material-symbols-outlined text-lg">edit_note</span>
            Text
          </TabsTrigger>
          <TabsTrigger value={1} className="rounded-lg px-4 py-1.5 gap-2">
            <span className="material-symbols-outlined text-lg">image</span>
            Media
          </TabsTrigger>
          <TabsTrigger value={2} className="rounded-lg px-4 py-1.5 gap-2">
            <span className="material-symbols-outlined text-lg">mic</span>
            Voice
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
              {projectLabels.length > 0 && (
                <select
                  value={selectedProject}
                  onChange={(e) => setSelectedProject(e.target.value)}
                  className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
                >
                  <option value="">No project</option>
                  {projectLabels.map((p) => (
                    <option key={p.id} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              )}
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

        {/* Media tab */}
        <TabsContent value={1}>
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

        {/* Voice tab */}
        <TabsContent value={2}>
          <div className="flex flex-col items-center pt-4 gap-4">
            {!speechSupported ? (
              <div className="flex flex-col items-center justify-center py-12 border-2 border-dashed border-outline-variant/20 rounded-xl w-full">
                <span className="material-symbols-outlined text-4xl text-outline-variant/40 mb-3">
                  mic_off
                </span>
                <p className="text-sm text-outline font-body text-center">
                  Voice input requires Chrome or Edge.
                </p>
              </div>
            ) : (
              <>
                {/* Mic button */}
                <div className="relative">
                  {isListening && (
                    <span className="absolute inset-0 rounded-full bg-primary/30 animate-ping" />
                  )}
                  <button
                    type="button"
                    onClick={isListening ? stopListening : startListening}
                    className={`relative w-16 h-16 rounded-full flex items-center justify-center transition-all active:scale-95 ${
                      isListening
                        ? "bg-error text-on-error shadow-lg shadow-error/30"
                        : "bg-gradient-to-r from-primary to-primary-container text-on-primary hover:shadow-[0_0_20px_rgba(173,198,255,0.3)]"
                    }`}
                    aria-label={isListening ? "Stop recording" : "Start recording"}
                  >
                    <span className="material-symbols-outlined text-2xl">
                      {isListening ? "stop" : "mic"}
                    </span>
                  </button>
                </div>

                {/* Timer */}
                {isListening && (
                  <span className="text-xs text-outline font-mono tabular-nums">
                    {formatElapsed(elapsed)}
                  </span>
                )}

                {/* Error */}
                {speechError && (
                  <p className="text-xs text-error text-center">{speechError}</p>
                )}

                {/* Live transcript */}
                {(transcript || interimTranscript) && (
                  <div className="w-full bg-surface-container-low rounded-xl p-4 text-sm text-on-surface min-h-[80px] max-h-[200px] overflow-y-auto">
                    {transcript}
                    {interimTranscript && (
                      <span className="text-outline/50 italic">
                        {interimTranscript}
                      </span>
                    )}
                  </div>
                )}

                {/* Actions */}
                {transcript.trim() && !isListening && (
                  <div className="flex gap-3 w-full justify-end">
                    <button
                      type="button"
                      onClick={resetTranscript}
                      className="text-sm text-outline hover:text-on-surface transition-colors py-2 px-4 rounded-xl"
                    >
                      Clear
                    </button>
                    <button
                      type="button"
                      onClick={handleVoiceSubmit}
                      disabled={submitting}
                      className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2.5 px-6 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap"
                    >
                      <span className="material-symbols-outlined text-sm">
                        neurology
                      </span>
                      Commit Memory
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
