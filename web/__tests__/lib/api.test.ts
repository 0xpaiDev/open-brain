import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getApiKey,
  setApiKey,
  removeApiKey,
  api,
  ApiError,
  validateApiKey,
} from "@/lib/api";

// ── T-20: localStorage key lifecycle ────────────────────────────────────────

describe("API key lifecycle", () => {
  test("getApiKey returns null when not set", () => {
    expect(getApiKey()).toBeNull();
  });

  test("setApiKey persists and getApiKey retrieves", () => {
    setApiKey("test-key-123");
    expect(getApiKey()).toBe("test-key-123");
  });

  test("removeApiKey clears stored key", () => {
    setApiKey("test-key-123");
    removeApiKey();
    expect(getApiKey()).toBeNull();
  });

  test("setApiKey overwrites previous key", () => {
    setApiKey("first");
    setApiKey("second");
    expect(getApiKey()).toBe("second");
  });
});

// ── T-21: api() throws ApiError on non-ok ────────────────────────────────────

describe("api() error handling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("throws ApiError with correct status on 500", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    );
    setApiKey("k");

    await expect(api("GET", "/v1/test")).rejects.toThrow(ApiError);
    try {
      await api("GET", "/v1/test");
    } catch (e) {
      expect(e).toBeInstanceOf(ApiError);
      expect((e as ApiError).status).toBe(500);
    }
  });

  test("throws ApiError when no API key is set", async () => {
    await expect(api("GET", "/v1/test")).rejects.toThrow(ApiError);
    try {
      await api("GET", "/v1/test");
    } catch (e) {
      expect((e as ApiError).status).toBe(401);
    }
  });

  test("includes X-API-Key header in requests", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal("fetch", mockFetch);
    setApiKey("my-secret");

    await api("GET", "/v1/test");

    expect(mockFetch).toHaveBeenCalledWith("/v1/test", {
      method: "GET",
      headers: { "X-API-Key": "my-secret" },
      body: undefined,
    });
  });

  test("sends Content-Type and JSON body when body is provided", async () => {
    const mockFetch = vi
      .fn()
      .mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
    vi.stubGlobal("fetch", mockFetch);
    setApiKey("k");

    await api("POST", "/v1/test", { foo: "bar" });

    expect(mockFetch).toHaveBeenCalledWith("/v1/test", {
      method: "POST",
      headers: { "X-API-Key": "k", "Content-Type": "application/json" },
      body: '{"foo":"bar"}',
    });
  });

  test("returns undefined for 204 No Content", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 204 }),
    );
    setApiKey("k");

    const result = await api("DELETE", "/v1/test");
    expect(result).toBeUndefined();
  });
});

// ── T-22: 401 auto-removes API key ──────────────────────────────────────────

describe("api() 401 auto-logout", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("removes API key from localStorage on 401", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401 }),
    );
    setApiKey("bad-key");
    expect(getApiKey()).toBe("bad-key");

    await expect(api("GET", "/v1/test")).rejects.toThrow();
    expect(getApiKey()).toBeNull();
  });
});

// ── T-23: validateApiKey ────────────────────────────────────────────────────

describe("validateApiKey", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("returns true on 200 (pulse exists)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 200 }),
    );
    expect(await validateApiKey("good-key")).toBe(true);
  });

  test("returns true on 404 (no pulse but key valid)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 404 }),
    );
    expect(await validateApiKey("good-key")).toBe(true);
  });

  test("returns false on 401 (invalid key)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ status: 401 }),
    );
    expect(await validateApiKey("bad-key")).toBe(false);
  });

  test("sends the provided key as X-API-Key header", async () => {
    const mockFetch = vi.fn().mockResolvedValue({ status: 200 });
    vi.stubGlobal("fetch", mockFetch);

    await validateApiKey("check-this-key");

    expect(mockFetch).toHaveBeenCalledWith("/v1/pulse/today", {
      method: "GET",
      headers: { "X-API-Key": "check-this-key" },
    });
  });
});

// ── T-29: Network error propagation ────────────────────────────────────────

describe("api() network errors", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("throws TypeError when fetch rejects (network down)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    setApiKey("k");

    await expect(api("GET", "/v1/test")).rejects.toThrow(TypeError);
    await expect(api("GET", "/v1/test")).rejects.toThrow("Failed to fetch");
  });

  // T-30: Malformed JSON response
  test("throws SyntaxError when response JSON is malformed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new SyntaxError("Unexpected token");
        },
      }),
    );
    setApiKey("k");

    await expect(api("GET", "/v1/test")).rejects.toThrow(SyntaxError);
  });
});

// ── T-31: SSR guard ────────────────────────────────────────────────────────

describe("getApiKey SSR", () => {
  test("returns null when window is undefined", () => {
    const original = globalThis.window;
    // @ts-expect-error - intentionally removing window for SSR test
    delete globalThis.window;
    try {
      expect(getApiKey()).toBeNull();
    } finally {
      globalThis.window = original;
    }
  });
});
