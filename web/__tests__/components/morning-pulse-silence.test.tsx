import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MorningPulse } from "@/components/dashboard/morning-pulse";
import type { PulseResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const SILENT_PULSE: PulseResponse & { signal_type: string | null } = {
  id: "p-silent",
  pulse_date: "2026-04-23",
  status: "silent",
  ai_question: null,
  ai_question_response: null,
  wake_time: null,
  sleep_quality: null,
  energy_level: null,
  notes: null,
  parsed_data: { signal_trace: [] },
  clean_meal: null,
  alcohol: null,
  created_at: "2026-04-23T05:00:00Z",
  updated_at: "2026-04-23T05:00:00Z",
  signal_type: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => setApiKey("test-key"));
afterEach(() => vi.restoreAllMocks());

describe("MorningPulse — silence path", () => {
  test("silent status renders silence card, not the log form", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(SILENT_PULSE)));

    render(<MorningPulse />);

    await waitFor(() => {
      expect(screen.getByText(/no pulse today/i)).toBeTruthy();
    });
    // The log-my-morning button must not be on the silence card
    expect(screen.queryByText("Log my morning")).toBeNull();
  });
});
