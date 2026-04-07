"use client";

import { useChat } from "@/hooks/use-chat";
import { ChatThread } from "@/components/chat/chat-thread";
import { ChatInput } from "@/components/chat/chat-input";

export default function ChatPage() {
  const {
    messages,
    externalContext,
    loading,
    error,
    exchangeCount,
    sendMessage,
    resetChat,
    setExternalContext,
  } = useChat();

  return (
    <div className="flex flex-col h-[calc(100dvh-7.5rem)] md:h-[calc(100dvh-4rem)]">
      {/* Header */}
      <div className="px-4 py-3 border-b border-outline-variant/15 bg-surface-container-lowest shrink-0">
        <h1 className="text-lg font-headline font-bold text-on-surface">
          RAG Chat
        </h1>
      </div>

      {/* Thread */}
      <ChatThread messages={messages} loading={loading} error={error} />

      {/* Input */}
      <div className="shrink-0">
        <ChatInput
          onSend={sendMessage}
          loading={loading}
          exchangeCount={exchangeCount}
          externalContext={externalContext}
          onExternalContextChange={setExternalContext}
          onReset={resetChat}
          messagesCount={messages.length}
        />
      </div>
    </div>
  );
}
