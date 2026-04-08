import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useJobHistory } from "@/hooks/use-job-history";
import type { JobHistoryResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const FAKE_ITEMS: JobHistoryResponse = {
  items: [
    {
      id: "r-1",
      job_name: "pulse",
      started_at: "2026-04-08T05:00:00Z",
      finished_at: "2026-04-08T05:00:02Z",
      status: "success",
      error_message: null,
      duration_seconds: 2.0,
      created_at: "2026-04-08T05:00:00Z",
    },
    {
      id: "r-2",
      job_name: "synthesis",
      started_at: "2026-04-07T00:00:00Z",
      finished_at: "2026-04-07T00:01:30Z",
      status: "failed",
      error_message: "RuntimeError: boom",
      duration_seconds: 90.0,
      created_at: "2026-04-07T00:00:00Z",
    },
  ],
  total: 2,
};

const MORE_ITEMS: JobHistoryResponse = {
  items: [
    {
      id: "r-3",
      job_name: "importance",
      started_at: "2026-04-06T01:00:00Z",
      finished_at: "2026-04-06T01:00:05Z",
      status: "success",
      error_message: null,
      duration_seconds: 5.0,
      created_at: "2026-04-06T01:00:00Z",
    },
  ],
  total: 3,
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

describe("useJobHistory", () => {
  test("fetches items on mount", async () => {
    mockFetch(async () => jsonResponse(FAKE_ITEMS));

    const { result } = renderHook(() => useJobHistory(null, null));

    expect(result.current.loading).toBe(true);

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items).toHaveLength(2);
    expect(result.current.total).toBe(2);
    expect(result.current.error).toBeNull();
  });

  test("sets error on failure", async () => {
    mockFetch(async () => jsonResponse({}, 500));

    const { result } = renderHook(() => useJobHistory(null, null));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Failed to load job history");
    expect(result.current.items).toHaveLength(0);
  });

  test("loadMore appends items", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      return jsonResponse(callCount === 1 ? { ...FAKE_ITEMS, total: 3 } : MORE_ITEMS);
    });

    const { result } = renderHook(() => useJobHistory(null, null));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(2);
    expect(result.current.hasMore).toBe(true);

    await act(async () => {
      await result.current.loadMore();
    });

    expect(result.current.items).toHaveLength(3);
  });

  test("filter change refetches", async () => {
    const calls: string[] = [];
    mockFetch(async (path: string) => {
      calls.push(path);
      return jsonResponse(FAKE_ITEMS);
    });

    const { result, rerender } = renderHook(
      ({ jobName, status }: { jobName: string | null; status: string | null }) =>
        useJobHistory(jobName, status),
      { initialProps: { jobName: null, status: null } },
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    rerender({ jobName: "pulse", status: null });

    await waitFor(() => expect(result.current.loading).toBe(false));

    const filteredCall = calls.find((c) => c.includes("job_name=pulse"));
    expect(filteredCall).toBeDefined();
  });

  test("refresh resets and refetches", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      return jsonResponse(FAKE_ITEMS);
    });

    const { result } = renderHook(() => useJobHistory(null, null));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(callCount).toBe(1);

    await act(async () => {
      await result.current.refresh();
    });

    expect(callCount).toBe(2);
  });
});
