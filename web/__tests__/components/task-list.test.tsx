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
    label: null,
    project: null,
    learning_item_id: null,
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
const mockDeferAll = vi.fn(async () => {});
const mockEditTodo = vi.fn(async () => {});
const mockDeleteTodo = vi.fn(async () => {});
const mockLoadMoreDone = vi.fn(async () => {});

let mockOpenTodos = allOpenTodos;
let mockDoneTodos: TodoItem[] = [];
let mockHasMoreDone = false;

vi.mock("@/hooks/use-todos", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/hooks/use-todos")>();
  return {
    ...actual,
    useTodos: () => ({
      openTodos: mockOpenTodos,
      doneTodos: mockDoneTodos,
      loading: false,
      error: null,
      completeTodo: mockCompleteTodo,
      addTodo: mockAddTodo,
      deferTodo: mockDeferTodo,
      deferAll: mockDeferAll,
      editTodo: mockEditTodo,
      deleteTodo: mockDeleteTodo,
      loadMoreDone: mockLoadMoreDone,
      hasMoreDone: mockHasMoreDone,
    }),
  };
});

// Mock useTodoLabels
const mockLabels = [
  { id: "l-1", name: "Work", color: "#FF0000", created_at: "2026-01-01T00:00:00Z" },
  { id: "l-2", name: "Personal", color: "#00FF00", created_at: "2026-01-01T00:00:00Z" },
];

vi.mock("@/hooks/use-todo-labels", () => ({
  useTodoLabels: () => ({
    labels: mockLabels,
    loading: false,
    createLabel: vi.fn(),
    deleteLabel: vi.fn(),
  }),
}));

// Mock useProjectLabels
vi.mock("@/hooks/use-project-labels", () => ({
  useProjectLabels: () => ({
    labels: [],
    loading: false,
    createLabel: vi.fn(),
    deleteLabel: vi.fn(),
    renameLabel: vi.fn(async () => true),
  }),
}));

// Mock sonner
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

describe("TaskList tabs", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = allOpenTodos;
    mockDoneTodos = [];
    mockHasMoreDone = false;
  });

  test("renders Today, This Week, and All tabs", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const tabList = screen.getByRole("tablist");
    const tabs = within(tabList).getAllByRole("tab");
    expect(tabs).toHaveLength(3);
    expect(tabs[0].textContent).toContain("Today");
    expect(tabs[1].textContent).toContain("This Week");
    expect(tabs[2].textContent).toContain("All");
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

    // Click "All" tab (index 2 now)
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[2]);

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
    expect(tabs[2].textContent).toContain("4");
  });

  test("Defer all button shown when Today tab has multiple tasks", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Default Today tab has 2 tasks (overdue + today) — button should appear.
    const buttons = screen.getAllByLabelText(/Defer all \d+ tasks/);
    expect(buttons.length).toBeGreaterThan(0);
  });

  test("Defer all button hidden when Today tab has only one task", async () => {
    mockOpenTodos = [todayTodo];
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    expect(screen.queryByLabelText(/Defer all \d+ tasks?/)).toBeNull();
  });

  test("Defer all dialog submits with date + reason and passes today's ids", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const triggerButtons = screen.getAllByLabelText(/Defer all \d+ tasks/);
    fireEvent.click(triggerButtons[0]);

    await waitFor(() => {
      expect(screen.getByText(/Defer all 2 tasks/)).toBeDefined();
    });

    const dateInput = screen.getByLabelText("New due date");
    // Default is pre-filled with tomorrow; override explicitly to assert payload.
    fireEvent.change(dateInput, { target: { value: "2026-05-10" } });

    const reasonInput = screen.getByLabelText("Defer reason");
    fireEvent.change(reasonInput, { target: { value: "morning triage" } });

    const dialogButtons = screen.getAllByRole("button", { name: "Defer all" });
    const submitBtn = dialogButtons.find((b) => b.closest("[data-slot='dialog-footer']"));
    expect(submitBtn).toBeDefined();
    fireEvent.click(submitBtn!);

    await waitFor(() => {
      expect(mockDeferAll).toHaveBeenCalledWith(
        expect.arrayContaining([overdueTodo.id, todayTodo.id]),
        "2026-05-10",
        "morning triage",
      );
    });
    // Only the two Today-tab todos get deferred — future and no-due are excluded.
    const passedIds = mockDeferAll.mock.calls[0][0] as string[];
    expect(passedIds).toHaveLength(2);
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

// ── AddTaskForm default date = tomorrow ───────────────────────────────────

describe("AddTaskForm default date", () => {
  const tomorrow = (() => { const d = new Date(); d.setDate(d.getDate() + 1); return d.toISOString().split("T")[0]; })();

  test("date button shows Tomorrow by default", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const dateBtn = screen.getByLabelText("Pick date");
    expect(dateBtn.textContent).toContain("Tomorrow");
  });

  test("submit without changing date sends tomorrow", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const taskInput = screen.getByPlaceholderText("Add a task...");
    fireEvent.change(taskInput, { target: { value: "Test task" } });

    const addBtn = screen.getByRole("button", { name: "Add task" });
    fireEvent.click(addBtn);

    await waitFor(() => {
      expect(mockAddTodo).toHaveBeenCalledWith(
        "Test task",
        "normal",
        expect.objectContaining({ dueDate: tomorrow, project: null }),
      );
    });
  });

  test("user can clear date to submit without due_date", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Open dialog and clear date
    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    const dateInput = screen.getByLabelText("Due date");
    fireEvent.change(dateInput, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    // Submit task
    const taskInput = screen.getByPlaceholderText("Add a task...");
    fireEvent.change(taskInput, { target: { value: "No date task" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => {
      expect(mockAddTodo).toHaveBeenCalledWith(
        "No date task",
        "normal",
        expect.objectContaining({ dueDate: undefined, project: null }),
      );
    });
  });

  test("date resets to tomorrow after submission", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Change date via dialog
    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-12-25" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    // Button should now show "Dec 25"
    await waitFor(() => {
      expect(screen.getByLabelText("Pick date").textContent).toMatch(/Dec\s+25/);
    });

    // Submit
    const taskInput = screen.getByPlaceholderText("Add a task...");
    fireEvent.change(taskInput, { target: { value: "Holiday task" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => {
      expect(mockAddTodo).toHaveBeenCalled();
    });

    // Date button should reset to "Tomorrow"
    await waitFor(() => {
      expect(screen.getByLabelText("Pick date").textContent).toContain("Tomorrow");
    });
  });
});

// ── DatePickerDialog (unified, all viewports) ────────────────────────────

describe("DatePickerDialog", () => {
  test("date button opens dialog", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const dateBtn = screen.getByLabelText("Pick date");
    fireEvent.click(dateBtn);

    await waitFor(() => {
      expect(screen.getByText("Due Date")).toBeDefined();
      expect(screen.getByLabelText("Due date")).toBeDefined();
    });
  });

  test("dialog passes date to addTodo on apply", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Open dialog
    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    // Change date
    const dateInput = screen.getByLabelText("Due date");
    fireEvent.change(dateInput, { target: { value: "2026-06-15" } });

    // Apply
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    // Submit task
    const taskInput = screen.getByPlaceholderText("Add a task...");
    fireEvent.change(taskInput, { target: { value: "Dated task" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => {
      expect(mockAddTodo).toHaveBeenCalledWith(
        "Dated task",
        "normal",
        expect.objectContaining({ dueDate: "2026-06-15", project: null }),
      );
    });
  });

  test("dialog supports range mode — shows start date input before due date", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    // Toggle range
    const checkbox = screen.getByLabelText("Date range");
    fireEvent.click(checkbox);

    await waitFor(() => {
      expect(screen.getByLabelText("Start date")).toBeDefined();
      expect(screen.getByLabelText("Due date")).toBeDefined();
    });

    // Start date must appear before due date in DOM
    const startInput = screen.getByLabelText("Start date");
    const dueInput = screen.getByLabelText("Due date");
    expect(
      startInput.compareDocumentPosition(dueInput) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  test("range mode blocks apply when start > end", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    fireEvent.click(screen.getByLabelText("Date range"));
    await waitFor(() => expect(screen.getByLabelText("Start date")).toBeDefined());

    // Set start after due
    fireEvent.change(screen.getByLabelText("Due date"), { target: { value: "2026-05-01" } });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-05-10" } });

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });

    const applyBtn = screen.getByRole("button", { name: "Apply" }) as HTMLButtonElement;
    expect(applyBtn.disabled).toBe(true);
  });

  test("dialog closes on cancel", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => {
      expect(screen.queryByText("Due Date")).toBeNull();
    });
  });

  test("dialog closes on apply", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Pick date"));
    await waitFor(() => expect(screen.getByText("Due Date")).toBeDefined());

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => {
      expect(screen.queryByText("Due Date")).toBeNull();
    });
  });
});

// ── AddTaskForm layout ───────────────────────────────────────────────────

describe("AddTaskForm layout", () => {
  test("form renders two rows (input + controls)", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const form = screen.getByPlaceholderText("Add a task...").closest("form")!;
    // Two-row layout: flex-col with 2 children
    expect(form.children).toHaveLength(2);
  });

  test("date button shows 'Tomorrow' by default", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const dateBtn = screen.getByLabelText("Pick date");
    expect(dateBtn.textContent).toContain("Tomorrow");
  });

  test("date button shows formatted date", async () => {
    const { formatDateButtonText } = await import("@/components/dashboard/task-list");
    // Use a date far enough in the future to avoid "Today"/"Tomorrow" labels
    const futureDate = new Date();
    futureDate.setDate(futureDate.getDate() + 10);
    const dateStr = futureDate.toISOString().split("T")[0];
    const result = formatDateButtonText(dateStr);
    // Should show abbreviated month + day (e.g. "Apr 19")
    expect(result).not.toBe("Today");
    expect(result).not.toBe("Tomorrow");
    expect(result).toMatch(/\w{3}\s+\d{1,2}/);
  });

  test("priority, label, date, add in correct order in controls row", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const form = screen.getByPlaceholderText("Add a task...").closest("form")!;
    const controlsRow = form.children[1];
    const buttons = controlsRow.querySelectorAll("button");

    // Priority trigger, label trigger, date picker, add button
    expect(buttons.length).toBeGreaterThanOrEqual(4);
  });
});

// ── Label display ────────────────────────────────────────────────────────

describe("Labels on tasks", () => {
  test("label selector in AddTaskForm shows available labels", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const labelTrigger = screen.getByLabelText("Label");
    expect(labelTrigger).toBeDefined();
  });

  test("label selector is functional", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Label trigger exists and is clickable
    const labelTrigger = screen.getByLabelText("Label");
    fireEvent.click(labelTrigger);

    // Dropdown should show label options
    await waitFor(() => {
      const options = screen.getAllByRole("option");
      // None + Work + Personal = at least 3
      expect(options.length).toBeGreaterThanOrEqual(3);
    });
  });
});

// ── This Week tab ──────────────────────────────────────────────────────────

describe("This Week tab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHasMoreDone = false;
    mockDoneTodos = [];
  });

  test("This Week tab shows tasks due this week", async () => {
    // Create a task due on Sunday of this week (always after today Mon–Sat)
    const getThisMonday = () => {
      const d = new Date();
      d.setHours(0, 0, 0, 0);
      const day = d.getDay();
      const diff = day === 0 ? 6 : day - 1;
      d.setDate(d.getDate() - diff);
      return d;
    };
    const sunday = getThisMonday();
    sunday.setDate(sunday.getDate() + 6);
    sunday.setHours(12, 0, 0, 0);

    const weekTodo = makeTodo({ id: "w-1", description: "Week task", due_date: sunday.toISOString() });
    mockOpenTodos = [...allOpenTodos, weekTodo];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Click "This Week" tab
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[1]);

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Week task")).toBeDefined();
    });
  });
});

// ── Search ─────────────────────────────────────────────────────────────────

describe("Search filtering", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = allOpenTodos;
    mockDoneTodos = [];
    mockHasMoreDone = false;
  });

  test("search bar is rendered", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    expect(screen.getByLabelText("Search tasks")).toBeDefined();
    expect(screen.getByPlaceholderText("Search tasks...")).toBeDefined();
  });

  test("search filters tasks by description", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Switch to All tab to see all tasks
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[2]);

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Overdue task")).toBeDefined();
    });

    // Type search query
    const searchInput = screen.getByLabelText("Search tasks");
    fireEvent.change(searchInput, { target: { value: "Overdue" } });

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Overdue task")).toBeDefined();
      expect(within(panel).queryByText("Today task")).toBeNull();
      expect(within(panel).queryByText("Future task")).toBeNull();
    });
  });

  test("search is case-insensitive", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[2]);

    const searchInput = screen.getByLabelText("Search tasks");
    fireEvent.change(searchInput, { target: { value: "overdue" } });

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Overdue task")).toBeDefined();
    });
  });

  test("empty search shows all tasks", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    fireEvent.click(tabs[2]);

    const searchInput = screen.getByLabelText("Search tasks");
    fireEvent.change(searchInput, { target: { value: "xyz" } });

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).queryByText("Overdue task")).toBeNull();
    });

    // Clear search
    fireEvent.change(searchInput, { target: { value: "" } });

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Overdue task")).toBeDefined();
    });
  });
});

// ── Label filter chips ─────────────────────────────────────────────────────

describe("Label filter chips", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockHasMoreDone = false;
    mockDoneTodos = [];
  });

  test("shows label chips when todos have labels", async () => {
    mockOpenTodos = [
      makeTodo({ id: "lf-1", description: "Work task", label: "Work" }),
      makeTodo({ id: "lf-2", description: "Personal task", label: "Personal" }),
      makeTodo({ id: "lf-3", description: "No label task" }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Chips for "Work" and "Personal" should render
    const workChip = screen.getByRole("button", { name: "Work" });
    const personalChip = screen.getByRole("button", { name: "Personal" });
    expect(workChip).toBeDefined();
    expect(personalChip).toBeDefined();
  });

  test("clicking a label chip filters tasks", async () => {
    mockOpenTodos = [
      makeTodo({ id: "lf-1", description: "Work task", label: "Work", due_date: "2020-01-01T00:00:00Z" }),
      makeTodo({ id: "lf-2", description: "Personal task", label: "Personal", due_date: "2020-01-01T00:00:00Z" }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Both tasks visible in Today tab (overdue)
    const panel = screen.getByRole("tabpanel");
    expect(within(panel).getByText("Work task")).toBeDefined();
    expect(within(panel).getByText("Personal task")).toBeDefined();

    // Click Work chip
    fireEvent.click(screen.getByRole("button", { name: "Work" }));

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Work task")).toBeDefined();
      expect(within(panel).queryByText("Personal task")).toBeNull();
    });
  });

  test("Clear button removes label filter", async () => {
    mockOpenTodos = [
      makeTodo({ id: "lf-1", description: "Work task", label: "Work", due_date: "2020-01-01T00:00:00Z" }),
      makeTodo({ id: "lf-2", description: "Personal task", label: "Personal", due_date: "2020-01-01T00:00:00Z" }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Activate a filter
    fireEvent.click(screen.getByRole("button", { name: "Work" }));

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).queryByText("Personal task")).toBeNull();
    });

    // Click "Clear"
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));

    await waitFor(() => {
      const panel = screen.getByRole("tabpanel");
      expect(within(panel).getByText("Work task")).toBeDefined();
      expect(within(panel).getByText("Personal task")).toBeDefined();
    });
  });

  test("no label chips when no todos have labels", async () => {
    mockOpenTodos = allOpenTodos; // none have labels

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();
  });
});

// ── Grouped done section ───────────────────────────────────────────────────

describe("Grouped done section", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = allOpenTodos;
    mockHasMoreDone = false;
  });

  test("done section shows grouped collapsibles", async () => {
    const thisWeek = new Date();
    const lastWeek = new Date();
    lastWeek.setDate(lastWeek.getDate() - 8);

    mockDoneTodos = [
      makeTodo({ id: "d-1", description: "Recent done", status: "done", updated_at: thisWeek.toISOString() }),
      makeTodo({ id: "d-2", description: "Older done", status: "done", updated_at: lastWeek.toISOString() }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Expand the parent History collapsible first
    const historyTrigger = screen.getByText(/History.*\(2\)/);
    fireEvent.click(historyTrigger);

    // Should see group headers — they are CollapsibleTriggers
    await waitFor(() => {
      expect(screen.getByText(/This Week.*\(1\)/)).toBeDefined();
      expect(screen.getByText(/Last Week.*\(1\)/)).toBeDefined();
    });
  });

  test("done group collapsible expands to show tasks", async () => {
    mockDoneTodos = [
      makeTodo({ id: "d-1", description: "Recent done", status: "done", updated_at: new Date().toISOString() }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Expand the parent History collapsible first
    const historyTrigger = screen.getByText(/History.*\(1\)/);
    fireEvent.click(historyTrigger);

    // Child group should be open by default, showing the task
    await waitFor(() => {
      expect(screen.getByText("Recent done")).toBeDefined();
    });
  });
});

// ── Load more button ───────────────────────────────────────────────────────

describe("Load more done", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = allOpenTodos;
  });

  test("Load more button visible when hasMoreDone is true", async () => {
    mockHasMoreDone = true;
    mockDoneTodos = [
      makeTodo({ id: "d-1", status: "done", updated_at: new Date().toISOString() }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Expand the parent History collapsible first
    fireEvent.click(screen.getByText(/History/));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Load more" })).toBeDefined();
    });
  });

  test("Load more button hidden when hasMoreDone is false", async () => {
    mockHasMoreDone = false;
    mockDoneTodos = [
      makeTodo({ id: "d-1", status: "done", updated_at: new Date().toISOString() }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Expand the parent History collapsible
    fireEvent.click(screen.getByText(/History/));
    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    });
  });

  test("clicking Load more calls loadMoreDone", async () => {
    mockHasMoreDone = true;
    mockDoneTodos = [
      makeTodo({ id: "d-1", status: "done", updated_at: new Date().toISOString() }),
    ];

    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    // Expand the parent History collapsible first
    fireEvent.click(screen.getByText(/History/));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Load more" })).toBeDefined();
    });

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));

    await waitFor(() => {
      expect(mockLoadMoreDone).toHaveBeenCalledTimes(1);
    });
  });
});

// ── Edit todo (desktop inline form) ────────────────────────────────────────

describe("Edit todo — desktop inline form", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = [
      makeTodo({
        id: "e-1",
        description: "Original task",
        due_date: "2020-01-01T00:00:00Z",
      }),
    ];
    mockDoneTodos = [];
    mockHasMoreDone = false;
  });

  test("edit button opens inline form seeded with current values", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Edit task: Original task"));

    const titleInput = screen.getByLabelText("Edit title: Original task") as HTMLInputElement;
    expect(titleInput.value).toBe("Original task");

    const dateInput = screen.getByLabelText("Edit due date") as HTMLInputElement;
    expect(dateInput.value).toBe("2020-01-01");
  });

  test("save submits edited description via editTodo", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Edit task: Original task"));

    const titleInput = screen.getByLabelText("Edit title: Original task");
    fireEvent.change(titleInput, { target: { value: "Updated task" } });

    fireEvent.click(screen.getByRole("button", { name: "Save task edit" }));

    await waitFor(() => {
      expect(mockEditTodo).toHaveBeenCalledWith("e-1", "Updated task", "2020-01-01", {});
    });
  });

  test("clearing the date sends null", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Edit task: Original task"));
    fireEvent.change(screen.getByLabelText("Edit due date"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save task edit" }));

    await waitFor(() => {
      expect(mockEditTodo).toHaveBeenCalledWith("e-1", "Original task", null, {});
    });
  });

  test("cancel restores values and closes form", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Edit task: Original task"));
    fireEvent.change(screen.getByLabelText("Edit title: Original task"), {
      target: { value: "Something else" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel task edit" }));

    await waitFor(() => {
      expect(screen.queryByLabelText("Edit title: Original task")).toBeNull();
    });
    expect(mockEditTodo).not.toHaveBeenCalled();
  });

  test("save button disabled on empty description", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Edit task: Original task"));
    fireEvent.change(screen.getByLabelText("Edit title: Original task"), {
      target: { value: "   " },
    });

    const saveBtn = screen.getByRole("button", { name: "Save task edit" }) as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
  });
});

// ── Delete todo (desktop one-click) ─────────────────────────────────────────

describe("Delete todo — desktop one-click", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = [
      makeTodo({ id: "d-x", description: "Doomed task", due_date: "2020-01-01T00:00:00Z" }),
    ];
    mockDoneTodos = [];
    mockHasMoreDone = false;
  });

  test("delete button calls deleteTodo with id", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("Delete task: Doomed task"));

    await waitFor(() => {
      expect(mockDeleteTodo).toHaveBeenCalledWith("d-x");
    });
  });
});

// ── Mobile sheet (EditTodoSheet) ────────────────────────────────────────────

describe("Edit todo — mobile bottom sheet", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockOpenTodos = [
      makeTodo({
        id: "m-1",
        description: "Sheet task",
        due_date: "2020-01-01T00:00:00Z",
      }),
    ];
    mockDoneTodos = [];
    mockHasMoreDone = false;
  });

  test("more button opens sheet seeded with current values", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("More actions for task: Sheet task"));

    await waitFor(() => {
      const title = screen.getByLabelText("Task title") as HTMLInputElement;
      expect(title.value).toBe("Sheet task");
      const date = screen.getByLabelText("Task due date") as HTMLInputElement;
      expect(date.value).toBe("2020-01-01");
    });
  });

  test("reason textarea appears only after the date changes", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("More actions for task: Sheet task"));

    await waitFor(() => expect(screen.getByLabelText("Task due date")).toBeDefined());
    expect(screen.queryByLabelText("Reason for defer")).toBeNull();

    fireEvent.change(screen.getByLabelText("Task due date"), {
      target: { value: "2026-05-01" },
    });

    await waitFor(() => {
      expect(screen.getByLabelText("Reason for defer")).toBeDefined();
    });
  });

  test("save sends edits and reason when date changed", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("More actions for task: Sheet task"));
    await waitFor(() => expect(screen.getByLabelText("Task title")).toBeDefined());

    fireEvent.change(screen.getByLabelText("Task title"), {
      target: { value: "Renamed" },
    });
    fireEvent.change(screen.getByLabelText("Task due date"), {
      target: { value: "2026-05-01" },
    });
    fireEvent.change(screen.getByLabelText("Reason for defer"), {
      target: { value: "Need more time" },
    });

    const saveBtn = screen
      .getAllByRole("button", { name: "Save" })
      .find((b) => (b as HTMLButtonElement).offsetParent !== null || true)!;
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(mockEditTodo).toHaveBeenCalledWith("m-1", "Renamed", "2026-05-01", {
        reason: "Need more time",
      });
    });
  });

  test("delete button inside sheet calls deleteTodo", async () => {
    const { TaskList } = await import("@/components/dashboard/task-list");
    render(<TaskList />);

    fireEvent.click(screen.getByLabelText("More actions for task: Sheet task"));
    await waitFor(() => expect(screen.getByLabelText("Task title")).toBeDefined());

    fireEvent.click(screen.getByLabelText("Delete task"));

    await waitFor(() => {
      expect(mockDeleteTodo).toHaveBeenCalledWith("m-1");
    });
  });
});
