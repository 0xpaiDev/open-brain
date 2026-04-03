import { describe, test, expect } from "vitest";
import { getDueBadge } from "@/components/dashboard/task-list";

// ── T-20 to T-24: getDueBadge ──────────────────────────────────────────────

describe("getDueBadge", () => {
  // T-23: null input
  test("returns null for null input", () => {
    expect(getDueBadge(null)).toBeNull();
  });

  // T-20: past date → Overdue
  test("returns Overdue for past dates", () => {
    const result = getDueBadge("2020-01-01T00:00:00Z");
    expect(result).not.toBeNull();
    expect(result!.label).toBe("Overdue");
    expect(result!.className).toContain("error");
  });

  // T-21: today → Today
  test("returns Today for today's date", () => {
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    const result = getDueBadge(today.toISOString());
    expect(result).not.toBeNull();
    expect(result!.label).toBe("Today");
  });

  // T-22: tomorrow → Tomorrow
  test("returns Tomorrow for tomorrow's date", () => {
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    tomorrow.setHours(12, 0, 0, 0);
    const result = getDueBadge(tomorrow.toISOString());
    expect(result).not.toBeNull();
    expect(result!.label).toBe("Tomorrow");
  });

  // T-24: future date > 1 day → formatted date
  test("returns formatted date for future dates beyond tomorrow", () => {
    const future = new Date();
    future.setDate(future.getDate() + 7);
    future.setHours(12, 0, 0, 0);
    const result = getDueBadge(future.toISOString());
    expect(result).not.toBeNull();
    // Should be a locale date string like "Apr 10"
    expect(result!.label).toMatch(/\w+/);
    expect(result!.label).not.toBe("Today");
    expect(result!.label).not.toBe("Tomorrow");
    expect(result!.label).not.toBe("Overdue");
  });

  // Edge: yesterday
  test("returns Overdue for yesterday", () => {
    const yesterday = new Date();
    yesterday.setDate(yesterday.getDate() - 1);
    yesterday.setHours(12, 0, 0, 0);
    const result = getDueBadge(yesterday.toISOString());
    expect(result!.label).toBe("Overdue");
  });
});
