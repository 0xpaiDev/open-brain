import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const mockDeferOverdue = vi.fn(async () => {});

let mockOverdueTodos: Array<{
  id: string;
  description: string;
  due_date: string | null;
  priority: string;
  status: string;
  start_date: string | null;
  created_at: string;
  updated_at: string;
}> = [];
let mockLoading = false;

vi.mock("@/hooks/use-overdue", () => ({
  useOverdue: () => ({
    overdueTodos: mockOverdueTodos,
    loading: mockLoading,
    deferOverdue: mockDeferOverdue,
    allHandled: !mockLoading && mockOverdueTodos.length === 0,
  }),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

function makeTodo(id: string, description: string) {
  return {
    id,
    description,
    priority: "normal",
    status: "open",
    due_date: "2020-01-01T00:00:00Z",
    start_date: null,
    created_at: "2020-01-01T00:00:00Z",
    updated_at: "2020-01-01T00:00:00Z",
  };
}

describe("OverdueModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOverdueTodos = [makeTodo("od-1", "Pay bills"), makeTodo("od-2", "File taxes")];
    mockLoading = false;
  });

  test("renders overdue tasks list", async () => {
    const { OverdueModal } = await import("@/components/dashboard/overdue-modal");
    render(<OverdueModal />);

    expect(screen.getByText("Overdue Tasks")).toBeDefined();
    expect(screen.getByText("Pay bills")).toBeDefined();
    expect(screen.getByText("File taxes")).toBeDefined();
  });

  test("requires reason before defer", async () => {
    const { OverdueModal } = await import("@/components/dashboard/overdue-modal");
    render(<OverdueModal />);

    // Get all "Defer" buttons
    const deferButtons = screen.getAllByRole("button", { name: "Defer" });
    // Initially disabled (no date or reason)
    expect(deferButtons[0].hasAttribute("disabled") || (deferButtons[0] as HTMLButtonElement).disabled).toBe(true);

    // Fill in date but not reason
    const dateInputs = screen.getAllByLabelText("New due date");
    fireEvent.change(dateInputs[0], { target: { value: "2026-12-31" } });

    // Fill in reason
    const reasonInputs = screen.getAllByLabelText("Defer reason");
    fireEvent.change(reasonInputs[0], { target: { value: "Will handle next week" } });

    // Wait for React to process the state updates and re-render
    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: "Defer" });
      expect((buttons[0] as HTMLButtonElement).disabled).toBe(false);
    });
  });

  test("defer removes task from modal", async () => {
    const { OverdueModal } = await import("@/components/dashboard/overdue-modal");
    render(<OverdueModal />);

    // Fill in first task's fields
    const dateInputs = screen.getAllByLabelText("New due date");
    fireEvent.change(dateInputs[0], { target: { value: "2026-12-31" } });
    const reasonInputs = screen.getAllByLabelText("Defer reason");
    fireEvent.change(reasonInputs[0], { target: { value: "Rescheduled" } });

    // Wait for button to enable, then click
    await waitFor(() => {
      const buttons = screen.getAllByRole("button", { name: "Defer" });
      expect((buttons[0] as HTMLButtonElement).disabled).toBe(false);
    });

    const deferButtons = screen.getAllByRole("button", { name: "Defer" });
    fireEvent.click(deferButtons[0]);

    await waitFor(() => {
      expect(mockDeferOverdue).toHaveBeenCalledWith("od-1", "2026-12-31", "Rescheduled");
    });
  });

  test("modal closes when all handled", async () => {
    mockOverdueTodos = [];

    const { OverdueModal } = await import("@/components/dashboard/overdue-modal");
    const { container } = render(<OverdueModal />);

    // allHandled = true -> component returns null
    expect(container.innerHTML).toBe("");
  });

  test("modal is non-dismissable (no close button)", async () => {
    const { OverdueModal } = await import("@/components/dashboard/overdue-modal");
    render(<OverdueModal />);

    // The dialog renders with showCloseButton={false}
    // There should be no "Close" sr-only text or X button
    expect(screen.queryByText("Close")).toBeNull();
  });
});
