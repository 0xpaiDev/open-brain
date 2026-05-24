"use client";

import { useChat } from "@/hooks/use-chat";
import { ChatThread } from "@/components/chat/chat-thread";
import { ChatInput } from "@/components/chat/chat-input";
import { ToolsToggle } from "@/components/chat/tools-toggle";

export default function ChatPage() {
  const {
    messages,
    toolsEnabled,
    externalContext,
    loading,
    error,
    exchangeCount,
    sendMessage,
    resetChat,
    setToolsEnabled,
    setExternalContext,
  } = useChat();

  return (
    <div className="flex flex-col h-[calc(100dvh-9rem)] md:h-[calc(100dvh-6rem)]">
      {/* Thread */}
      <ChatThread messages={messages} loading={loading} error={error} />

      {/* Input */}
      <div className="shrink-0 flex flex-col gap-1">
        <div className="flex justify-end px-1">
          <ToolsToggle
            enabled={toolsEnabled}
            onToggle={setToolsEnabled}
            disabled={loading}
          />
        </div>
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
