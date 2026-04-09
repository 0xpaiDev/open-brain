"use client";

import { useState, useCallback, type KeyboardEvent } from "react";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSend: (text: string) => void;
  loading: boolean;
  exchangeCount: number;
  externalContext?: string;
  onExternalContextChange?: (value: string) => void;
  onReset?: () => void;
  messagesCount?: number;
}

const EXCHANGE_WARNING = 10;
const MAX_CONTEXT_CHARS = 20_000;

export function ChatInput({
  onSend,
  loading,
  exchangeCount,
  externalContext = "",
  onExternalContextChange,
  onReset,
  messagesCount = 0,
}: ChatInputProps) {
  const [input, setInput] = useState("");
  const [contextOpen, setContextOpen] = useState(false);

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || loading) return;
    onSend(text);
    setInput("");
  }, [input, loading, onSend]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <div className="flex flex-col gap-2">
      {exchangeCount >= EXCHANGE_WARNING && (
        <div className="flex items-center gap-2 px-4 py-2 text-xs text-yellow-300 bg-yellow-900/20 rounded-full">
          <span className="material-symbols-outlined text-sm">warning</span>
          {exchangeCount} exchanges — answers may lose early context.
        </div>
      )}

      <div className="rounded-full bg-surface-container-high/80 backdrop-blur-xl p-2 flex items-center gap-2 ring-1 ring-outline-variant/15 transition-all focus-within:ring-primary/40 shadow-lg">
        {/* Attach context */}
        {onExternalContextChange && (
          <Dialog open={contextOpen} onOpenChange={setContextOpen}>
            <DialogTrigger
              className="relative flex items-center justify-center w-10 h-10 rounded-full text-on-surface-variant hover:text-on-surface hover:bg-surface-bright transition-all active:scale-95 shrink-0 cursor-pointer"
              title="Attach external context"
            >
              <span className="material-symbols-outlined">attach_file</span>
              {externalContext && (
                <span className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-primary" />
              )}
            </DialogTrigger>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>External Context</DialogTitle>
              </DialogHeader>
              <div className="space-y-2">
                <Textarea
                  value={externalContext}
                  onChange={(e) =>
                    onExternalContextChange(
                      e.target.value.slice(0, MAX_CONTEXT_CHARS),
                    )
                  }
                  placeholder="Paste meeting notes, documents, or other context here…"
                  className="min-h-32 max-h-60 text-base md:text-xs bg-surface-container-lowest border-outline-variant/15 text-on-surface resize-y"
                  disabled={loading}
                />
                <div className="flex items-center justify-between text-xs text-outline px-1">
                  <span>
                    {externalContext.length.toLocaleString()} /{" "}
                    {MAX_CONTEXT_CHARS.toLocaleString()}
                  </span>
                  {externalContext && (
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => onExternalContextChange("")}
                      disabled={loading}
                    >
                      <span className="material-symbols-outlined text-xs">
                        close
                      </span>
                      Clear
                    </Button>
                  )}
                </div>
              </div>
            </DialogContent>
          </Dialog>
        )}

        {/* Input */}
        <div className="flex-1 min-w-0">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask anything…"
            rows={1}
            disabled={loading}
            className="w-full bg-transparent border-none focus:ring-0 text-on-surface text-base md:text-sm py-2 px-2 outline-none placeholder:text-on-surface-variant/50 disabled:opacity-50 resize-none field-sizing-content max-h-32"
          />
        </div>

        {/* Exchange count + Reset */}
        {onReset && messagesCount > 0 && (
          <div className="flex items-center gap-1 shrink-0">
            {exchangeCount > 0 && (
              <span className="text-xs text-outline tabular-nums">
                {exchangeCount}
              </span>
            )}
            <button
              onClick={onReset}
              className="flex items-center justify-center w-10 h-10 rounded-full text-on-surface-variant hover:text-on-surface hover:bg-surface-bright transition-all active:scale-95"
              title="Reset chat"
            >
              <span className="material-symbols-outlined">refresh</span>
            </button>
          </div>
        )}

        {/* Send */}
        <button
          onClick={handleSend}
          disabled={loading || !input.trim()}
          className="flex items-center justify-center w-10 h-10 rounded-full bg-primary text-on-primary shrink-0 transition-all active:scale-90 shadow-lg disabled:opacity-50 disabled:pointer-events-none"
          aria-label="Send message"
        >
          <span
            className="material-symbols-outlined"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            send
          </span>
        </button>
      </div>
    </div>
  );
}
