"use client";

import { useChat } from "@/hooks/use-chat";
import { ModelSelector } from "@/components/chat/model-selector";
import { ChatThread } from "@/components/chat/chat-thread";
import { ExternalContextPanel } from "@/components/chat/external-context-panel";
import { ChatInput } from "@/components/chat/chat-input";
import { Button } from "@/components/ui/button";

export default function ChatPage() {
  const {
    messages,
    model,
    externalContext,
    loading,
    error,
    exchangeCount,
    sendMessage,
    resetChat,
    setModel,
    setExternalContext,
  } = useChat();

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)]">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-outline-variant/15 bg-surface-container-lowest shrink-0">
        <h1 className="text-lg font-headline font-bold text-on-surface">
          RAG Chat
        </h1>
        <ModelSelector
          model={model}
          onModelChange={setModel}
          disabled={loading}
        />
        <div className="ml-auto">
          <Button
            variant="ghost"
            size="sm"
            onClick={resetChat}
            disabled={messages.length === 0}
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            Reset
          </Button>
        </div>
      </div>

      {/* Thread */}
      <ChatThread messages={messages} loading={loading} error={error} />

      {/* External context + Input */}
      <div className="shrink-0 border-t border-outline-variant/15 bg-surface-container-lowest">
        <div className="px-3 pt-1">
          <ExternalContextPanel
            value={externalContext}
            onChange={setExternalContext}
            disabled={loading}
          />
        </div>
        <ChatInput
          onSend={sendMessage}
          loading={loading}
          exchangeCount={exchangeCount}
        />
      </div>
    </div>
  );
}
