import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { CommitmentCreateForm } from "@/components/commitments/commitment-create-form";
import type { CommitmentCreate, CommitmentResponse } from "@/lib/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const TODAY = new Date().toISOString().slice(0, 10);
const TOMORROW = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

function makeResponse(overrides: Partial<CommitmentResponse> = {}): CommitmentResponse {
  return {
    id: "c-1",
    name: "Test",
    exercise: "push-ups",
    daily_target: 20,
    metric: "reps",
    cadence: "daily",
    kind: "single",
    targets: null,
    progress: null,
    pace: null,
    start_date: TODAY,
    end_date: TOMORROW,
    status: "active",
    created_at: TODAY + "T00:00:00Z",
    updated_at: TODAY + "T00:00:00Z",
    current_streak: 0,
    goal_reached: null,
    entries: [],
    exercises: [],
    ...overrides,
  };
}

function fillDailyForm() {
  fireEvent.change(screen.getByPlaceholderText("Challenge name"), {
    target: { value: "Push-up Challenge" },
  });
  fireEvent.change(screen.getByPlaceholderText("Exercise (e.g. push-ups)"), {
    target: { value: "push-ups" },
  });
  fireEvent.change(screen.getByPlaceholderText("Daily target"), {
    target: { value: "20" },
  });
  fireEvent.change(screen.getByLabelText("End date"), {
    target: { value: TOMORROW },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CommitmentCreateForm — daily cadence", () => {
  test("renders daily form fields by default", () => {
    const createCommitment = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    expect(screen.getByPlaceholderText("Challenge name")).toBeTruthy();
    expect(screen.getByPlaceholderText("Exercise (e.g. push-ups)")).toBeTruthy();
    expect(screen.getByPlaceholderText("Daily target")).toBeTruthy();
    // Aggregate field should NOT be visible
    expect(screen.queryByPlaceholderText("Period target")).toBeNull();
  });

  test("submit button is disabled when form is empty", () => {
    const createCommitment = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    const submit = screen.getByText("Create Commitment").closest("button")!;
    expect(submit).toHaveProperty("disabled", true);
  });

  test("submit button enabled after filling required daily fields", () => {
    const createCommitment = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    fillDailyForm();

    const submit = screen.getByText("Create Commitment").closest("button")!;
    expect(submit).toHaveProperty("disabled", false);
  });

  test("calls createCommitment with correct daily payload on submit", async () => {
    const createCommitment = vi.fn().mockResolvedValue(makeResponse());
    const onCreated = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} onCreated={onCreated} />);

    fillDailyForm();
    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    await waitFor(() => {
      expect(createCommitment).toHaveBeenCalledWith(
        expect.objectContaining<Partial<CommitmentCreate>>({
          name: "Push-up Challenge",
          exercise: "push-ups",
          daily_target: 20,
          cadence: "daily",
          end_date: TOMORROW,
        }),
      );
    });
  });

  test("resets fields after successful submit", async () => {
    const createCommitment = vi.fn().mockResolvedValue(makeResponse());
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    fillDailyForm();
    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    await waitFor(() => {
      expect(createCommitment).toHaveBeenCalled();
    });

    expect((screen.getByPlaceholderText("Challenge name") as HTMLInputElement).value).toBe("");
    expect((screen.getByPlaceholderText("Daily target") as HTMLInputElement).value).toBe("");
  });

  test("calls onCreated after successful submit", async () => {
    const createCommitment = vi.fn().mockResolvedValue(makeResponse());
    const onCreated = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} onCreated={onCreated} />);

    fillDailyForm();
    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    await waitFor(() => {
      expect(onCreated).toHaveBeenCalledTimes(1);
    });
  });

  test("does NOT call onCreated if createCommitment returns null", async () => {
    const createCommitment = vi.fn().mockResolvedValue(null);
    const onCreated = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} onCreated={onCreated} />);

    fillDailyForm();
    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    await waitFor(() => {
      expect(createCommitment).toHaveBeenCalled();
    });

    expect(onCreated).not.toHaveBeenCalled();
  });
});

describe("CommitmentCreateForm — aggregate cadence", () => {
  test("switching to Period cadence shows aggregate fields", () => {
    const createCommitment = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    fireEvent.click(screen.getByText("Period"));

    expect(screen.getByPlaceholderText("Period target")).toBeTruthy();
    expect(screen.queryByPlaceholderText("Daily target")).toBeNull();
  });

  test("submit button disabled when aggregate target is empty", () => {
    const createCommitment = vi.fn();
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    fireEvent.click(screen.getByText("Period"));
    fireEvent.change(screen.getByPlaceholderText("Challenge name"), {
      target: { value: "Monthly km" },
    });
    fireEvent.change(screen.getByPlaceholderText("Exercise (e.g. cycling)"), {
      target: { value: "cycling" },
    });
    // No period target set yet
    const submit = screen.getByText("Create Commitment").closest("button")!;
    expect(submit).toHaveProperty("disabled", true);
  });

  test("calls createCommitment with aggregate payload", async () => {
    const createCommitment = vi.fn().mockResolvedValue(makeResponse({ cadence: "aggregate" }));
    render(<CommitmentCreateForm createCommitment={createCommitment} />);

    fireEvent.click(screen.getByText("Period"));
    fireEvent.change(screen.getByPlaceholderText("Challenge name"), {
      target: { value: "200km month" },
    });
    fireEvent.change(screen.getByPlaceholderText("Exercise (e.g. cycling)"), {
      target: { value: "cycling" },
    });
    fireEvent.change(screen.getByPlaceholderText("Period target"), {
      target: { value: "200" },
    });
    fireEvent.change(screen.getByLabelText("End date"), { target: { value: TOMORROW } });

    fireEvent.submit(screen.getByText("Create Commitment").closest("form")!);

    await waitFor(() => {
      expect(createCommitment).toHaveBeenCalledWith(
        expect.objectContaining({
          cadence: "aggregate",
          targets: { km: 200 },
        }),
      );
    });
  });
});
