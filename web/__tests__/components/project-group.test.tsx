import { describe, test, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import type { TodoItem } from "@/lib/types";
import { ProjectGroup } from "@/components/dashboard/project-group";

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: crypto.randomUUID(),
    description: "in-group task",
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

const noopProps = {
  onSelectFocus: vi.fn(),
  onComplete: vi.fn(),
  onDefer: vi.fn(async () => {}),
  onEdit: vi.fn(async () => {}),
  onDelete: vi.fn(async () => {}),
  onAdd: vi.fn(async () => {}),
  onToggleCollapsed: vi.fn(),
  labels: [],
  projects: [],
};

describe("ProjectGroup", () => {
  test("renders header with project name, count, and rows", () => {
    const todos = [
      makeTodo({ id: "g-1", description: "First task", project: "OB" }),
      makeTodo({ id: "g-2", description: "Second task", project: "OB" }),
    ];
    render(
      <ProjectGroup
        {...noopProps}
        name="OB"
        color="#E07060"
        todos={todos}
        totalInProject={2}
        collapsed={false}
        focusId={null}
      />,
    );

    const header = screen.getByLabelText("OB project group");
    expect(within(header).getByText("OB")).toBeDefined();
    expect(within(header).getByText("First task")).toBeDefined();
    expect(within(header).getByText("Second task")).toBeDefined();
  });

  test("collapsed state hides task rows but keeps header visible", () => {
    const todos = [makeTodo({ id: "g-3", description: "Hidden task" })];
    render(
      <ProjectGroup
        {...noopProps}
        name="Health"
        todos={todos}
        totalInProject={1}
        collapsed={true}
        focusId={null}
      />,
    );

    expect(screen.getByText("Health")).toBeDefined();
    expect(screen.queryByText("Hidden task")).toBeNull();
  });

  test("clicking the header invokes onToggleCollapsed", () => {
    const onToggle = vi.fn();
    render(
      <ProjectGroup
        {...noopProps}
        onToggleCollapsed={onToggle}
        name="OB"
        todos={[]}
        totalInProject={0}
        collapsed={false}
        focusId={null}
      />,
    );

    const section = screen.getByLabelText("OB project group");
    // The collapse toggle is the first button inside the header (controls the body via aria-controls).
    const headerBtn = within(section)
      .getAllByRole("button")
      .find((b) => b.getAttribute("aria-controls")?.startsWith("project-group-"));
    expect(headerBtn).toBeDefined();
    fireEvent.click(headerBtn!);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  test("Add to {Project} expands inline composer and submits with the project", async () => {
    const onAdd = vi.fn(async () => {});
    render(
      <ProjectGroup
        {...noopProps}
        onAdd={onAdd}
        name="OB"
        todos={[makeTodo({ project: "OB" })]}
        totalInProject={1}
        collapsed={false}
        focusId={null}
      />,
    );

    fireEvent.click(screen.getByLabelText("Add task to OB"));

    const input = (await screen.findByLabelText("Task description")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Inline task" } });

    fireEvent.click(screen.getByLabelText("Add task"));

    // Wait for promise microtasks to flush
    await new Promise((r) => setTimeout(r, 0));
    expect(onAdd).toHaveBeenCalledWith(
      "Inline task",
      "normal",
      expect.objectContaining({ project: "OB" }),
    );
  });

  test("Personal group's Add row submits with project=null", async () => {
    const onAdd = vi.fn(async () => {});
    render(
      <ProjectGroup
        {...noopProps}
        onAdd={onAdd}
        name="Personal"
        todos={[makeTodo({ project: null })]}
        totalInProject={1}
        collapsed={false}
        focusId={null}
      />,
    );

    fireEvent.click(screen.getByLabelText("Add task to Personal"));
    const input = (await screen.findByLabelText("Task description")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "x" } });
    fireEvent.click(screen.getByLabelText("Add task"));

    await new Promise((r) => setTimeout(r, 0));
    expect(onAdd).toHaveBeenCalledWith(
      "x",
      "normal",
      expect.objectContaining({ project: null }),
    );
  });
});
