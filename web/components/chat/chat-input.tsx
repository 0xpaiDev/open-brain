"use client";

import { useState, useCallback, type KeyboardEvent } from "react";
import { Button } from "@/components/ui/button";

interface ChatInputProps {
  onSend: (text: string) => void;
  loading: boolean;
  exchangeCount: number;
}

const EXCHANGE_WARNING = 10;

export function ChatInput({ onSend, loading, exchangeCount }: ChatInputProps) {
  const [input, setInput] = useState("");

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
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your memories…"
          rows={1}
          disabled={loading}
          className="flex-1 resize-none rounded-xl border border-outline-variant/15 bg-surface-container-low text-on-surface text-sm px-4 py-2.5 outline-none focus:border-primary transition-colors placeholder:text-outline disabled:opacity-50 field-sizing-content max-h-32"
        />
        <div className="flex items-center gap-2">
          {exchangeCount > 0 && (
            <span className="text-xs text-outline tabular-nums">
              {exchangeCount}
            </span>
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
