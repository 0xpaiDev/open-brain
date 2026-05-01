import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import type { TodoItem } from "@/lib/types";
import { FocusCard } from "@/components/dashboard/focus-card";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: crypto.randomUUID(),
    description: "test focus task",
    priority: "normal",
    status: "open",
    due_date: null,
    start_date: null,
    label: null,
    project: null,
    learning_item_id: null,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-01T00:00:00Z",
    ...overrides,
  };
}

function renderCard(todo: TodoItem | null, overrides: Partial<Parameters<typeof FocusCard>[0]> = {}) {
  const onClear = vi.fn();
  const onComplete = vi.fn();
  const onDefer = vi.fn(async () => {});
  const onDelete = vi.fn(async () => {});
  render(
    <FocusCard
      todo={todo}
      onClear={onClear}
      onComplete={onComplete}
      onDefer={onDefer}
      onDelete={onDelete}
      {...overrides}
    />,
  );
  return { onClear, onComplete, onDefer, onDelete };
}

describe("FocusCard", () => {
  test("renders empty state when todo is null", () => {
    renderCard(null);
    expect(screen.getByLabelText("No focus selected")).toBeDefined();
    expect(screen.getByText(/no focus selected/i)).toBeDefined();
  });

  test("renders Done, Defer, and Delete buttons; no Skip button", () => {
    const todo = makeTodo({ id: "f-1", description: "Reply to Anna", project: "Personal" });
    renderCard(todo, { projectLabel: "Personal" });

    expect(screen.getByLabelText(/Mark .* done and clear focus/i)).toBeDefined();
    expect(screen.getByLabelText(/Defer focus todo/i)).toBeDefined();
    expect(screen.getByLabelText(/Delete .* permanently/i)).toBeDefined();
    expect(screen.queryByLabelText(/Skip focus/i)).toBeNull();
  });

  test("Done button calls onComplete with the todo id", () => {
    const todo = makeTodo({ id: "f-2" });
    const { onComplete } = renderCard(todo);
    fireEvent.click(screen.getByLabelText(/Mark .* done and clear focus/i));
    expect(onComplete).toHaveBeenCalledWith("f-2");
  });

  test("Delete button calls confirm then onDelete", async () => {
    const todo = makeTodo({ id: "f-3", description: "Doomed task" });
    const { onDelete } = renderCard(todo);
    vi.stubGlobal("confirm", () => true);
    fireEvent.click(screen.getByLabelText(/Delete .* permanently/i));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("f-3"));
    vi.unstubAllGlobals();
  });

  test("Delete button does nothing when confirm is cancelled", async () => {
    const todo = makeTodo({ id: "f-4", description: "Kept task" });
    const { onDelete } = renderCard(todo);
    vi.stubGlobal("confirm", () => false);
    fireEvent.click(screen.getByLabelText(/Delete .* permanently/i));
    await waitFor(() => expect(onDelete).not.toHaveBeenCalled());
    vi.unstubAllGlobals();
  });

  test("Defer button opens dialog with date input", async () => {
    const todo = makeTodo({ id: "f-5" });
    renderCard(todo);
    fireEvent.click(screen.getByLabelText(/Defer focus todo/i));
    await waitFor(() => {
      expect(screen.getByText("Defer Task")).toBeDefined();
      expect(screen.getByLabelText("New due date")).toBeDefined();
    });
  });

  test("Defer dialog calls onDefer on submit", async () => {
    const todo = makeTodo({ id: "f-6" });
    const { onDefer } = renderCard(todo);
    fireEvent.click(screen.getByLabelText(/Defer focus todo/i));
    await waitFor(() => expect(screen.getByLabelText("New due date")).toBeDefined());

    fireEvent.change(screen.getByLabelText("New due date"), { target: { value: "2026-06-01" } });

    const deferBtns = screen.getAllByRole("button", { name: "Defer" });
    const submitBtn = deferBtns.find((b) => b.closest("[data-slot='dialog-footer']"));
    expect(submitBtn).toBeDefined();
    fireEvent.click(submitBtn!);

    await waitFor(() => {
      expect(onDefer).toHaveBeenCalledWith("f-6", "2026-06-01", undefined);
    });
  });

  test("project badge renders to the right of the title (after in DOM order)", () => {
    const todo = makeTodo({ description: "Layout test" });
    renderCard(todo, { projectLabel: "Work" });

    const card = screen.getByLabelText("Focused task");
    const header = card.firstElementChild!;
    const titleEl = header.querySelector("p")!;
    const badgeCluster = header.lastElementChild!;

    // title should come before badge cluster in DOM
    expect(
      titleEl.compareDocumentPosition(badgeCluster) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(badgeCluster.textContent).toContain("Work");
  });

  test("falls back to Personal label when projectLabel is undefined", () => {
    const todo = makeTodo({ project: null });
    renderCard(todo);
    expect(screen.getByText("Personal")).toBeDefined();
  });

  test("renders date range badge without 'Invalid Date'", () => {
    const todo = makeTodo({
      due_date: "2026-05-09",
      start_date: "2026-05-05",
    });
    renderCard(todo);
    const card = screen.getByLabelText("Focused task");
    expect(card.textContent).not.toContain("Invalid Date");
    // Should contain a dash between two dates
    expect(card.textContent).toMatch(/May\s+\d+\s+–\s+May\s+\d+/);
  });
});
