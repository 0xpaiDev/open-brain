import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, within, fireEvent, waitFor } from "@testing-library/react";
import type { TodoItem } from "@/lib/types";

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: crypto.randomUUID(),
    description: "test task",
    priority: "normal",
    status: "open",
    due_date: null,
    start_date: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function todayISO(): string {
  const d = new Date();
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

function daysFromNow(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() + n);
  d.setHours(12, 0, 0, 0);
  return d.toISOString();
}

// Build a controlled set of todos
const overdueTodo = makeTodo({ id: "t-1", description: "Overdue task", due_date: "2020-06-01T00:00:00Z" });
const todayTodo = makeTodo({ id: "t-2", description: "Today task", due_date: todayISO() });
const futureTodo = makeTodo({ id: "t-3", description: "Future task", due_date: daysFromNow(7) });
const noDueTodo = makeTodo({ id: "t-4", description: "No date task" });

const allOpenTodos = [overdueTodo, todayTodo, futureTodo, noDueTodo];

// Mock useTodos hook
const mockCompleteTodo = vi.fn(async () => {});
const mockAddTodo = vi.fn(async () => {});
const mockDeferTodo = vi.fn(async () => {});

vi.mock("@/hooks/use-todos", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-todos")>();
  return {
    ...actual,
    useTodos: () => ({
      openTodos: allOpenTodos,
      doneTodos: [],
      loading: false,
      error: null,
      completeTodo: mockCompleteTodo,
      addTodo: mockAddTodo,
      deferTodo: mockDeferTodo,
    }),
  };
});

// Mock sonner
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

describe("TaskList tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  test("renders Today and All tabs", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const tabList = screen.getByRole("tablist");
    const tabs = within(tabList).getAllByRole("tab");
    expect(tabs).toHaveLength(2);
    expect(tabs[0].textContent).toContain("Today");
    expect(tabs[1].textContent).toContain("All");
  });

  test("Today tab shows only today's tasks (overdue + due today)", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Default tab is "Today" — the active panel content
    // Find the visible tabpanel
    const activePanel = screen.getByRole("tabpanel");
    expect(within(activePanel).getByText("Overdue task")).toBeDefined();
    expect(within(activePanel).getByText("Today task")).toBeDefined();
    expect(within(activePanel).queryByText("Future task")).toBeNull();
    expect(within(activePanel).queryByText("No date task")).toBeNull();
  });

  test("All tab shows all open tasks", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Click "All" tab
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[1]);

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Future task")).toBeDefined();
      expect(within(panel).getByText("Overdue task")).toBeDefined();
      expect(within(panel).getByText("Today task")).toBeDefined();
      expect(within(panel).getByText("No date task")).toBeDefined();
    });
  });

  test("tab badge counts are correct", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");

    // Today tab badge = 2 (overdue + today)
    expect(tabs[0].textContent).toContain("2");

    // All tab badge = 4
    expect(tabs[1].textContent).toContain("4");
  });

  test("defer button opens dialog", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Find defer buttons (calendar_month icons)
    const deferButtons = screen.getAllByLabelText("Defer task");
    expect(deferButtons.length).toBeGreaterThan(0);

    // Click the first defer button
    fireEvent.click(deferButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Defer Task")).toBeDefined();
    });

    // Dialog should have date input and reason textarea
    expect(screen.getByLabelText("New due date")).toBeDefined();
    expect(screen.getByLabelText("Defer reason")).toBeDefined();
  });

  test("defer dialog submits with date and reason", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Open defer dialog on first task
    const deferButtons = screen.getAllByLabelText("Defer task");
    fireEvent.click(deferButtons[0]);

    await waitFor(() => {
      expect(screen.getByText("Defer Task")).toBeDefined();
    });

    // Fill in date
    const dateInput = screen.getByLabelText("New due date");
    fireEvent.change(dateInput, { target: { value: "2026-05-01" } });

    // Fill in reason
    const reasonInput = screen.getByLabelText("Defer reason");
    fireEvent.change(reasonInput, { target: { value: "Need more info" } });

    // Submit — find the "Defer" button inside the dialog (not the trigger)
    const dialogButtons = screen.getAllByRole("button", { name: "Defer" });
    // The submit button is the one inside the dialog footer
    const submitBtn = dialogButtons.find((btn) => btn.closest("[data-slot='dialog-footer']"));
    expect(submitBtn).toBeDefined();
    fireEvent.click(submitBtn!);

    await waitFor(() => {
      expect(mockDeferTodo).toHaveBeenCalledWith(
        expect.any(String),
        "2026-05-01",
        "Need more info",
      );
    });
  });
});

// ── getDueBadge unit tests ─────────────────────────────────────────────────

describe("getDueBadge", () => {
  test("returns Active for tasks in date range", async () => {
    const { getDueBadge } = await import("@/components/dashboard/task-list");

    const start = new Date();
    start.setDate(start.getDate() - 2);
    const due = new Date();
    due.setDate(due.getDate() + 2);

    const badge = getDueBadge(due.toISOString(), start.toISOString());
    expect(badge).not.toBeNull();
    expect(badge!.label).toBe("Active");
  });

  test("returns Overdue for past due dates", async () => {
    const { getDueBadge } = await import("@/components/dashboard/task-list");
    const badge = getDueBadge("2020-01-01T00:00:00Z");
    expect(badge).not.toBeNull();
    expect(badge!.label).toBe("Overdue");
  });

  test("returns Today for tasks due today", async () => {
    const { getDueBadge } = await import("@/components/dashboard/task-list");
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const badge = getDueBadge(today.toISOString());
    expect(badge).not.toBeNull();
    expect(badge!.label).toBe("Today");
  });

  test("returns null for no due date", async () => {
    const { getDueBadge } = await import("@/components/dashboard/task-list");
    const badge = getDueBadge(null);
    expect(badge).toBeNull();
  });
});

// ── AddTaskForm date range toggle ──────────────────────────────────────────

describe("AddTaskForm date range", () => {
  test("date range toggle shows start and due inputs", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Find the date/range toggle button
    const toggle = screen.getByTitle("Switch to date range");
    expect(toggle.textContent).toContain("Date");

    fireEvent.click(toggle);

    await waitFor(() => {
      expect(screen.getByLabelText("From date")).toBeDefined();
      expect(screen.getByLabelText("Due date")).toBeDefined();
    });
  });
});
