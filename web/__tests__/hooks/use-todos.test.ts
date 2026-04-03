import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { sortOpenTodos, filterTodayTodos } from "@/hooks/use-todos";
import { setApiKey, ApiError } from "@/lib/api";
import type { TodoItem, TodoListResponse } from "@/lib/types";

function makeTodo(overrides: Partial<TodoItem> = {}): TodoItem {
  return {
    id: crypto.randomUUID(),
    description: "test",
    priority: "normal",
    status: "open",
    due_date: null,
    start_date: null,
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

// Mock sonner toast — toast is both callable and has methods.
// vi.hoisted() ensures the variable is available when vi.mock hoists.
const { toastFn } = vi.hoisted(() => {
  const fn = Object.assign(vi.fn(), {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
  });
  return { toastFn: fn };
});
vi.mock("sonner", () => ({
  toast: toastFn,
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
  start_date: null,
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

  // ── deferTodo ──────────────────────────────────────────────────────────────

  test("deferTodo updates due_date optimistically", async () => {
    const todo = { ...TODO_A, id: "d-1", due_date: "2026-04-01T00:00:00Z" };
    const newDueDate = "2026-04-15";

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todo], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      // PATCH succeeds
      return jsonResponse({ ...todo, due_date: newDueDate });
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferTodo("d-1", newDueDate);
    });

    expect(result.current.openTodos[0].due_date).toBe(newDueDate);
  });

  test("deferTodo with reason passes reason in PATCH body", async () => {
    const todo = { ...TODO_A, id: "d-2", due_date: "2026-04-01T00:00:00Z" };
    const newDueDate = "2026-04-20";
    const reason = "Waiting on dependencies";
    let patchBody: Record<string, unknown> | null = null;

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todo], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      // Capture PATCH body
      if (init?.method === "PATCH") {
        patchBody = JSON.parse(init.body as string);
        return jsonResponse({ ...todo, due_date: newDueDate });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferTodo("d-2", newDueDate, reason);
    });

    expect(patchBody).not.toBeNull();
    expect(patchBody!.due_date).toBe(newDueDate);
    expect(patchBody!.reason).toBe(reason);
  });

  // ── F6: completeTodo undo toast + undoComplete ─────────────────────────────

  test("completeTodo shows undo toast on success", async () => {
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

    // toast() called directly (not toast.success) with undo action
    expect(toastFn).toHaveBeenCalledWith(
      "Task completed",
      expect.objectContaining({
        action: expect.objectContaining({ label: "Undo" }),
        duration: 5000,
      }),
    );
  });

  test("undoComplete moves task back to open", async () => {
    const doneTodo = { ...TODO_A, id: "undo-1", status: "done" as const };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [doneTodo], total: 1 });
      }
      // PATCH to reopen succeeds
      return jsonResponse({ ...doneTodo, status: "open" });
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.doneTodos).toHaveLength(1);
    expect(result.current.openTodos).toHaveLength(0);

    await act(async () => {
      await result.current.undoComplete("undo-1");
    });

    expect(result.current.openTodos).toHaveLength(1);
    expect(result.current.openTodos[0].status).toBe("open");
    expect(result.current.doneTodos).toHaveLength(0);
  });

  test("undoComplete rollback on API failure", async () => {
    const doneTodo = { ...TODO_A, id: "undo-2", status: "done" as const };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [doneTodo], total: 1 });
      }
      // PATCH fails
      return jsonResponse({}, 500);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.undoComplete("undo-2");
    });

    // Rolled back — todo should be back in done
    expect(result.current.doneTodos).toHaveLength(1);
    expect(result.current.openTodos).toHaveLength(0);
    expect(toastFn.error).toHaveBeenCalledWith("Failed to undo");
  });
});

// ── filterTodayTodos ────────────────────────────────────────────────────────

describe("filterTodayTodos", () => {
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

  test("includes overdue tasks", () => {
    const overdue = makeTodo({ due_date: "2020-01-01T00:00:00Z" });
    const result = filterTodayTodos([overdue]);
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe(overdue.id);
  });

  test("includes tasks due today", () => {
    const dueToday = makeTodo({ due_date: todayISO() });
    const result = filterTodayTodos([dueToday]);
    expect(result).toHaveLength(1);
  });

  test("includes active range tasks (start_date <= today <= due_date)", () => {
    const rangeTask = makeTodo({
      start_date: daysFromNow(-3),
      due_date: daysFromNow(3),
    });
    const result = filterTodayTodos([rangeTask]);
    expect(result).toHaveLength(1);
  });

  test("excludes future tasks", () => {
    const future = makeTodo({ due_date: daysFromNow(7) });
    const result = filterTodayTodos([future]);
    expect(result).toHaveLength(0);
  });

  test("excludes tasks with no dates", () => {
    const noDates = makeTodo({ due_date: null, start_date: null });
    const result = filterTodayTodos([noDates]);
    expect(result).toHaveLength(0);
  });

  test("handles timezone edge cases — date near midnight", () => {
    // Task due at end-of-today in UTC — should still be "today" in local time
    const today = new Date();
    today.setHours(23, 59, 59, 0);
    const dueEndOfToday = makeTodo({ due_date: today.toISOString() });
    const result = filterTodayTodos([dueEndOfToday]);
    expect(result).toHaveLength(1);
  });

  test("excludes future range task not yet started", () => {
    // start_date is tomorrow, due in a week — today is before the range
    const futureRange = makeTodo({
      start_date: daysFromNow(1),
      due_date: daysFromNow(7),
    });
    const result = filterTodayTodos([futureRange]);
    expect(result).toHaveLength(0);
  });

  test("mixed list filters correctly", () => {
    const overdue = makeTodo({ description: "overdue", due_date: "2020-01-01T00:00:00Z" });
    const dueToday = makeTodo({ description: "today", due_date: todayISO() });
    const future = makeTodo({ description: "future", due_date: daysFromNow(7) });
    const noDates = makeTodo({ description: "no dates" });
    const activeRange = makeTodo({
      description: "range",
      start_date: daysFromNow(-1),
      due_date: daysFromNow(1),
    });

    const result = filterTodayTodos([overdue, dueToday, future, noDates, activeRange]);
    expect(result).toHaveLength(3);
    expect(result.map((t) => t.description).sort()).toEqual(["overdue", "range", "today"]);
  });
});
