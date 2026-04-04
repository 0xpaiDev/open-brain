import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { setApiKey } from "@/lib/api";
import type { TodoItem } from "@/lib/types";

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const OVERDUE_TODO: TodoItem = {
  id: "od-1",
  description: "Overdue task",
  priority: "normal",
  status: "open",
  due_date: "2020-01-01T00:00:00Z",
  start_date: null,
  label: null,
  created_at: "2020-01-01T00:00:00Z",
  updated_at: "2020-01-01T00:00:00Z",
};

const OVERDUE_TODO_2: TodoItem = {
  ...OVERDUE_TODO,
  id: "od-2",
  description: "Another overdue",
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("useOverdue", () => {
  beforeEach(() => {
    vi.resetModules();
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("fetches overdue tasks on mount", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([OVERDUE_TODO, OVERDUE_TODO_2])));

    const { useOverdue } = await import("@/hooks/use-overdue");
    const { result } = renderHook(() => useOverdue());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overdueTodos).toHaveLength(2);
    expect(result.current.allHandled).toBe(false);
  });

  test("re-fetches on visibility change", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([OVERDUE_TODO]));
    vi.stubGlobal("fetch", fetchMock);

    const { useOverdue } = await import("@/hooks/use-overdue");
    const { result } = renderHook(() => useOverdue());

    await waitFor(() => expect(result.current.loading).toBe(false));
    const initialCallCount = fetchMock.mock.calls.length;

    // Simulate tab becoming visible
    Object.defineProperty(document, "visibilityState", { value: "visible", writable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    await waitFor(() => {
      expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCallCount);
    });
  });

  test("deferOverdue removes task from list", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "GET") {
        return jsonResponse([OVERDUE_TODO, OVERDUE_TODO_2]);
      }
      // PATCH succeeds
      return jsonResponse({ ...OVERDUE_TODO, due_date: "2026-12-31T00:00:00Z" });
    }));

    const { useOverdue } = await import("@/hooks/use-overdue");
    const { result } = renderHook(() => useOverdue());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overdueTodos).toHaveLength(2);

    await act(async () => {
      await result.current.deferOverdue("od-1", "2026-12-31", "Need more time");
    });

    expect(result.current.overdueTodos).toHaveLength(1);
    expect(result.current.overdueTodos[0].id).toBe("od-2");
  });

  test("allHandled true when list empty", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));

    const { useOverdue } = await import("@/hooks/use-overdue");
    const { result } = renderHook(() => useOverdue());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.overdueTodos).toHaveLength(0);
    expect(result.current.allHandled).toBe(true);
  });
});
