import { describe, test, expect } from "vitest";
import { sortOpenTodos } from "@/hooks/use-todos";
import type { TodoItem } from "@/lib/types";

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: crypto.randomUUID(),
    description: "test",
    priority: "normal",
    status: "open",
    due_date: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// ── T-24: sortOpenTodos ordering ────────────────────────────────────────────

describe("sortOpenTodos", () => {
  test("sorts high before normal before low", () => {
    const todos = [
      makeTodo({ priority: "low" }),
      makeTodo({ priority: "high" }),
      makeTodo({ priority: "normal" }),
    ];
    const sorted = sortOpenTodos(todos);
    expect(sorted.map((t) => t.priority)).toEqual(["high", "normal", "low"]);
  });

  test("within same priority, due_date earliest first", () => {
    const todos = [
      makeTodo({ due_date: "2026-04-10T00:00:00Z" }),
      makeTodo({ due_date: "2026-04-01T00:00:00Z" }),
    ];
    const sorted = sortOpenTodos(todos);
    expect(sorted[0].due_date).toBe("2026-04-01T00:00:00Z");
    expect(sorted[1].due_date).toBe("2026-04-10T00:00:00Z");
  });

  test("items with due_date sort before items without", () => {
    const todos = [
      makeTodo({ due_date: null }),
      makeTodo({ due_date: "2026-04-01T00:00:00Z" }),
    ];
    const sorted = sortOpenTodos(todos);
    expect(sorted[0].due_date).toBe("2026-04-01T00:00:00Z");
    expect(sorted[1].due_date).toBeNull();
  });

  test("same priority and no due_date sorts by created_at ascending", () => {
    const todos = [
      makeTodo({ created_at: "2026-03-01T00:00:00Z" }),
      makeTodo({ created_at: "2026-01-01T00:00:00Z" }),
      makeTodo({ created_at: "2026-02-01T00:00:00Z" }),
    ];
    const sorted = sortOpenTodos(todos);
    expect(sorted.map((t) => t.created_at)).toEqual([
      "2026-01-01T00:00:00Z",
      "2026-02-01T00:00:00Z",
      "2026-03-01T00:00:00Z",
    ]);
  });

  test("does not mutate the original array", () => {
    const todos = [
      makeTodo({ priority: "low" }),
      makeTodo({ priority: "high" }),
    ];
    const original = [...todos];
    sortOpenTodos(todos);
    expect(todos).toEqual(original);
  });

  test("empty array returns empty array", () => {
    expect(sortOpenTodos([])).toEqual([]);
  });

  test("single item returns unchanged", () => {
    const todo = makeTodo();
    const result = sortOpenTodos([todo]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(todo.id);
  });

  test("full priority + due_date + created_at tiebreaker chain", () => {
    const todos = [
      makeTodo({ priority: "normal", due_date: null, created_at: "2026-03-01T00:00:00Z" }),
      makeTodo({ priority: "high", due_date: "2026-04-10T00:00:00Z" }),
      makeTodo({ priority: "normal", due_date: "2026-04-05T00:00:00Z" }),
      makeTodo({ priority: "normal", due_date: null, created_at: "2026-01-01T00:00:00Z" }),
      makeTodo({ priority: "low" }),
    ];
    const sorted = sortOpenTodos(todos);
    // high first, then normal with due date, then normals by created_at, then low
    expect(sorted[0].priority).toBe("high");
    expect(sorted[1].due_date).toBe("2026-04-05T00:00:00Z");
    expect(sorted[2].created_at).toBe("2026-01-01T00:00:00Z");
    expect(sorted[3].created_at).toBe("2026-03-01T00:00:00Z");
    expect(sorted[4].priority).toBe("low");
  });
});
