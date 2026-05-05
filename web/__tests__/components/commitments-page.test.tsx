import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CommitmentsPage from "@/app/commitments/page";
import type { CommitmentResponse, CommitmentListResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// Mock Next.js Link so it renders as a plain anchor in jsdom
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Mock next/navigation (used by sidebar/other layout deps if imported transitively)
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/commitments",
  useSearchParams: () => new URLSearchParams(),
}));

const TODAY = new Date().toISOString().slice(0, 10);
const YESTERDAY = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

function makeCommitment(overrides: Partial<CommitmentResponse>): CommitmentResponse {
  return {
    id: "c-1",
    name: "Test commitment",
    exercise: "push-ups",
    daily_target: 20,
    metric: "reps",
    cadence: "daily",
    kind: "single",
    targets: null,
    progress: null,
    pace: null,
    start_date: YESTERDAY,
    end_date: TODAY,
    status: "active",
    created_at: YESTERDAY + "T00:00:00Z",
    updated_at: TODAY + "T00:00:00Z",
    current_streak: 0,
    goal_reached: null,
    entries: [],
    exercises: [],
    ...overrides,
  };
}

const ACTIVE_DAILY = makeCommitment({ id: "c-active", name: "Push-up Challenge" });
const COMPLETED_REACHED = makeCommitment({
  id: "c-done",
  name: "Finished Goal",
  status: "completed",
  goal_reached: true,
  end_date: YESTERDAY,
});
const COMPLETED_MISSED = makeCommitment({
  id: "c-missed",
  name: "Missed Goal",
  status: "completed",
  goal_reached: false,
  end_date: YESTERDAY,
});
const ABANDONED = makeCommitment({
  id: "c-abandoned",
  name: "Abandoned One",
  status: "abandoned",
  end_date: YESTERDAY,
});

function mockFetch(response: CommitmentListResponse) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => response,
    }),
  );
}

beforeEach(() => {
  setApiKey("test-key");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CommitmentsPage", () => {
  test("renders page heading", async () => {
    mockFetch({ commitments: [], total: 0 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /commitments/i, level: 1 })).toBeTruthy();
    });
  });

  test("shows loading skeletons while fetching", () => {
    // Never resolves — stays loading
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    render(<CommitmentsPage />);

    const skeletons = document.querySelectorAll(".animate-pulse");
    expect(skeletons.length).toBeGreaterThan(0);
  });

  test("renders active commitments", async () => {
    mockFetch({ commitments: [ACTIVE_DAILY], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Push-up Challenge")).toBeTruthy();
    });
  });

  test("shows empty state when no active commitments", async () => {
    mockFetch({ commitments: [], total: 0 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText(/no active commitments/i)).toBeTruthy();
    });
  });

  test("renders history section with completed and abandoned commitments", async () => {
    mockFetch({
      commitments: [ACTIVE_DAILY, COMPLETED_REACHED, ABANDONED],
      total: 3,
    });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Finished Goal")).toBeTruthy();
      expect(screen.getByText("Abandoned One")).toBeTruthy();
    });
  });

  test("history shows 'not reached' badge for completed with goal_reached=false", async () => {
    mockFetch({ commitments: [COMPLETED_MISSED], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("not reached")).toBeTruthy();
    });
  });

  test("history shows 'reached' badge for completed with goal_reached=true", async () => {
    mockFetch({ commitments: [COMPLETED_REACHED], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("reached")).toBeTruthy();
    });
  });

  test("history shows 'abandoned' badge for abandoned commitments", async () => {
    mockFetch({ commitments: [ABANDONED], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("abandoned")).toBeTruthy();
    });
  });

  test("shows empty history state when no non-active commitments", async () => {
    mockFetch({ commitments: [ACTIVE_DAILY], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Push-up Challenge")).toBeTruthy();
    });
    expect(screen.getByText(/no completed commitments yet/i)).toBeTruthy();
  });

  test("clicking New button reveals the create form", async () => {
    mockFetch({ commitments: [], total: 0 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText(/no active commitments/i)).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: /new/i }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Challenge name")).toBeTruthy();
    });
  });

  test("Import plan link points to /commitments/import", async () => {
    mockFetch({ commitments: [], total: 0 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText(/import plan/i)).toBeTruthy();
    });

    const importLink = screen.getByText(/import plan/i).closest("a");
    expect(importLink?.getAttribute("href")).toBe("/commitments/import");
  });

  test("each active card has a detail link to /commitments/[id]", async () => {
    mockFetch({ commitments: [ACTIVE_DAILY], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Push-up Challenge")).toBeTruthy();
    });

    const detailLink = document.querySelector(`a[href="/commitments/c-active"]`);
    expect(detailLink).toBeTruthy();
  });

  test("each history row links to /commitments/[id]", async () => {
    mockFetch({ commitments: [COMPLETED_REACHED], total: 1 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Finished Goal")).toBeTruthy();
    });

    const detailLink = document.querySelector(`a[href="/commitments/c-done"]`);
    expect(detailLink).toBeTruthy();
  });

  test("history is sorted by end_date descending (newest first)", async () => {
    const TWO_DAYS_AGO = new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10);
    const older = makeCommitment({
      id: "c-older",
      name: "Older Goal",
      status: "completed",
      goal_reached: true,
      end_date: TWO_DAYS_AGO,
    });
    const newer = makeCommitment({
      id: "c-newer",
      name: "Newer Goal",
      status: "completed",
      goal_reached: true,
      end_date: YESTERDAY,
    });
    // Pass older first to prove the sort is actually applied
    mockFetch({ commitments: [older, newer], total: 2 });
    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Newer Goal")).toBeTruthy();
    });

    const historyItems = document.querySelectorAll("ul li");
    expect(historyItems[0].textContent).toContain("Newer Goal");
    expect(historyItems[1].textContent).toContain("Older Goal");
  });

  test("form closes after successful commitment creation", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ commitments: [], total: 0 }) })
      .mockResolvedValueOnce({
        ok: true,
        status: 201,
        json: async () => makeCommitment({ id: "c-new", name: "Brand New" }),
      })
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({ commitments: [], total: 0 }) });
    vi.stubGlobal("fetch", fetchMock);

    render(<CommitmentsPage />);

    await waitFor(() => expect(screen.getByText(/no active commitments/i)).toBeTruthy());

    // Open the form
    fireEvent.click(screen.getByRole("button", { name: /new/i }));
    await waitFor(() => expect(screen.getByPlaceholderText("Challenge name")).toBeTruthy());

    // Fill required fields
    fireEvent.change(screen.getByPlaceholderText("Challenge name"), { target: { value: "Brand New" } });
    fireEvent.change(screen.getByPlaceholderText("Exercise (e.g. push-ups)"), { target: { value: "push-ups" } });
    fireEvent.change(screen.getByPlaceholderText("Daily target"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("End date"), {
      target: { value: new Date(Date.now() + 86400000).toISOString().slice(0, 10) },
    });

    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    // After success the form should collapse (input disappears)
    await waitFor(() => {
      expect(screen.queryByPlaceholderText("Challenge name")).toBeNull();
    });
  });
});
