import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { useCommitments } from "@/hooks/use-commitments";
import type { CommitmentListResponse, CommitmentEntry } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// ── Fixtures ────────────────────────────────────────────────────────────────

const TODAY = new Date().toISOString().slice(0, 10);

const FAKE_ENTRY: CommitmentEntry = {
  id: "e-1",
  commitment_id: "c-1",
  entry_date: TODAY,
  logged_count: 0,
  status: "pending",
  created_at: "2026-04-12T00:00:00Z",
  updated_at: "2026-04-12T00:00:00Z",
};

const FAKE_RESPONSE: CommitmentListResponse = {
  commitments: [
    {
      id: "c-1",
      name: "Push-ups",
      exercise: "push-ups",
      daily_target: 50,
      metric: "reps",
      cadence: "daily",
      kind: "single",
      targets: null,
      progress: null,
      pace: null,
      start_date: TODAY,
      end_date: TODAY,
      status: "active",
      created_at: "2026-04-12T00:00:00Z",
      updated_at: "2026-04-12T00:00:00Z",
      current_streak: 3,
      goal_reached: null,
      entries: [FAKE_ENTRY],
      exercises: [],
    },
  ],
  total: 1,
};

// ── Helpers ─────────────────────────────────────────────────────────────────

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

// ── Tests ───────────────────────────────────────────────────────────────────

describe("useCommitments", () => {
  test("fetches active commitments on mount", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    const { result } = renderHook(() => useCommitments());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.commitments).toHaveLength(1);
    expect(result.current.commitments[0].name).toBe("Push-ups");
  });

  test("empty list when no commitments", async () => {
    mockFetch(async () =>
      jsonResponse({ commitments: [], total: 0 }),
    );

    const { result } = renderHook(() => useCommitments());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.commitments).toHaveLength(0);
  });

  test("logCount sends POST and updates local state", async () => {
    const updatedEntry: CommitmentEntry = {
      ...FAKE_ENTRY,
      logged_count: 10,
      status: "pending",
    };

    let callCount = 0;
    mockFetch(async (path: string, init: RequestInit) => {
      callCount++;
      if (callCount === 1) return jsonResponse(FAKE_RESPONSE);
      // Log call
      return jsonResponse(updatedEntry);
    });

    const { result } = renderHook(() => useCommitments());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logCount("c-1", 10);
    });

    const entry = result.current.commitments[0]?.entries.find(
      (e) => e.entry_date === TODAY,
    );
    expect(entry?.logged_count).toBe(10);
  });

  test("logCount updates streak on hit", async () => {
    const hitEntry: CommitmentEntry = {
      ...FAKE_ENTRY,
      logged_count: 50,
      status: "hit",
    };

    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      if (callCount === 1) return jsonResponse(FAKE_RESPONSE);
      return jsonResponse(hitEntry);
    });

    const { result } = renderHook(() => useCommitments());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.logCount("c-1", 50);
    });

    expect(result.current.commitments[0].current_streak).toBe(4); // was 3 + 1
  });

  test("abandonCommitment removes from list", async () => {
    let callCount = 0;
    mockFetch(async () => {
      callCount++;
      if (callCount === 1) return jsonResponse(FAKE_RESPONSE);
      // Abandon PATCH
      return jsonResponse({ ...FAKE_RESPONSE.commitments[0], status: "abandoned" });
    });

    const { result } = renderHook(() => useCommitments());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.commitments).toHaveLength(1);

    await act(async () => {
      await result.current.abandonCommitment("c-1");
    });

    expect(result.current.commitments).toHaveLength(0);
  });
});
