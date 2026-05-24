"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { api } from "@/lib/api";
import type {
  ChatMessage,
  ChatDisplayMessage,
  ChatRequest,
  ChatResponse,
} from "@/lib/types";

const MODEL_STORAGE_KEY = "ob_chat_model";
const TOOLS_STORAGE_KEY = "ob_chat_tools_enabled";
const MAX_HISTORY = 20;

const HAIKU_MODEL = "claude-haiku-4-5-20251001";
const SONNET_MODEL = "claude-sonnet-4-6";

export const AVAILABLE_MODELS = [
  { value: HAIKU_MODEL, label: "Haiku (faster)" },
  { value: SONNET_MODEL, label: "Sonnet (smarter)" },
] as const;

function generateId(): string {
  return crypto.randomUUID();
}

function getStoredModel(): string {
  if (typeof window === "undefined") return HAIKU_MODEL;
  return localStorage.getItem(MODEL_STORAGE_KEY) ?? HAIKU_MODEL;
}

function getStoredToolsEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem(TOOLS_STORAGE_KEY) === "true";
}

interface UseChatReturn {
  messages: ChatDisplayMessage[];
  model: string;
  toolsEnabled: boolean;
  externalContext: string;
  loading: boolean;
  error: string | null;
  exchangeCount: number;
  sendMessage: (text: string) => Promise<void>;
  resetChat: () => void;
  setModel: (model: string) => void;
  setToolsEnabled: (enabled: boolean) => void;
  setExternalContext: (ctx: string) => void;
}

export function useChat(): UseChatReturn {
  const [messages, setMessages] = useState<ChatDisplayMessage[]>([]);
  const [model, setModelState] = useState<string>(HAIKU_MODEL);
  const [toolsEnabled, setToolsEnabledState] = useState<boolean>(false);
  const [externalContext, setExternalContext] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef(false);

  // Load model and tools toggle from localStorage on mount
  useEffect(() => {
    setModelState(getStoredModel());
    setToolsEnabledState(getStoredToolsEnabled());
  }, []);

  const setModel = useCallback((m: string) => {
    setModelState(m);
    if (typeof window !== "undefined") {
      localStorage.setItem(MODEL_STORAGE_KEY, m);
    }
  }, []);

  const setToolsEnabled = useCallback((enabled: boolean) => {
    setToolsEnabledState(enabled);
    if (typeof window !== "undefined") {
      localStorage.setItem(TOOLS_STORAGE_KEY, String(enabled));
    }
  }, []);

  const exchangeCount = messages.filter((m) => m.role === "user").length;

  const sendMessage = useCallback(
    async (text: string) => {
      if (loading || !text.trim()) return;

      setLoading(true);
      setError(null);
      abortRef.current = false;

      const userMsg: ChatDisplayMessage = {
        id: generateId(),
        role: "user",
        content: text.trim(),
      };

      setMessages((prev) => [...prev, userMsg]);

      try {
        // Build history from existing messages (before adding user msg)
        const allMessages = [...messages, userMsg];
        const history: ChatMessage[] = allMessages
          .map((m) => ({ role: m.role, content: m.content }))
          .slice(-MAX_HISTORY);

        const body: ChatRequest = {
          message: text.trim(),
          history: history.slice(0, -1), // exclude current message (it's in `message`)
          model,
          external_context: externalContext || undefined,
          tools_enabled: toolsEnabled,
        };

        const res = await api<ChatResponse>("POST", "/v1/chat", body);

        if (abortRef.current) return;

        const assistantMsg: ChatDisplayMessage = {
          id: generateId(),
          role: "assistant",
          content: res.response,
          sources: res.sources,
          searchQuery: res.search_query,
        };

        setMessages((prev) => [...prev, assistantMsg]);
      } catch (err) {
        if (abortRef.current) return;
        const message =
          err instanceof Error ? err.message : "Failed to send message";
        setError(message);
      } finally {
        if (!abortRef.current) setLoading(false);
      }
    },
    [loading, messages, model, toolsEnabled, externalContext],
  );

  const resetChat = useCallback(() => {
    abortRef.current = true;
    setMessages([]);
    setExternalContext("");
    setError(null);
    setLoading(false);
  }, []);

  return {
    messages,
    model,
    toolsEnabled,
    externalContext,
    loading,
    error,
    exchangeCount,
    sendMessage,
    resetChat,
    setModel,
    setToolsEnabled,
    setExternalContext,
  };
}
