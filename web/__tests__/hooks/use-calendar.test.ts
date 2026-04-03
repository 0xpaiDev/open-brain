import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useCalendar } from "@/hooks/use-calendar";
import type { CalendarResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

// ── Fixtures ────────────────────────────────────────────────────────────────

const FAKE_CALENDAR: CalendarResponse = {
  status: "ok",
  date: "2026-04-03",
  fetched_at: "2026-04-03T08:00:00Z",
  events: [
    {
      title: "Standup",
      start: "2026-04-03T09:00:00Z",
      end: "2026-04-03T09:15:00Z",
      location: null,
      calendar: "Work",
      all_day: false,
    },
  ],
  tomorrow_preview: [],
};

// ── Helpers ─────────────────────────────────────────────────────────────────

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => {
  setApiKey("test-key");
});

afterEach(() => {
  vi.restoreAllMocks();
});

// ── T-43: Fetches calendar on mount ─────────────────────────────────────────

describe("useCalendar", () => {
  test("fetches calendar on mount and sets data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(FAKE_CALENDAR)));

    const { result } = renderHook(() => useCalendar());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toEqual(FAKE_CALENDAR);
    expect(result.current.error).toBeNull();
  });

  // ── T-44: Error sets message ──────────────────────────────────────────────

  test("error sets error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 500)));

    const { result } = renderHook(() => useCalendar());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBe("Failed to load calendar");
  });
});
