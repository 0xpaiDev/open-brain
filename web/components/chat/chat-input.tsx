"use client";

import { useState, useCallback, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

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
    <div className="border-t border-outline-variant/15 bg-surface-container-lowest">
      {exchangeCount >= EXCHANGE_WARNING && (
        <div className="flex items-center gap-2 px-4 py-2 text-xs text-yellow-700 bg-yellow-50 dark:text-yellow-300 dark:bg-yellow-900/20">
          <span className="material-symbols-outlined text-sm">warning</span>
          You&apos;ve reached {exchangeCount} exchanges. Answers may lose early
          context. Consider resetting.
        </div>
      )}
      <div className="flex items-end gap-2 p-3">
        {/* Left action buttons */}
        <div className="flex items-center gap-1 shrink-0 pb-0.5">
          {/* External context trigger */}
          {onExternalContextChange && (
            <Dialog open={contextOpen} onOpenChange={setContextOpen}>
              <DialogTrigger
                className="relative p-1.5 rounded-lg text-outline hover:text-on-surface-variant hover:bg-surface-container-low transition-colors cursor-pointer"
                title="Attach external context"
              >
                <span className="material-symbols-outlined text-lg">
                  attach_file
                </span>
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
                    className="min-h-32 max-h-60 text-xs bg-surface-container-lowest border-outline-variant/15 text-on-surface resize-y"
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
        </div>

        {/* Textarea */}
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your memories…"
          rows={1}
          disabled={loading}
          className="flex-1 resize-none rounded-xl border border-outline-variant/15 bg-surface-container-low text-on-surface text-sm px-4 py-2.5 outline-none focus:border-primary transition-colors placeholder:text-outline disabled:opacity-50 field-sizing-content max-h-32"
        />

        {/* Right action buttons */}
        <div className="flex items-center gap-1 shrink-0 pb-0.5">
          {exchangeCount > 0 && (
            <span className="text-xs text-outline tabular-nums">
              {exchangeCount}
            </span>
          )}
          {onReset && (
            <button
              onClick={onReset}
              disabled={messagesCount === 0}
              className="p-1.5 rounded-lg text-outline hover:text-on-surface-variant hover:bg-surface-container-low transition-colors disabled:opacity-30 disabled:pointer-events-none"
              title="Reset chat"
            >
              <span className="material-symbols-outlined text-lg">refresh</span>
            </button>
          )}
          <Button
            onClick={handleSend}
            disabled={loading || !input.trim()}
            size="icon"
            className="rounded-xl bg-primary text-on-primary shrink-0"
          >
            <span className="material-symbols-outlined text-lg">send</span>
          </Button>
        </div>
      </div>
    </div>
  );
}
