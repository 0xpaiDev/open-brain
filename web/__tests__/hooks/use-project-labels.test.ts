import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { setApiKey } from "@/lib/api";
import type { ProjectLabel } from "@/lib/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const INITIAL_LABELS: ProjectLabel[] = [
  { id: "p-1", name: "OB", color: "#E07060", created_at: "2026-04-01T00:00:00Z" },
];

describe("useProjectLabels.renameLabel", () => {
  beforeEach(() => {
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  test("optimistically renames and confirms on success", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === undefined || init?.method === "GET") {
        return jsonResponse(INITIAL_LABELS);
      }
      if (init?.method === "PATCH" && path.includes("/v1/project-labels/OB")) {
        return jsonResponse({
          id: "p-1",
          name: "Open Brain",
          color: "#E07060",
          created_at: "2026-04-01T00:00:00Z",
        });
      }
      return jsonResponse({}, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useProjectLabels } = await import("@/hooks/use-project-labels");
    const { result } = renderHook(() => useProjectLabels());

    await waitFor(() => expect(result.current.labels.length).toBe(1));

    let ok = false;
    await act(async () => {
      ok = await result.current.renameLabel("OB", "Open Brain");
    });

    expect(ok).toBe(true);
    expect(result.current.labels[0].name).toBe("Open Brain");

    // PATCH was called with new_name
    const patchCall = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "PATCH");
    expect(patchCall).toBeDefined();
    const body = JSON.parse((patchCall![1] as RequestInit).body as string);
    expect(body).toEqual({ new_name: "Open Brain" });
  });

  test("rolls back on 409 collision", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === undefined || init?.method === "GET") {
        return jsonResponse([
          ...INITIAL_LABELS,
          { id: "p-2", name: "Open Brain", color: "#7b8fc7", created_at: "2026-04-01T00:00:00Z" },
        ]);
      }
      if (init?.method === "PATCH") {
        return {
          ok: false,
          status: 409,
          json: async () => ({ detail: "exists" }),
        } as Response;
      }
      return jsonResponse({}, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useProjectLabels } = await import("@/hooks/use-project-labels");
    const { result } = renderHook(() => useProjectLabels());
    await waitFor(() => expect(result.current.labels.length).toBe(2));

    const before = result.current.labels.map((l) => l.name).sort();

    let ok = true;
    await act(async () => {
      ok = await result.current.renameLabel("OB", "Open Brain");
    });

    expect(ok).toBe(false);
    expect(result.current.labels.map((l) => l.name).sort()).toEqual(before);
  });

  test("empty new name is rejected without a network call", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === undefined || init?.method === "GET") {
        return jsonResponse(INITIAL_LABELS);
      }
      return jsonResponse({}, 500);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { useProjectLabels } = await import("@/hooks/use-project-labels");
    const { result } = renderHook(() => useProjectLabels());
    await waitFor(() => expect(result.current.labels.length).toBe(1));

    let ok = true;
    await act(async () => {
      ok = await result.current.renameLabel("OB", "   ");
    });

    expect(ok).toBe(false);
    // No PATCH was attempted.
    const patchCalls = fetchMock.mock.calls.filter(
      (c) => (c[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patchCalls).toHaveLength(0);
  });
});
