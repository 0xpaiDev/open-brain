import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { sortOpenTodos } from "@/hooks/use-todos";
import { setApiKey, ApiError } from "@/lib/api";
import type { TodoItem, TodoListResponse } from "@/lib/types";

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

// ── useTodos hook tests ─────────────────────────────────────────────────────

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const TODO_A: TodoItem = {
  id: "a-1",
  description: "Buy groceries",
  priority: "normal",
  status: "open",
  due_date: null,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

describe("useTodos hook", () => {
  beforeEach(() => {
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── T-36: completeTodo optimistic update + rollback on error ────────────

  test("completeTodo rolls back on PATCH failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      // PATCH fails
      return jsonResponse({}, 500);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.openTodos).toHaveLength(1);

    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    // After rollback, todo should be back in open list
    expect(result.current.openTodos).toHaveLength(1);
    expect(result.current.openTodos[0].id).toBe("a-1");
    expect(result.current.doneTodos).toHaveLength(0);
  });

  test("completeTodo moves todo to done on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      // PATCH succeeds
      return jsonResponse({ ...TODO_A, status: "done" });
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    expect(result.current.openTodos).toHaveLength(0);
    expect(result.current.doneTodos).toHaveLength(1);
    expect(result.current.doneTodos[0].status).toBe("done");
  });

  // ── T-37: addTodo inserts and re-sorts ──────────────────────────────────

  test("addTodo inserts new todo in sorted position", async () => {
    const newTodo: TodoItem = {
      id: "new-1",
      description: "Urgent task",
      priority: "high",
      status: "open",
      due_date: null,
      created_at: "2026-04-03T00:00:00Z",
      updated_at: "2026-04-03T00:00:00Z",
    };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      // POST returns new todo
      return jsonResponse(newTodo, 201);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.openTodos).toHaveLength(1);

    await act(async () => {
      await result.current.addTodo("Urgent task", "high");
    });

    expect(result.current.openTodos).toHaveLength(2);
    // High priority should sort first
    expect(result.current.openTodos[0].priority).toBe("high");
    expect(result.current.openTodos[0].id).toBe("new-1");
  });
});
