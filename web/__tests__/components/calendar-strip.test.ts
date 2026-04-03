import { describe, test, expect } from "vitest";
import { isCurrentOrNext } from "@/components/dashboard/calendar-strip";
import type { CalendarEvent } from "@/lib/types";

// ── Helpers ─────────────────────────────────────────────────────────────────

function makeEvent(startOffset: number, endOffset: number, now: Date): CalendarEvent {
  return {
    title: "Test Event",
    start: new Date(now.getTime() + startOffset).toISOString(),
    end: new Date(now.getTime() + endOffset).toISOString(),
    location: null,
    calendar: "Work",
    all_day: false,
  };
}

const HOUR = 60 * 60 * 1000;

// ── T-25 to T-28: isCurrentOrNext ───────────────────────────────────────────

describe("isCurrentOrNext", () => {
  const now = new Date("2026-04-03T10:00:00Z");

  // T-25: event happening now → true
  test("returns true for event happening now", () => {
    const event = makeEvent(-1 * HOUR, 1 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(true);
  });

  // T-26: event starting within 2h → true
  test("returns true for event starting within 2 hours", () => {
    const event = makeEvent(1 * HOUR, 2 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(true);
  });

  // T-27: event >2h away → false
  test("returns false for event more than 2 hours away", () => {
    const event = makeEvent(3 * HOUR, 4 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(false);
  });

  // T-28: past event → false
  test("returns false for past event", () => {
    const event = makeEvent(-3 * HOUR, -1 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(false);
  });

  // Edge: event ending exactly at now
  test("returns true for event ending exactly at now (boundary)", () => {
    const event = makeEvent(-1 * HOUR, 0, now);
    expect(isCurrentOrNext(event, now)).toBe(true);
  });

  // Edge: event starting exactly at 2h boundary
  test("returns true for event starting at exactly 2h boundary", () => {
    const event = makeEvent(2 * HOUR, 3 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(true);
  });

  // Edge: event starting 1ms past 2h boundary
  test("returns false for event starting 1ms past 2h boundary", () => {
    const event = makeEvent(2 * HOUR + 1, 3 * HOUR, now);
    expect(isCurrentOrNext(event, now)).toBe(false);
  });
});
