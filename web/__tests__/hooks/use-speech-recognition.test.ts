import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// Mock SpeechRecognition instance
function createMockRecognition() {
  return {
    continuous: false,
    interimResults: false,
    lang: "",
    start: vi.fn(),
    stop: vi.fn(),
    abort: vi.fn(),
    onresult: null as ((event: any) => void) | null,
    onerror: null as ((event: any) => void) | null,
    onend: null as (() => void) | null,
  };
}

let mockRecognition: ReturnType<typeof createMockRecognition>;

beforeEach(() => {
  mockRecognition = createMockRecognition();
  // Must use function() not arrow — vi needs it to be constructable with `new`
  vi.stubGlobal(
    "webkitSpeechRecognition",
    vi.fn(function () { return mockRecognition; }),
  );
  localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

// Dynamic import so the module picks up our global stubs
async function importHook() {
  // Clear module cache to pick up fresh globals
  vi.resetModules();
  const mod = await import("@/hooks/use-speech-recognition");
  return mod.useSpeechRecognition;
}

describe("useSpeechRecognition", () => {
  test("isSupported is true when webkitSpeechRecognition exists", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());
    expect(result.current.isSupported).toBe(true);
  });

  test("isSupported is false when no SpeechRecognition API", async () => {
    vi.unstubAllGlobals();
    // Ensure neither variant exists
    vi.stubGlobal("webkitSpeechRecognition", undefined);
    vi.stubGlobal("SpeechRecognition", undefined);

    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());
    expect(result.current.isSupported).toBe(false);
  });

  test("startListening starts recognition and sets isListening", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    expect(result.current.isListening).toBe(true);
    expect(mockRecognition.start).toHaveBeenCalled();
    expect(mockRecognition.continuous).toBe(true);
    expect(mockRecognition.interimResults).toBe(true);
  });

  test("stopListening stops recognition and clears isListening", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());
    act(() => result.current.stopListening());

    expect(result.current.isListening).toBe(false);
    expect(mockRecognition.stop).toHaveBeenCalled();
  });

  test("accumulates final transcript results", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    // Simulate a final result
    act(() => {
      mockRecognition.onresult?.({
        resultIndex: 0,
        results: {
          length: 1,
          0: { isFinal: true, length: 1, 0: { transcript: "hello world", confidence: 0.95 } },
          item: (i: number) => ({ isFinal: true, length: 1, 0: { transcript: "hello world", confidence: 0.95 } }),
        },
      });
    });

    expect(result.current.transcript).toBe("hello world");
  });

  test("shows interim transcript separately", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    // Simulate an interim result
    act(() => {
      mockRecognition.onresult?.({
        resultIndex: 0,
        results: {
          length: 1,
          0: { isFinal: false, length: 1, 0: { transcript: "hel", confidence: 0.5 } },
          item: (i: number) => ({ isFinal: false, length: 1, 0: { transcript: "hel", confidence: 0.5 } }),
        },
      });
    });

    expect(result.current.interimTranscript).toBe("hel");
    expect(result.current.transcript).toBe("");
  });

  test("sets error on not-allowed and stops listening", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    act(() => {
      mockRecognition.onerror?.({ error: "not-allowed", message: "Permission denied" });
    });

    expect(result.current.error).toContain("Microphone access denied");
    expect(result.current.isListening).toBe(false);
  });

  test("reads voice language from localStorage", async () => {
    localStorage.setItem("ob_voice_lang", "lt-LT");

    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    expect(mockRecognition.lang).toBe("lt-LT");
  });

  test("defaults to en-US when no localStorage value", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    expect(mockRecognition.lang).toBe("en-US");
  });

  test("resetTranscript clears all state", async () => {
    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());

    act(() => {
      mockRecognition.onresult?.({
        resultIndex: 0,
        results: {
          length: 1,
          0: { isFinal: true, length: 1, 0: { transcript: "test", confidence: 0.9 } },
          item: (i: number) => ({ isFinal: true, length: 1, 0: { transcript: "test", confidence: 0.9 } }),
        },
      });
    });

    expect(result.current.transcript).toBe("test");

    act(() => result.current.resetTranscript());

    expect(result.current.transcript).toBe("");
    expect(result.current.interimTranscript).toBe("");
    expect(result.current.error).toBeNull();
  });

  test("auto-stops after 5 minute timeout", async () => {
    vi.useFakeTimers();

    const useSpeechRecognition = await importHook();
    const { result } = renderHook(() => useSpeechRecognition());

    act(() => result.current.startListening());
    expect(result.current.isListening).toBe(true);

    // Advance past the 5-minute limit
    act(() => vi.advanceTimersByTime(5 * 60 * 1000 + 100));

    expect(result.current.isListening).toBe(false);
    expect(result.current.error).toContain("5 minute limit");

    vi.useRealTimers();
  });
});
