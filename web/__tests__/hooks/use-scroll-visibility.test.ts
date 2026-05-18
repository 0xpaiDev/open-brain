import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

async function importHook() {
  vi.resetModules();
  const mod = await import("@/hooks/use-scroll-visibility");
  return mod.useScrollVisibility;
}

describe("useScrollVisibility", () => {
  beforeEach(() => {
    vi.spyOn(window, "addEventListener");
    vi.spyOn(window, "removeEventListener");
    Object.defineProperty(window, "scrollY", { writable: true, value: 0 });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("starts visible", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());
    expect(result.current).toBe(true);
  });

  test("registers a scroll listener on mount", async () => {
    const useScrollVisibility = await importHook();
    renderHook(() => useScrollVisibility());
    expect(window.addEventListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function),
      { passive: true }
    );
  });

  test("removes scroll listener on unmount", async () => {
    const useScrollVisibility = await importHook();
    const { unmount } = renderHook(() => useScrollVisibility());
    unmount();
    expect(window.removeEventListener).toHaveBeenCalledWith(
      "scroll",
      expect.any(Function)
    );
  });

  test("hides when scrolling down more than 10px", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    act(() => {
      (window as any).scrollY = 50;
      handler();
    });

    expect(result.current).toBe(false);
  });

  test("shows when scrolling up after scrolling down", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    act(() => {
      (window as any).scrollY = 50;
      handler();
    });
    expect(result.current).toBe(false);

    act(() => {
      (window as any).scrollY = 30;
      handler();
    });
    expect(result.current).toBe(true);
  });

  test("does not hide for small downward scroll (<= 10px)", async () => {
    const useScrollVisibility = await importHook();
    const { result } = renderHook(() => useScrollVisibility());

    const [, handler] = (window.addEventListener as any).mock.calls.find(
      ([evt]: [string]) => evt === "scroll"
    );

    act(() => {
      (window as any).scrollY = 8;
      handler();
    });

    expect(result.current).toBe(true);
  });
});
