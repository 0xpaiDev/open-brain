import { describe, test, expect } from "vitest";
import { isSearchResult } from "@/hooks/use-memories";

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
