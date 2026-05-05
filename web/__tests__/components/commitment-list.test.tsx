import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CommitmentList } from "@/components/dashboard/commitment-list";
import type { CommitmentListResponse, CommitmentEntry } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const TODAY = new Date().toISOString().slice(0, 10);
const YESTERDAY = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

const ENTRY_HIT: CommitmentEntry = {
  id: "e-0",
  commitment_id: "c-1",
  entry_date: YESTERDAY,
  logged_count: 50,
  status: "hit",
  created_at: "2026-04-11T00:00:00Z",
  updated_at: "2026-04-11T00:00:00Z",
};

const ENTRY_PENDING: CommitmentEntry = {
  id: "e-1",
  commitment_id: "c-1",
  entry_date: TODAY,
  logged_count: 20,
  status: "pending",
  created_at: "2026-04-12T00:00:00Z",
  updated_at: "2026-04-12T00:00:00Z",
};

const FAKE_RESPONSE: CommitmentListResponse = {
  commitments: [
    {
      id: "c-1",
      name: "Push-ups Challenge",
      exercise: "push-ups",
      daily_target: 50,
      metric: "reps",
      cadence: "daily",
      kind: "single",
      targets: null,
      progress: null,
      pace: null,
      start_date: YESTERDAY,
      end_date: TODAY,
      status: "active",
      created_at: "2026-04-11T00:00:00Z",
      updated_at: "2026-04-12T00:00:00Z",
      current_streak: 1,
      goal_reached: null,
      entries: [ENTRY_HIT, ENTRY_PENDING],
      exercises: [],
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

describe("CommitmentList", () => {
  test("renders active commitments with cards", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("Commitments")).toBeTruthy();
    });
    expect(screen.getByText("Push-ups Challenge")).toBeTruthy();
  });

  test("renders nothing when no commitments", async () => {
    mockFetch(async () => jsonResponse({ commitments: [], total: 0 }));

    const { container } = render(<CommitmentList />);

    await waitFor(() => {
      // Loading skeleton should disappear, and no content rendered
      expect(container.querySelector(".animate-pulse")).toBeNull();
    });

    // Should not render the header
    expect(screen.queryByText("Commitments")).toBeNull();
  });

  test("shows today's progress", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText(/Today: 20\/50 reps/)).toBeTruthy();
    });
  });

  test("shows streak count", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("1-day")).toBeTruthy();
    });
  });

  test("renders log buttons for pending entry", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("+5")).toBeTruthy();
      expect(screen.getByText("+10")).toBeTruthy();
      expect(screen.getByText("+25")).toBeTruthy();
    });
  });

  test("clicking log button calls API", async () => {
    const updatedEntry = { ...ENTRY_PENDING, logged_count: 30 };

    let callCount = 0;
    const fetchSpy = vi.fn(async () => {
      callCount++;
      if (callCount === 1) return jsonResponse(FAKE_RESPONSE);
      return jsonResponse(updatedEntry);
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("+10")).toBeTruthy();
    });

    fireEvent.click(screen.getByText("+10"));

    await waitFor(() => {
      // Second call should be the log POST
      expect(fetchSpy).toHaveBeenCalledTimes(2);
    });
  });

  test("streak dots have correct colors", async () => {
    mockFetch(async () => jsonResponse(FAKE_RESPONSE));

    const { container } = render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("Push-ups Challenge")).toBeTruthy();
    });

    // Hit dot should have bg-streak-hit class
    const dots = container.querySelectorAll("span.rounded-full.w-2.h-2");
    expect(dots.length).toBe(2); // yesterday + today
    expect(dots[0].className).toContain("bg-streak-hit"); // yesterday = hit
    expect(dots[1].className).toContain("bg-streak-pending"); // today = pending
  });
});

// ── Aggregate commitment card tests ─────────────────────────────────────────

const AGGREGATE_RESPONSE: CommitmentListResponse = {
  commitments: [
    {
      id: "c-agg",
      name: "200km this month",
      exercise: "cycling",
      daily_target: 0,
      metric: "reps",
      cadence: "aggregate",
      kind: "single",
      targets: { km: 200 },
      progress: { km: 120 },
      pace: { km: 1.15, overall: 1.15 },
      start_date: YESTERDAY,
      end_date: new Date(Date.now() + 86400000 * 28).toISOString().slice(0, 10),
      status: "active",
      created_at: "2026-04-11T00:00:00Z",
      updated_at: "2026-04-12T00:00:00Z",
      current_streak: 0,
      goal_reached: null,
      entries: [],
      exercises: [],
    },
  ],
  total: 1,
};

describe("AggregateCommitmentCard", () => {
  test("renders aggregate commitment with progress", async () => {
    mockFetch(async () => jsonResponse(AGGREGATE_RESPONSE));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("200km this month")).toBeTruthy();
    });
    // Should show progress, not daily log buttons
    expect(screen.getByText(/120.*\/.*200.*km/)).toBeTruthy();
    // Should NOT show log buttons
    expect(screen.queryByText("+5")).toBeNull();
    expect(screen.queryByText("+10")).toBeNull();
  });

  test("renders pace indicator with correct color for ahead", async () => {
    mockFetch(async () => jsonResponse(AGGREGATE_RESPONSE));

    const { container } = render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("200km this month")).toBeTruthy();
    });

    // Pace badge should be green (ahead of pace ≥ 1.0)
    const paceBadge = screen.getByText(/ahead/i);
    expect(paceBadge).toBeTruthy();
  });

  test("renders pace indicator amber when behind", async () => {
    const behindResponse = {
      ...AGGREGATE_RESPONSE,
      commitments: [
        {
          ...AGGREGATE_RESPONSE.commitments[0],
          progress: { km: 50 },
          pace: { km: 0.85, overall: 0.85 },
        },
      ],
    };
    mockFetch(async () => jsonResponse(behindResponse));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("200km this month")).toBeTruthy();
    });

    const paceBadge = screen.getByText(/behind/i);
    expect(paceBadge).toBeTruthy();
  });

  test("does not render streak dots for aggregate", async () => {
    mockFetch(async () => jsonResponse(AGGREGATE_RESPONSE));

    const { container } = render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("200km this month")).toBeTruthy();
    });

    // No streak dots (w-2 h-2 circles)
    const dots = container.querySelectorAll("span.rounded-full.w-2.h-2");
    expect(dots.length).toBe(0);
  });

  test("renders both daily and aggregate cards", async () => {
    const mixedResponse: CommitmentListResponse = {
      commitments: [
        FAKE_RESPONSE.commitments[0], // daily
        AGGREGATE_RESPONSE.commitments[0], // aggregate
      ],
      total: 2,
    };
    mockFetch(async () => jsonResponse(mixedResponse));

    render(<CommitmentList />);

    await waitFor(() => {
      expect(screen.getByText("Push-ups Challenge")).toBeTruthy();
      expect(screen.getByText("200km this month")).toBeTruthy();
    });
  });
});
