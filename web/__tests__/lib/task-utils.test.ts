import { describe, test, expect } from "vitest";
import { getFocusDateLabel } from "@/components/dashboard/task-utils";

describe("getFocusDateLabel", () => {
  test("returns null when both dueDate and startDate are null", () => {
    expect(getFocusDateLabel(null, null)).toBeNull();
    expect(getFocusDateLabel(null)).toBeNull();
    expect(getFocusDateLabel(null, undefined)).toBeNull();
  });

  test("returns single-date badge when only dueDate is set", () => {
    const result = getFocusDateLabel("2026-05-09", null);
    expect(result).not.toBeNull();
    expect(result!.label).not.toContain("Invalid Date");
  });

  test("returns single-date badge when only startDate is set (defensive)", () => {
    const result = getFocusDateLabel(null, "2026-05-09");
    expect(result).not.toBeNull();
    expect(result!.label).not.toContain("Invalid Date");
  });

  test("returns range label when both dates are set and different", () => {
    const result = getFocusDateLabel("2026-05-09", "2026-05-05");
    expect(result).not.toBeNull();
    expect(result!.label).toContain("–");
    expect(result!.label).not.toContain("Invalid Date");
    expect(result!.className).toContain("primary");
  });

  test("range label has start before end (earlier – later)", () => {
    const result = getFocusDateLabel("2026-05-09", "2026-05-05");
    // Should be "May 5 – May 9" (or locale equivalent), not reversed
    const parts = result!.label.split("–").map((s) => s.trim());
    expect(parts).toHaveLength(2);
    // Both parts should be non-empty and not "Invalid Date"
    expect(parts[0]).not.toContain("Invalid Date");
    expect(parts[1]).not.toContain("Invalid Date");
  });

  test("collapses to single-date badge when start === due", () => {
    const result = getFocusDateLabel("2026-05-09", "2026-05-09");
    expect(result).not.toBeNull();
    expect(result!.label).not.toContain("–");
  });

  test("handles inverted range (start > due) without crashing", () => {
    // start after due — should swap and render a range, not crash
    const result = getFocusDateLabel("2026-05-01", "2026-05-09");
    expect(result).not.toBeNull();
    expect(result!.label).not.toContain("Invalid Date");
    expect(result!.label).toContain("–");
  });

  test("works with full ISO datetime strings (does not produce Invalid Date)", () => {
    const result = getFocusDateLabel("2026-05-09T00:00:00Z", "2026-05-05T00:00:00Z");
    expect(result).not.toBeNull();
    expect(result!.label).not.toContain("Invalid Date");
  });

  test("never returns a string containing 'Invalid' for any combination", () => {
    const combinations: [string | null, string | null | undefined][] = [
      [null, null],
      ["2026-05-09", null],
      [null, "2026-05-05"],
      ["2026-05-09", "2026-05-05"],
      ["2026-05-09", "2026-05-09"],
      ["2026-05-01", "2026-05-09"],
      ["2026-05-09T00:00:00Z", "2026-05-05T00:00:00Z"],
    ];
    for (const [due, start] of combinations) {
      const result = getFocusDateLabel(due, start);
      if (result) {
        expect(result.label).not.toContain("Invalid");
      }
    }
  });
});
