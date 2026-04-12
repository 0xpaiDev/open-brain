import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MorningPulse } from "@/components/dashboard/morning-pulse";
import type { PulseResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const SENT_PULSE: PulseResponse = {
  id: "p-1",
  pulse_date: "2026-04-12",
  status: "sent",
  ai_question: "What's your plan?",
  ai_question_response: null,
  wake_time: null,
  sleep_quality: null,
  energy_level: null,
  notes: null,
  parsed_data: null,
  clean_meal: null,
  alcohol: null,
  created_at: "2026-04-12T06:00:00Z",
  updated_at: "2026-04-12T06:00:00Z",
};

const COMPLETED_PULSE: PulseResponse = {
  ...SENT_PULSE,
  status: "completed",
  sleep_quality: 4,
  energy_level: 3,
  clean_meal: true,
  alcohol: false,
  updated_at: "2026-04-12T07:00:00Z",
};

function mockFetch(handler: (path: string, init: RequestInit) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(handler));
}

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

beforeEach(() => {
  setApiKey("test-key");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MorningPulse nutrition", () => {
  test("renders clean eating and alcohol toggles in form", async () => {
    mockFetch(async () => jsonResponse(SENT_PULSE));

    render(<MorningPulse />);

    await waitFor(() => {
      expect(screen.getByText("Clean eating")).toBeTruthy();
      expect(screen.getByText("Alcohol")).toBeTruthy();
    });
  });

  test("submit includes nutrition fields", async () => {
    let patchBody: Record<string, unknown> | null = null;

    const fetchSpy = vi.fn(async (path: string, init: RequestInit) => {
      if (init.method === "GET") return jsonResponse(SENT_PULSE);
      if (init.method === "PATCH") {
        patchBody = JSON.parse(init.body as string);
        return jsonResponse(COMPLETED_PULSE);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchSpy);

    render(<MorningPulse />);

    await waitFor(() => {
      expect(screen.getByText("Clean eating")).toBeTruthy();
    });

    // Click "Yes" for clean eating
    const yesButtons = screen.getAllByText("Yes");
    fireEvent.click(yesButtons[0]); // Clean eating Yes

    // Click "No" for alcohol
    const noButtons = screen.getAllByText("No");
    fireEvent.click(noButtons[1]); // Alcohol No

    // Submit the form
    fireEvent.click(screen.getByText("Log my morning"));

    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody!.clean_meal).toBe(true);
    expect(patchBody!.alcohol).toBe(false);
  });

  test("summary shows nutrition badges when set", async () => {
    mockFetch(async () => jsonResponse(COMPLETED_PULSE));

    render(<MorningPulse />);

    await waitFor(() => {
      expect(screen.getByText("Clean")).toBeTruthy();
      expect(screen.getByText("Sober")).toBeTruthy();
    });
  });

  test("summary hides nutrition badges when null", async () => {
    const pulseNoNutrition: PulseResponse = {
      ...COMPLETED_PULSE,
      clean_meal: null,
      alcohol: null,
    };
    mockFetch(async () => jsonResponse(pulseNoNutrition));

    render(<MorningPulse />);

    await waitFor(() => {
      expect(screen.getByText("Morning Pulse")).toBeTruthy();
    });

    expect(screen.queryByText("Clean")).toBeNull();
    expect(screen.queryByText("Sober")).toBeNull();
    expect(screen.queryByText("Cheat")).toBeNull();
    expect(screen.queryByText("Drank")).toBeNull();
  });
});
