import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { sortOpenTodos, filterTodayTodos, filterThisWeekTodos, groupDoneTodos, PRIORITY_ORDER } from "@/hooks/use-todos";
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
    label: null,
    project: null,
    learning_item_id: null,
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
    warning: vi.fn(),
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
  label: null,
  project: null,
  learning_item_id: null,
  created_at: "2026-04-01T00:00:00Z",
  updated_at: "2026-04-01T00:00:00Z",
};

describe("useTodos hook", () => {
  beforeEach(() => {
    setApiKey("test-key");
    toastFn.mockClear();
    toastFn.success.mockClear();
    toastFn.error.mockClear();
    toastFn.info.mockClear();
    toastFn.warning.mockClear();
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
      start_date: null,
      label: null,
      project: null,
      learning_item_id: null,
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

  test("addTodo includes project in POST body", async () => {
    let postBody: Record<string, unknown> | null = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "GET" && path.includes("status=open")) {
          return jsonResponse({ todos: [], total: 0 });
        }
        if (init?.method === "GET" && path.includes("status=done")) {
          return jsonResponse({ todos: [], total: 0 });
        }
        if (init?.method === "POST") {
          postBody = JSON.parse(init.body as string) as Record<string, unknown>;
          return jsonResponse(
            {
              id: "p-1",
              description: "scoped task",
              priority: "normal",
              status: "open",
              due_date: null,
              start_date: null,
              label: null,
              project: "OB",
              learning_item_id: null,
              created_at: "2026-04-04T00:00:00Z",
              updated_at: "2026-04-04T00:00:00Z",
            },
            201,
          );
        }
        return jsonResponse({}, 500);
      }),
    );

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.addTodo("scoped task", "normal", { project: "OB" });
    });

    expect(postBody).not.toBeNull();
    expect(postBody!.project).toBe("OB");
    expect(result.current.openTodos[0].project).toBe("OB");
  });

  test("editTodo with project option includes project in PATCH body", async () => {
    const todo = { ...TODO_A, id: "ep-1" };
    let patchBody: Record<string, unknown> | null = null;

    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (init?.method === "GET" && path.includes("status=open")) {
          return jsonResponse({ todos: [todo], total: 1 });
        }
        if (init?.method === "GET" && path.includes("status=done")) {
          return jsonResponse({ todos: [], total: 0 });
        }
        if (init?.method === "PATCH") {
          patchBody = JSON.parse(init.body as string) as Record<string, unknown>;
          return jsonResponse({ ...todo, project: "Egle" });
        }
        return jsonResponse({}, 500);
      }),
    );

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.editTodo("ep-1", todo.description, todo.due_date, {
        project: "Egle",
      });
    });

    expect(patchBody).not.toBeNull();
    expect(patchBody!.project).toBe("Egle");
    expect(result.current.openTodos[0].project).toBe("Egle");
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

  // ── deferAll ──────────────────────────────────────────────────────────────

  test("deferAll updates due_date on every targeted todo and toasts success", async () => {
    const todoA = { ...TODO_A, id: "d-all-1", due_date: "2026-04-01T00:00:00Z" };
    const todoB = { ...TODO_A, id: "d-all-2", due_date: "2026-04-02T00:00:00Z" };
    const newDueDate = "2026-04-20";
    let postBody: Record<string, unknown> | null = null;

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todoA, todoB], total: 2 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "POST" && path.includes("/v1/todos/defer-all")) {
        postBody = JSON.parse(init.body as string);
        return jsonResponse({
          deferred: [
            { ...todoA, due_date: newDueDate },
            { ...todoB, due_date: newDueDate },
          ],
          skipped: [],
        });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferAll(["d-all-1", "d-all-2"], newDueDate);
    });

    expect(postBody).not.toBeNull();
    expect(postBody!.todo_ids).toEqual(["d-all-1", "d-all-2"]);
    expect(postBody!.due_date).toBe(newDueDate);
    expect(result.current.openTodos.map((t) => t.due_date)).toEqual([newDueDate, newDueDate]);
    expect(toastFn.success).toHaveBeenCalledWith("2 tasks deferred");
  });

  test("deferAll with reason forwards it in POST body", async () => {
    const todo = { ...TODO_A, id: "d-all-r", due_date: "2026-04-01T00:00:00Z" };
    let postBody: Record<string, unknown> | null = null;

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todo], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "POST" && path.includes("/v1/todos/defer-all")) {
        postBody = JSON.parse(init.body as string);
        return jsonResponse({
          deferred: [{ ...todo, due_date: "2026-04-15" }],
          skipped: [],
        });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferAll(["d-all-r"], "2026-04-15", "morning triage");
    });

    expect(postBody!.reason).toBe("morning triage");
  });

  test("deferAll warns when some todos are skipped", async () => {
    const todo = { ...TODO_A, id: "d-all-s", due_date: "2026-04-01T00:00:00Z" };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todo], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "POST" && path.includes("/v1/todos/defer-all")) {
        return jsonResponse({
          deferred: [{ ...todo, due_date: "2026-04-15" }],
          skipped: [{ todo_id: "missing-id", reason: "not_found" }],
        });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferAll(["d-all-s", "missing-id"], "2026-04-15");
    });

    expect(toastFn.warning).toHaveBeenCalledWith("1 task deferred (1 skipped)");
  });

  test("deferAll rolls back on POST failure", async () => {
    const todoA = { ...TODO_A, id: "d-all-f1", due_date: "2026-04-01T00:00:00Z" };
    const todoB = { ...TODO_A, id: "d-all-f2", due_date: "2026-04-02T00:00:00Z" };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [todoA, todoB], total: 2 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "POST" && path.includes("/v1/todos/defer-all")) {
        return jsonResponse({}, 500);
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deferAll(["d-all-f1", "d-all-f2"], "2026-04-20");
    });

    // Due dates rolled back to original values.
    const byId = Object.fromEntries(result.current.openTodos.map((t) => [t.id, t.due_date]));
    expect(byId["d-all-f1"]).toBe("2026-04-01T00:00:00Z");
    expect(byId["d-all-f2"]).toBe("2026-04-02T00:00:00Z");
    expect(toastFn.error).toHaveBeenCalledWith("Failed to defer tasks");
  });

  test("deferAll with empty ids is a no-op", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      await result.current.deferAll([], "2026-04-20");
    });
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });

  // ── F6: completeTodo undo toast ────────────────────────────────────────────

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

  // ── Undo via toast (stale closure fix) ────────────────────────────────────

  test("undo via toast restores task to open list", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
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

    // Extract undo callback from toast mock and invoke it
    const toastCall = toastFn.mock.calls.find(
      (c: unknown[]) => c[0] === "Task completed",
    );
    expect(toastCall).toBeDefined();
    const undoFn = toastCall![1].action.onClick;

    await act(async () => {
      undoFn();
    });

    // Task should be back in openTodos
    expect(result.current.openTodos).toHaveLength(1);
    expect(result.current.openTodos[0].id).toBe("a-1");
    expect(result.current.openTodos[0].status).toBe("open");
    expect(result.current.doneTodos).toHaveLength(0);
  });

  test("undo via toast sends PATCH {status: 'open'}", async () => {
    let patchCalls: { path: string; body: Record<string, unknown> }[] = [];

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "PATCH") {
        patchCalls.push({ path, body: JSON.parse(init.body as string) });
        return jsonResponse({ ...TODO_A, status: "open" });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    const toastCall = toastFn.mock.calls.find(
      (c: unknown[]) => c[0] === "Task completed",
    );
    const undoFn = toastCall![1].action.onClick;

    await act(async () => {
      undoFn();
    });

    // Second PATCH should be the undo call
    const undoPatch = patchCalls.find((c) => c.body.status === "open");
    expect(undoPatch).toBeDefined();
    expect(undoPatch!.path).toContain("/v1/todos/a-1");
    expect(undoPatch!.body).toEqual({ status: "open" });
  });

  test("undo via toast API failure rolls back (task stays done)", async () => {
    let patchCount = 0;

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "PATCH") {
        patchCount++;
        // First PATCH (complete) succeeds, second (undo) fails
        if (patchCount === 1) return jsonResponse({ ...TODO_A, status: "done" });
        return jsonResponse({}, 500);
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    const toastCall = toastFn.mock.calls.find(
      (c: unknown[]) => c[0] === "Task completed",
    );
    const undoFn = toastCall![1].action.onClick;

    await act(async () => {
      undoFn();
    });

    // Undo failed — task should remain in doneTodos
    expect(result.current.doneTodos).toHaveLength(1);
    expect(result.current.doneTodos[0].id).toBe("a-1");
    expect(result.current.openTodos).toHaveLength(0);
    expect(toastFn.error).toHaveBeenCalledWith("Failed to undo");
  });

  test("complete non-existent todo is no-op", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      return jsonResponse({}, 200);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.completeTodo("bogus-id");
    });

    // No state change, no PATCH call beyond initial fetches
    expect(result.current.openTodos).toHaveLength(1);
    expect(result.current.doneTodos).toHaveLength(0);
  });

  test("rapid complete→undo→complete doesn't corrupt state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [TODO_A], total: 1 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      return jsonResponse({ ...TODO_A, status: "done" });
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    // Complete
    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    // Extract undo and invoke
    const toastCall = toastFn.mock.calls.find(
      (c: unknown[]) => c[0] === "Task completed",
    );
    const undoFn = toastCall![1].action.onClick;
    await act(async () => {
      undoFn();
    });

    // Should be back in open
    expect(result.current.openTodos).toHaveLength(1);
    expect(result.current.doneTodos).toHaveLength(0);

    // Complete again
    toastFn.mockClear();
    await act(async () => {
      await result.current.completeTodo("a-1");
    });

    // Should be in done again, no duplicates
    expect(result.current.openTodos).toHaveLength(0);
    expect(result.current.doneTodos).toHaveLength(1);
    expect(result.current.doneTodos[0].id).toBe("a-1");
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

// ── filterThisWeekTodos ────────────────────────────────────────────────────

describe("filterThisWeekTodos", () => {
  /** Get the Monday 00:00 of the current ISO week. */
  function getThisMonday(): Date {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    const day = d.getDay();
    const diff = day === 0 ? 6 : day - 1;
    d.setDate(d.getDate() - diff);
    return d;
  }

  function dateInWeek(offsetDays: number): string {
    const monday = getThisMonday();
    monday.setDate(monday.getDate() + offsetDays);
    monday.setHours(12, 0, 0, 0);
    return monday.toISOString();
  }

  test("includes tasks due this week (Mon–Sun)", () => {
    // Due on Wednesday of this week
    const wed = makeTodo({ due_date: dateInWeek(2) });
    expect(filterThisWeekTodos([wed])).toHaveLength(1);
  });

  test("includes tasks due on Monday of this week", () => {
    const mon = makeTodo({ due_date: dateInWeek(0) });
    expect(filterThisWeekTodos([mon])).toHaveLength(1);
  });

  test("includes tasks due on Sunday of this week", () => {
    const sun = makeTodo({ due_date: dateInWeek(6) });
    expect(filterThisWeekTodos([sun])).toHaveLength(1);
  });

  test("excludes tasks due next week", () => {
    const nextWeek = makeTodo({ due_date: dateInWeek(7) });
    expect(filterThisWeekTodos([nextWeek])).toHaveLength(0);
  });

  test("excludes tasks due last week", () => {
    const lastWeek = makeTodo({ due_date: dateInWeek(-1) });
    expect(filterThisWeekTodos([lastWeek])).toHaveLength(0);
  });

  test("excludes tasks with no due_date", () => {
    const noDue = makeTodo({ due_date: null });
    expect(filterThisWeekTodos([noDue])).toHaveLength(0);
  });
});

// ── groupDoneTodos ─────────────────────────────────────────────────────────

describe("groupDoneTodos", () => {
  function getThisMonday(): Date {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    const day = d.getDay();
    const diff = day === 0 ? 6 : day - 1;
    d.setDate(d.getDate() - diff);
    return d;
  }

  test("returns empty array for no todos", () => {
    expect(groupDoneTodos([])).toEqual([]);
  });

  test("groups completed this week under 'This Week'", () => {
    const thisWeek = getThisMonday();
    thisWeek.setDate(thisWeek.getDate() + 1); // Tuesday
    const todo = makeTodo({ status: "done", updated_at: thisWeek.toISOString() });
    const groups = groupDoneTodos([todo]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("This Week");
    expect(groups[0].todos).toHaveLength(1);
  });

  test("groups completed last week under 'Last Week'", () => {
    const lastWeek = getThisMonday();
    lastWeek.setDate(lastWeek.getDate() - 3); // Last week Friday
    const todo = makeTodo({ status: "done", updated_at: lastWeek.toISOString() });
    const groups = groupDoneTodos([todo]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Last Week");
  });

  test("groups older todos by month/year", () => {
    const oldDate = new Date(2025, 0, 15); // January 2025
    const todo = makeTodo({ status: "done", updated_at: oldDate.toISOString() });
    const groups = groupDoneTodos([todo]);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toContain("2025");
  });

  test("multiple groups for mixed completion dates", () => {
    const thisWeek = getThisMonday();
    thisWeek.setDate(thisWeek.getDate() + 1);
    const lastWeek = getThisMonday();
    lastWeek.setDate(lastWeek.getDate() - 2);

    const todos = [
      makeTodo({ id: "1", status: "done", updated_at: thisWeek.toISOString() }),
      makeTodo({ id: "2", status: "done", updated_at: lastWeek.toISOString() }),
    ];
    const groups = groupDoneTodos(todos);
    expect(groups).toHaveLength(2);
    expect(groups[0].label).toBe("This Week");
    expect(groups[1].label).toBe("Last Week");
  });
});

// ── loadMoreDone pagination ────────────────────────────────────────────────

describe("loadMoreDone pagination", () => {
  beforeEach(() => {
    setApiKey("test-key");
    toastFn.mockClear();
    toastFn.success.mockClear();
    toastFn.error.mockClear();
    toastFn.info.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("hasMoreDone is true when initial fetch returns full page", async () => {
    const doneTodos = Array.from({ length: 20 }, (_, i) =>
      makeTodo({ id: `done-${i}`, status: "done" }),
    );

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: doneTodos, total: 20 });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasMoreDone).toBe(true);
    expect(result.current.doneTodos).toHaveLength(20);
  });

  test("hasMoreDone is false when initial fetch returns less than page size", async () => {
    const doneTodos = [makeTodo({ id: "done-1", status: "done" })];

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        return jsonResponse({ todos: doneTodos, total: 1 });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.hasMoreDone).toBe(false);
  });

  test("loadMoreDone appends next page and updates hasMoreDone", async () => {
    const page1 = Array.from({ length: 20 }, (_, i) =>
      makeTodo({ id: `done-${i}`, status: "done" }),
    );
    const page2 = Array.from({ length: 5 }, (_, i) =>
      makeTodo({ id: `done-extra-${i}`, status: "done" }),
    );

    let fetchCallCount = 0;
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET" && path.includes("status=open")) {
        return jsonResponse({ todos: [], total: 0 });
      }
      if (init?.method === "GET" && path.includes("status=done")) {
        fetchCallCount++;
        if (fetchCallCount === 1) {
          return jsonResponse({ todos: page1, total: 20 });
        }
        return jsonResponse({ todos: page2, total: 5 });
      }
      return jsonResponse({}, 404);
    }));

    const { useTodos } = await import("@/hooks/use-todos");
    const { result } = renderHook(() => useTodos());
    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.doneTodos).toHaveLength(20);
    expect(result.current.hasMoreDone).toBe(true);

    await act(async () => {
      await result.current.loadMoreDone();
    });

    expect(result.current.doneTodos).toHaveLength(25);
    expect(result.current.hasMoreDone).toBe(false);
  });
});
