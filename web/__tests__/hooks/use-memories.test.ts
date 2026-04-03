import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { isSearchResult, useMemories } from "@/hooks/use-memories";
import { setApiKey } from "@/lib/api";
import type {
  MemoryItemResponse,
  MemoryRecentResponse,
  MemoryIngestResponse,
  SearchResponse,
} from "@/lib/types";

// ── T-25: isSearchResult type guard ─────────────────────────────────────────

describe("isSearchResult", () => {
  test("returns true for objects with combined_score property", () => {
    const searchResult = {
      id: "x",
      type: "memory",
      content: "test",
      combined_score: 0.85,
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(isSearchResult(searchResult as any)).toBe(true);
  });

  test("returns false for memory items without combined_score", () => {
    const memoryItem = {
      id: "x",
      raw_id: "y",
      type: "memory",
      content: "test",
      importance_score: 0.5,
      base_importance: 0.5,
      dynamic_importance: 0.0,
      is_superseded: false,
      supersedes_id: null,
      summary: null,
      created_at: "2026-01-01T00:00:00Z",
    };
    expect(isSearchResult(memoryItem as any)).toBe(false);
  });

  test("returns false for empty objects", () => {
    expect(isSearchResult({} as any)).toBe(false);
  });
});

// ── useMemories hook tests ──────────────────────────────────────────────────

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const MEMORY_A: MemoryItemResponse = {
  id: "m-1",
  raw_id: "r-1",
  type: "memory",
  content: "First memory",
  summary: null,
  base_importance: 0.5,
  dynamic_importance: 0.0,
  importance_score: 0.5,
  is_superseded: false,
  supersedes_id: null,
  created_at: "2026-04-01T00:00:00Z",
};

const MEMORY_B: MemoryItemResponse = {
  ...MEMORY_A,
  id: "m-2",
  raw_id: "r-2",
  content: "Second memory",
  created_at: "2026-04-02T00:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

describe("useMemories hook", () => {
  beforeEach(() => {
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ── T-38: Browse mode fetches recent on mount ───────────────────────────

  test("browse mode fetches recent memories on mount", async () => {
    const response: MemoryRecentResponse = { items: [MEMORY_A, MEMORY_B], total: 2 };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(response)));

    const { result } = renderHook(() => useMemories());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(2);
    expect(result.current.total).toBe(2);
    expect(result.current.isSearchMode).toBe(false);
  });

  // ── T-39: Search mode fetches search results ───────────────────────────

  test("search mode fetches search results", async () => {
    const searchResponse: SearchResponse = {
      query: "test",
      results: [
        {
          id: "m-1",
          content: "First memory",
          summary: null,
          type: "memory",
          importance_score: 0.5,
          combined_score: 0.9,
        },
      ],
    };
    const fetchMock = vi.fn(async () => jsonResponse(searchResponse));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useMemories({ searchQuery: "test" }));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.isSearchMode).toBe(true);
    expect(result.current.items).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/v1/search?q=test"),
      expect.anything(),
    );
  });

  // ── T-40: loadMore skipped in search mode ──────────────────────────────

  test("loadMore does nothing in search mode", async () => {
    const searchResponse: SearchResponse = {
      query: "test",
      results: [{ id: "m-1", content: "x", summary: null, type: "memory", importance_score: 0.5, combined_score: 0.9 }],
    };
    const fetchMock = vi.fn(async () => jsonResponse(searchResponse));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useMemories({ searchQuery: "test" }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const callCountBefore = fetchMock.mock.calls.length;
    result.current.loadMore();
    // No additional fetch call
    expect(fetchMock.mock.calls.length).toBe(callCountBefore);
  });

  // ── T-41: ingestMemory duplicate shows info toast ─────────────────────

  test("ingestMemory shows info toast for duplicates", async () => {
    const { toast } = await import("sonner");
    const dupResponse: MemoryIngestResponse = { raw_id: "r-dup", status: "duplicate", supersedes_id: null };
    const browseResponse: MemoryRecentResponse = { items: [], total: 0 };

    vi.stubGlobal("fetch", vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse(dupResponse, 202);
      return jsonResponse(browseResponse);
    }));

    const { result } = renderHook(() => useMemories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let success: boolean | undefined;
    await act(async () => {
      success = await result.current.ingestMemory("duplicate text");
    });

    expect(success).toBe(true);
    expect(toast.info).toHaveBeenCalledWith(expect.stringContaining("already exists"));
  });

  // ── ingestMemory queued shows success toast ───────────────────────────

  test("ingestMemory shows success toast for queued", async () => {
    const { toast } = await import("sonner");
    const queuedResponse: MemoryIngestResponse = { raw_id: "r-new", status: "queued", supersedes_id: null };
    const browseResponse: MemoryRecentResponse = { items: [], total: 0 };

    vi.stubGlobal("fetch", vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse(queuedResponse, 202);
      return jsonResponse(browseResponse);
    }));

    const { result } = renderHook(() => useMemories());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.ingestMemory("new text");
    });

    expect(toast.success).toHaveBeenCalledWith(expect.stringContaining("queued"));
  });

  // ── T-42: loadMore appends items in browse mode ────────────────────────

  test("loadMore appends items in browse mode", async () => {
    const page1: MemoryRecentResponse = { items: [MEMORY_A], total: 2 };
    const page2: MemoryRecentResponse = { items: [MEMORY_B], total: 2 };
    let callIdx = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      callIdx++;
      return jsonResponse(callIdx <= 1 ? page1 : page2);
    }));

    const { result } = renderHook(() => useMemories());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.items).toHaveLength(1);

    await act(async () => {
      result.current.loadMore();
    });

    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.items[0].id).toBe("m-1");
    expect(result.current.items[1].id).toBe("m-2");
  });
});
