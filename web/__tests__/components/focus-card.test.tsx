import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import type { TodoItem } from "@/lib/types";
import { FocusCard } from "@/components/dashboard/focus-card";

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

describe("FocusCard", () => {
  test("renders empty state when todo is null", () => {
    render(
      <FocusCard
        todo={null}
        onClear={vi.fn()}
        onComplete={vi.fn()}
      />,
    );
    expect(screen.getByLabelText("No focus selected")).toBeDefined();
    expect(screen.getByText(/no focus selected/i)).toBeDefined();
  });

  test("renders focused todo with project chip and Done/Skip buttons", () => {
    const todo = makeTodo({
      id: "f-1",
      description: "Reply to Anna",
      project: "Personal",
    });
    render(
      <FocusCard
        todo={todo}
        accentColor="#7b8fc7"
        projectLabel="Personal"
        onClear={vi.fn()}
        onComplete={vi.fn()}
      />,
    );

    expect(screen.getByText("Reply to Anna")).toBeDefined();
    expect(screen.getByText("Personal")).toBeDefined();
    expect(screen.getByLabelText(/Mark .* done and clear focus/i)).toBeDefined();
    expect(screen.getByLabelText(/Skip focus/i)).toBeDefined();
  });

  test("Done button calls onComplete with the todo id", () => {
    const onComplete = vi.fn();
    const todo = makeTodo({ id: "f-2" });
    render(
      <FocusCard
        todo={todo}
        onClear={vi.fn()}
        onComplete={onComplete}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Mark .* done and clear focus/i));
    expect(onComplete).toHaveBeenCalledWith("f-2");
  });

  test("Skip button calls onClear and never invokes onComplete", () => {
    const onClear = vi.fn();
    const onComplete = vi.fn();
    const todo = makeTodo({ id: "f-3" });
    render(
      <FocusCard
        todo={todo}
        onClear={onClear}
        onComplete={onComplete}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Skip focus/i));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(onComplete).not.toHaveBeenCalled();
  });

  test("falls back to Personal label when projectLabel is undefined", () => {
    const todo = makeTodo({ project: null });
    render(
      <FocusCard todo={todo} onClear={vi.fn()} onComplete={vi.fn()} />,
    );
    expect(screen.getByText("Personal")).toBeDefined();
  });
});
