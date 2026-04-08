import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useDeadLetters } from "@/hooks/use-dead-letters";
import type { DeadLetterListResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const FAKE_DEAD_LETTERS: DeadLetterListResponse = {
  items: [
    {
      id: "dl-1",
      raw_id: "raw-1",
      queue_id: "q-1",
      error_reason: "extraction failed",
      attempt_count: 3,
      last_output: "partial output here",
      retry_count: 0,
      created_at: "2026-04-08T05:00:00Z",
      resolved_at: null,
    },
  ],
  total: 1,
};

function mockFetch(handler: (path: string, init: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(handler));
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => {
  setApiKey("test-key");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useDeadLetters", () => {
  test("fetches unresolved by default", async () => {
    const calls: string[] = [];
    mockFetch(async (path: string) => {
      calls.push(path);
      return jsonResponse(FAKE_DEAD_LETTERS);
    });

    const { result } = renderHook(() => useDeadLetters(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items).toHaveLength(1);
    expect(result.current.total).toBe(1);
    expect(calls[0]).toContain("resolved=false");
  });

  test("resolved filter changes URL", async () => {
    const calls: string[] = [];
    mockFetch(async (path: string) => {
      calls.push(path);
      return jsonResponse({ items: [], total: 0 });
    });

    const { result } = renderHook(() => useDeadLetters(true));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(calls[0]).toContain("resolved=true");
  });

  test("sets error on failure", async () => {
    mockFetch(async () => jsonResponse({}, 500));

    const { result } = renderHook(() => useDeadLetters(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Failed to load dead letters");
  });

  test("loadMore appends items", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      if (callCount === 1) {
        return jsonResponse({ ...FAKE_DEAD_LETTERS, total: 2 });
      }
      return jsonResponse({
        items: [{ ...FAKE_DEAD_LETTERS.items[0], id: "dl-2" }],
        total: 2,
      });
    });

    const { result } = renderHook(() => useDeadLetters(false));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.hasMore).toBe(true);

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.items).toHaveLength(2);
  });

  test("refresh re-fetches", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      return jsonResponse(FAKE_DEAD_LETTERS);
    });

    const { result } = renderHook(() => useDeadLetters(false));

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(callCount).toBe(2);
  });
});
