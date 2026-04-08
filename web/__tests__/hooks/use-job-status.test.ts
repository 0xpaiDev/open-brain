import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useJobStatus } from "@/hooks/use-job-status";
import type { JobStatusResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const FAKE_JOB_STATUS: JobStatusResponse = {
  jobs: {
    pulse: {
      last_run: "2026-04-08T05:00:00Z",
      last_status: "success",
      duration_seconds: 1.5,
      error: null,
      overdue: false,
      schedule: "daily 05:00 UTC",
    },
    importance: {
      last_run: "2026-04-08T01:00:00Z",
      last_status: "success",
      duration_seconds: 3.2,
      error: null,
      overdue: false,
      schedule: "daily 01:00 UTC",
    },
    synthesis: {
      last_run: "2026-04-06T00:00:00Z",
      last_status: "success",
      duration_seconds: 45.0,
      error: null,
      overdue: false,
      schedule: "weekly Sun 00:00 UTC",
    },
  },
  scheduler: {
    container: "openbrain-scheduler",
    tip: "docker logs openbrain-scheduler --tail=20",
  },
  checked_at: "2026-04-08T12:00:00Z",
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

describe("useJobStatus", () => {
  test("fetches job status on mount", async () => {
    mockFetch(async () => jsonResponse(FAKE_JOB_STATUS));

    const { result } = renderHook(() => useJobStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.jobStatus).toEqual(FAKE_JOB_STATUS);
    expect(result.current.error).toBeNull();
  });

  test("sets error on failure", async () => {
    mockFetch(async () => jsonResponse({}, 500));

    const { result } = renderHook(() => useJobStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.error).toBe("Failed to load job status");
    expect(result.current.jobStatus).toBeNull();
  });

  test("refresh re-fetches", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      return jsonResponse(FAKE_JOB_STATUS);
    });

    const { result } = renderHook(() => useJobStatus());

    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.refresh();
    });

    expect(callCount).toBe(2);
  });
});
