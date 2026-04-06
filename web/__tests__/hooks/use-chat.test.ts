import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useChat, AVAILABLE_MODELS } from "@/hooks/use-chat";
import { setApiKey } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

const MOCK_RESPONSE: ChatResponse = {
  response: "Here are your recent projects.",
  sources: [
    {
      id: "s-1",
      content: "Working on Open Brain",
      summary: "Open Brain project work",
      type: "context",
      importance_score: 0.8,
      combined_score: 0.92,
      project: "open-brain",
    },
  ],
  model: "claude-haiku-4-5-20251001",
  search_query: "recent projects",
};

describe("useChat hook", () => {
  beforeEach(() => {
    setApiKey("test-key");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(MOCK_RESPONSE)));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("initial state is empty", () => {
    const { result } = renderHook(() => useChat());

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.exchangeCount).toBe(0);
    expect(result.current.externalContext).toBe("");
  });

  test("sendMessage adds user + assistant messages", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("What projects have I worked on?");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe(
      "What projects have I worked on?",
    );
    expect(result.current.messages[1].role).toBe("assistant");
    expect(result.current.messages[1].content).toBe(
      "Here are your recent projects.",
    );
    expect(result.current.messages[1].sources).toHaveLength(1);
    expect(result.current.messages[1].searchQuery).toBe("recent projects");
    expect(result.current.exchangeCount).toBe(1);
  });

  test("sendMessage sends correct request body", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MOCK_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test question");
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/v1/chat",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          "Content-Type": "application/json",
          "X-API-Key": "test-key",
        }),
      }),
    );

    const callBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(callBody.message).toBe("test question");
    expect(callBody.history).toEqual([]);
    expect(callBody.model).toBe("claude-haiku-4-5-20251001");
  });

  test("sendMessage includes history from previous messages", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MOCK_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    // First exchange
    await act(async () => {
      await result.current.sendMessage("first question");
    });

    // Second exchange
    await act(async () => {
      await result.current.sendMessage("follow-up question");
    });

    const secondCallBody = JSON.parse(
      fetchMock.mock.calls[1][1]?.body as string,
    );
    expect(secondCallBody.message).toBe("follow-up question");
    expect(secondCallBody.history).toHaveLength(2);
    expect(secondCallBody.history[0]).toEqual({
      role: "user",
      content: "first question",
    });
    expect(secondCallBody.history[1]).toEqual({
      role: "assistant",
      content: "Here are your recent projects.",
    });
  });

  test("sendMessage truncates history to 20 messages", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MOCK_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    // Send 12 messages to get 24 total messages (12 user + 12 assistant)
    for (let i = 0; i < 12; i++) {
      await act(async () => {
        await result.current.sendMessage(`message ${i}`);
      });
    }

    // The 12th call should have history truncated
    const lastCallBody = JSON.parse(
      fetchMock.mock.calls[11][1]?.body as string,
    );
    // History should be at most 20 items (excluding current message)
    expect(lastCallBody.history.length).toBeLessThanOrEqual(20);
  });

  test("resetChat clears messages and external context", async () => {
    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });
    await act(() => {
      result.current.setExternalContext("some context");
    });

    expect(result.current.messages).toHaveLength(2);
    expect(result.current.externalContext).toBe("some context");

    act(() => {
      result.current.resetChat();
    });

    expect(result.current.messages).toHaveLength(0);
    expect(result.current.externalContext).toBe("");
    expect(result.current.error).toBeNull();
    expect(result.current.exchangeCount).toBe(0);
  });

  test("error state on API failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ detail: "error" }, 500)),
    );

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("test");
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBeTruthy();
    // User message should still be visible
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
  });

  test("model persists to localStorage", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.setModel("claude-sonnet-4-6");
    });

    expect(result.current.model).toBe("claude-sonnet-4-6");
    expect(localStorage.getItem("ob_chat_model")).toBe("claude-sonnet-4-6");
  });

  test("model loads from localStorage on mount", () => {
    localStorage.setItem("ob_chat_model", "claude-sonnet-4-6");

    const { result } = renderHook(() => useChat());

    // After useEffect runs
    expect(result.current.model).toBe("claude-sonnet-4-6");
  });

  test("sendMessage ignores empty text", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MOCK_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    await act(async () => {
      await result.current.sendMessage("   ");
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.messages).toHaveLength(0);
  });

  test("sendMessage includes external context when set", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(MOCK_RESPONSE));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.setExternalContext("Meeting notes from today");
    });

    await act(async () => {
      await result.current.sendMessage("What did we discuss?");
    });

    const callBody = JSON.parse(fetchMock.mock.calls[0][1]?.body as string);
    expect(callBody.external_context).toBe("Meeting notes from today");
  });

  test("AVAILABLE_MODELS exports both models", () => {
    expect(AVAILABLE_MODELS).toHaveLength(2);
    expect(AVAILABLE_MODELS[0].value).toBe("claude-haiku-4-5-20251001");
    expect(AVAILABLE_MODELS[1].value).toBe("claude-sonnet-4-6");
  });
});
