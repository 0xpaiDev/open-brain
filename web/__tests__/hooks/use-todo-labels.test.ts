import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { setApiKey } from "@/lib/api";
import type { TodoLabel } from "@/lib/types";

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

const LABEL_WORK: TodoLabel = {
  id: "l-1",
  name: "Work",
  color: "#FF0000",
  created_at: "2026-01-01T00:00:00Z",
};

const LABEL_PERSONAL: TodoLabel = {
  id: "l-2",
  name: "Personal",
  color: "#00FF00",
  created_at: "2026-01-01T00:00:00Z",
};

describe("useTodoLabels", () => {
  beforeEach(() => {
    setApiKey("test-key");
    toastFn.mockClear();
    toastFn.error.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("fetches labels on mount", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([LABEL_WORK, LABEL_PERSONAL])));

    const { useTodoLabels } = await import("@/hooks/use-todo-labels");
    const { result } = renderHook(() => useTodoLabels());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.labels).toHaveLength(2);
    expect(result.current.labels[0].name).toBe("Work");
  });

  test("createLabel adds to list optimistically", async () => {
    const newLabel: TodoLabel = { id: "l-new", name: "Urgent", color: "#6750A4", created_at: "2026-04-04T00:00:00Z" };

    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse([]);
      // POST returns created label
      return jsonResponse(newLabel, 201);
    }));

    const { useTodoLabels } = await import("@/hooks/use-todo-labels");
    const { result } = renderHook(() => useTodoLabels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.createLabel("Urgent");
    });

    expect(result.current.labels).toHaveLength(1);
    expect(result.current.labels[0].name).toBe("Urgent");
  });

  test("createLabel API error rolls back", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse([]);
      // POST fails (duplicate)
      return jsonResponse({ detail: "exists" }, 409);
    }));

    const { useTodoLabels } = await import("@/hooks/use-todo-labels");
    const { result } = renderHook(() => useTodoLabels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.createLabel("Dup");
    });

    expect(result.current.labels).toHaveLength(0);
    expect(toastFn.error).toHaveBeenCalledWith("Failed to create label");
  });

  test("deleteLabel removes from list", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse([LABEL_WORK]);
      // DELETE succeeds
      return { ok: true, status: 204, json: async () => undefined } as Response;
    }));

    const { useTodoLabels } = await import("@/hooks/use-todo-labels");
    const { result } = renderHook(() => useTodoLabels());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.labels).toHaveLength(1);

    await act(async () => {
      await result.current.deleteLabel("Work");
    });

    expect(result.current.labels).toHaveLength(0);
  });

  test("deleteLabel API error rolls back", async () => {
    vi.stubGlobal("fetch", vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse([LABEL_WORK]);
      // DELETE fails
      return jsonResponse({}, 500);
    }));

    const { useTodoLabels } = await import("@/hooks/use-todo-labels");
    const { result } = renderHook(() => useTodoLabels());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.deleteLabel("Work");
    });

    // Rolled back
    expect(result.current.labels).toHaveLength(1);
    expect(result.current.labels[0].name).toBe("Work");
    expect(toastFn.error).toHaveBeenCalledWith("Failed to delete label");
  });
});
