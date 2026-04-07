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
    <div className="flex flex-col h-[calc(100dvh-9rem)] md:h-[calc(100dvh-6rem)]">
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
