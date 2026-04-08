import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useQueueStatus } from "@/hooks/use-queue-status";
import type { QueueStatusResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const FAKE_STATUS: QueueStatusResponse = {
  pending: 3,
  processing: 1,
  done: 42,
  failed: 2,
  total: 48,
  oldest_locked_at: null,
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

describe("useQueueStatus", () => {
  test("fetches status on mount", async () => {
    mockFetch(async () => jsonResponse(FAKE_STATUS));

    const { result } = renderHook(() => useQueueStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.status).toEqual(FAKE_STATUS);
    expect(result.current.error).toBeNull();
  });

  test("sets error on failure", async () => {
    mockFetch(async () => jsonResponse({}, 500));

    const { result } = renderHook(() => useQueueStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Failed to load pipeline status");
    expect(result.current.status).toBeNull();
  });

  test("refresh re-fetches", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      return jsonResponse(FAKE_STATUS);
    });

    const { result } = renderHook(() => useQueueStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(callCount).toBe(1);

    await act(async () => {
      await result.current.refresh();
    });

    expect(callCount).toBe(2);
  });
});
