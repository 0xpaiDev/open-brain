"use client";

import { useEffect, useRef } from "react";
import type { ChatDisplayMessage } from "@/lib/types";
import { ChatSources } from "./chat-sources";

interface ChatThreadProps {
  messages: ChatDisplayMessage[];
  loading: boolean;
  error: string | null;
}

export function ChatThread({ messages, loading, error }: ChatThreadProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, loading]);

  if (messages.length === 0 && !loading) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center px-4">
        <span className="material-symbols-outlined text-5xl text-outline/30 mb-3">
          chat
        </span>
        <p className="text-on-surface-variant text-sm">
          Ask anything about your memories.
        </p>
        <p className="text-outline text-xs mt-1">
          Your conversation is not saved — it resets when you leave.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto px-2 py-4 space-y-4">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              msg.role === "user"
                ? "bg-primary text-on-primary rounded-br-md"
                : "bg-surface-container-low text-on-surface rounded-bl-md"
            }`}
          >
            {msg.role === "assistant" && msg.searchQuery && (
              <div className="flex items-center gap-1.5 text-xs text-outline mb-2 pb-2 border-b border-outline-variant/15">
                <span className="material-symbols-outlined text-sm">search</span>
                Searched for: &quot;{msg.searchQuery}&quot;
              </div>
            )}
            <div className="whitespace-pre-wrap">{msg.content}</div>
            {msg.role === "assistant" && msg.sources && (
              <div className="mt-3 pt-2 border-t border-outline-variant/15">
                <ChatSources sources={msg.sources} />
              </div>
            )}
          </div>
        </div>
      ))}

      {loading && (
        <div className="flex justify-start">
          <div className="bg-surface-container-low rounded-2xl rounded-bl-md px-4 py-3">
            <div className="flex items-center gap-2 text-sm text-on-surface-variant">
              <span className="material-symbols-outlined text-base animate-spin">
                progress_activity
              </span>
              Thinking…
            </div>
          </div>
        </div>
      )}

      {error && (
        <div className="flex justify-center">
          <div className="bg-error-container text-on-error-container rounded-xl px-4 py-2 text-sm flex items-center gap-2">
            <span className="material-symbols-outlined text-base">error</span>
            {error}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
