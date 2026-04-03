import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { usePulse } from "@/hooks/use-pulse";
import type { PulseResponse } from "@/lib/types";
import { setApiKey } from "@/lib/api";

// Mock sonner toast
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

// ── Fixtures ────────────────────────────────────────────────────────────────

const FAKE_PULSE: PulseResponse = {
  id: "p-1",
  pulse_date: "2026-04-03",
  status: "sent",
  ai_question: "What are you looking forward to?",
  ai_question_response: null,
  wake_time: null,
  sleep_quality: null,
  energy_level: null,
  notes: null,
  parsed_data: null,
  created_at: "2026-04-03T06:00:00Z",
  updated_at: "2026-04-03T06:00:00Z",
};

const COMPLETED_PULSE: PulseResponse = {
  ...FAKE_PULSE,
  status: "completed",
  sleep_quality: 4,
  energy_level: 3,
};

// ── Helpers ─────────────────────────────────────────────────────────────────

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

// ── T-32: Fetches today's pulse on mount ────────────────────────────────────

describe("usePulse", () => {
  test("fetches today's pulse on mount", async () => {
    mockFetch(async () => jsonResponse(FAKE_PULSE));

    const { result } = renderHook(() => usePulse());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.pulse).toEqual(FAKE_PULSE);
    expect(result.current.error).toBeNull();
  });

  // ── T-33: 404 → null pulse, no error ────────────────────────────────────

  test("404 sets null pulse without error", async () => {
    mockFetch(async () => jsonResponse({}, 404));

    const { result } = renderHook(() => usePulse());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.pulse).toBeNull();
    expect(result.current.error).toBeNull();
  });

  // ── T-34: Non-404 error → error state ───────────────────────────────────

  test("non-404 error sets error message", async () => {
    mockFetch(async () => jsonResponse({}, 500));

    const { result } = renderHook(() => usePulse());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.pulse).toBeNull();
    expect(result.current.error).toBe("Failed to load pulse");
  });

  // ── T-35: createPulse calls POST and sets pulse ─────────────────────────

  test("createPulse calls POST with today's date", async () => {
    const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse({}, 404);
      return jsonResponse(FAKE_PULSE); // POST
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePulse());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.pulse).toBeNull();

    await act(async () => {
      await result.current.createPulse();
    });

    expect(result.current.pulse).toEqual(FAKE_PULSE);
    // Verify POST was called to /v1/pulse/start with no body
    const postCall = fetchMock.mock.calls.find(
      ([, init]) => init?.method === "POST",
    );
    expect(postCall).toBeDefined();
    expect(postCall![0]).toContain("/v1/pulse/start");
    expect(postCall![1].body).toBeUndefined();
  });

  // ── createPulse 409 → fallback to GET /v1/pulse/today ─────────────────

  test("createPulse 409 fetches existing pulse", async () => {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "POST") return jsonResponse({ detail: "exists" }, 409);
      // GET /v1/pulse/today — first call returns 404 (mount), second returns pulse (409 fallback)
      if (init?.method === "GET") {
        if (fetchMock.mock.calls.filter(([, i]) => !i?.method || i.method === "GET").length <= 1) {
          return jsonResponse({}, 404);
        }
        return jsonResponse(FAKE_PULSE);
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePulse());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.pulse).toBeNull();

    await act(async () => {
      await result.current.createPulse();
    });

    expect(result.current.pulse).toEqual(FAKE_PULSE);
  });

  // ── createPulse sets pulse with ai_question ───────────────────────────

  test("createPulse sets pulse with ai_question from response", async () => {
    const pulseWithQuestion: PulseResponse = {
      ...FAKE_PULSE,
      ai_question: "What's blocking the deploy?",
    };

    const fetchMock = vi.fn(async (_path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse({}, 404);
      return jsonResponse(pulseWithQuestion, 201);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => usePulse());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.createPulse();
    });

    expect(result.current.pulse?.ai_question).toBe("What's blocking the deploy?");
  });

  // ── submitPulse calls PATCH and updates state ───────────────────────────

  test("submitPulse PATCHes and updates pulse", async () => {
    mockFetch(async (_path: string, init?: RequestInit) => {
      if (init?.method === "GET") return jsonResponse(FAKE_PULSE);
      return jsonResponse(COMPLETED_PULSE); // PATCH
    });

    const { result } = renderHook(() => usePulse());
    await waitFor(() => expect(result.current.pulse).toEqual(FAKE_PULSE));

    await act(async () => {
      await result.current.submitPulse({ sleep_quality: 4, energy_level: 3 });
    });

    expect(result.current.pulse).toEqual(COMPLETED_PULSE);
  });
});
