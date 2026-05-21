import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MorningPulse } from "@/components/dashboard/morning-pulse";
import type { PulseResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const base: PulseResponse = {
  id: "p-1",
  pulse_date: "2026-04-23",
  status: "sent",
  ai_question: null,
  ai_question_response: null,
  wake_time: null,
  sleep_quality: null,
  energy_level: null,
  parsed_data: null,
  clean_meal: null,
  alcohol: null,
  signal_type: null,
  created_at: "2026-04-23T05:00:00Z",
  updated_at: "2026-04-23T05:00:00Z",
};

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => setApiKey("test-key"));
afterEach(() => vi.restoreAllMocks());

describe("MorningPulse — briefing bullet rendering", () => {
  test("multi-line ai_question renders each bullet as a list item", async () => {
    const pulse = {
      ...base,
      ai_question: "• Today: Paulius's birthday\n• Ride weather: wet rest of week",
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(pulse)));
    render(<MorningPulse />);
    await waitFor(() => {
      expect(screen.getByText("Today: Paulius's birthday")).toBeTruthy();
    });
    expect(screen.getByText("Ride weather: wet rest of week")).toBeTruthy();
  });

  test("single-line ai_question without bullet prefix renders as-is", async () => {
    const pulse = { ...base, ai_question: "Ride weather today; wet rest of week." };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(pulse)));
    render(<MorningPulse />);
    await waitFor(() => {
      expect(screen.getByText("Ride weather today; wet rest of week.")).toBeTruthy();
    });
  });

  test("null ai_question renders no bullet list", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(base)));
    render(<MorningPulse />);
    await waitFor(() => {
      expect(screen.getByText("Log my morning")).toBeTruthy();
    });
    expect(screen.queryByRole("list")).toBeNull();
  });
});
