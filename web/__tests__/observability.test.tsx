/**
 * Observability — Vitest unit tests
 * Covers: useTraces, useKpis hooks + KpiTiles, TraceList, SpanTree, TraceDetailPanel components
 */

import { describe, test, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { render, screen, fireEvent } from "@testing-library/react";
import { setApiKey } from "@/lib/api";
import { useTraceDetail } from "@/hooks/use-trace-detail";
import type {
  TraceListResponse,
  TraceListItem,
  KpiResponse,
  TraceDetail,
  LLMCallRaw,
} from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────────────

function jsonRes(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function makeTrace(overrides: Partial<TraceListItem> = {}): TraceListItem {
  return {
    id: "trace-1",
    trigger_type: "cron",
    trigger_name: "memory_flywheel",
    status: "success",
    started_at: "2026-05-25T08:00:00Z",
    finished_at: "2026-05-25T08:01:00Z",
    duration_ms: 60000,
    total_cost_usd: "0.001234",
    total_input_tokens: 100,
    total_output_tokens: 50,
    total_cache_read_tokens: 0,
    total_cache_creation_tokens: 0,
    llm_call_count: 1,
    tool_call_count: 2,
    error_message: null,
    error_class: null,
    causal_parent_trace_id: null,
    rerun_of_trace_id: null,
    ...overrides,
  };
}

const SAMPLE_KPIS: KpiResponse = {
  cost_in_range_usd: "0.012345",
  sparkline_7d: [],
  cache_hit_rate_24h: null,
  failure_count_24h: 0,
  oldest_dead_letter_age_seconds: null,
};

const SAMPLE_TRACE_DETAIL: TraceDetail = {
  ...makeTrace(),
  trigger_metadata: null,
  cron_steps: [
    {
      id: "cs-1",
      span_id: "span-cs-1",
      parent_span_id: null,
      step_name: "distill",
      status: "success",
      started_at: "2026-05-25T08:00:00Z",
      finished_at: "2026-05-25T08:00:10Z",
      duration_ms: 10000,
      error_message: null,
      error_class: null,
      step_metadata: {},
    },
  ],
  llm_calls: [
    {
      id: "llm-1",
      span_id: "span-llm-1",
      parent_span_id: "span-cs-1",
      call_site: "distill_memories",
      model: "claude-haiku-4-5",
      provider: "anthropic",
      status: "success",
      started_at: "2026-05-25T08:00:02Z",
      finished_at: "2026-05-25T08:00:09Z",
      duration_ms: 7000,
      input_tokens: 100,
      output_tokens: 50,
      cache_read_input_tokens: 0,
      cache_creation_input_tokens: 0,
      stop_reason: "end_turn",
      cost_usd: "0.001",
      pricing_version: "v1",
      request_summary: {},
      response_summary: null,
      error_message: null,
      error_class: null,
    },
  ],
  tool_calls: [],
  events: [],
};

// ─────────────────────────────────────────────────────────────────────────────
// 1. useTraces — initial fetch with correct URL + items populated
// ─────────────────────────────────────────────────────────────────────────────

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

describe("useTraces hook", () => {
  beforeEach(() => {
    vi.resetModules();
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("fetches /v1/traces on mount and populates items", async () => {
    const response: TraceListResponse = {
      items: [makeTrace()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const fetchMock = vi.fn(async () => jsonRes(response));
    vi.stubGlobal("fetch", fetchMock);

    const { useTraces } = await import("@/hooks/use-traces");
    const { result } = renderHook(() => useTraces({}));

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.items).toHaveLength(1);
    expect(result.current.items[0].id).toBe("trace-1");
    expect(result.current.total).toBe(1);
    // URL must contain /v1/traces
    const calledUrl: string = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("/v1/traces");
    expect(calledUrl).toContain("page=1");
  });

  // ── 2. refresh resets to page 1 ───────────────────────────────────────────

  test("refresh resets to page 1", async () => {
    const response: TraceListResponse = {
      items: [makeTrace()],
      total: 1,
      page: 1,
      page_size: 50,
    };
    const fetchMock = vi.fn(async () => jsonRes(response));
    vi.stubGlobal("fetch", fetchMock);

    const { useTraces } = await import("@/hooks/use-traces");
    const { result } = renderHook(() => useTraces({}));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const callsBefore = fetchMock.mock.calls.length;

    await act(async () => {
      await result.current.refresh();
    });

    // refresh triggers a new fetch
    expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBefore);
    // page should be back at 1
    expect(result.current.page).toBe(1);
  });

  // ── 3. loadMore blocked when loading ─────────────────────────────────────

  test("loadMore is blocked when loading is true", async () => {
    let resolveFirst!: (v: Response) => void;
    const firstPromise = new Promise<Response>((res) => {
      resolveFirst = res;
    });

    const fetchMock = vi.fn(() => firstPromise);
    vi.stubGlobal("fetch", fetchMock);

    const { useTraces } = await import("@/hooks/use-traces");
    const { result } = renderHook(() =>
      useTraces({ trigger_type: "cron", status: null }),
    );

    // Still loading — loadMore should be a no-op
    expect(result.current.loading).toBe(true);
    const callsBefore = fetchMock.mock.calls.length;
    await act(async () => {
      await result.current.loadMore();
    });
    expect(fetchMock.mock.calls.length).toBe(callsBefore); // no extra call

    // resolve so the hook can clean up
    resolveFirst(
      jsonRes({ items: [], total: 0, page: 1, page_size: 50 }),
    );
    await waitFor(() => expect(result.current.loading).toBe(false));
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 4. useKpis — fetches /v1/traces/kpis
// ─────────────────────────────────────────────────────────────────────────────

describe("useKpis hook", () => {
  beforeEach(() => {
    vi.resetModules();
    setApiKey("test-key");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  test("fetches /v1/traces/kpis and returns kpis", async () => {
    const fetchMock = vi.fn(async () => jsonRes(SAMPLE_KPIS));
    vi.stubGlobal("fetch", fetchMock);

    const { useKpis } = await import("@/hooks/use-traces");
    const { result } = renderHook(() => useKpis());

    await waitFor(() => expect(result.current.loading).toBe(false));

    expect(result.current.kpis).not.toBeNull();
    expect(result.current.kpis?.cost_in_range_usd).toBe("0.012345");

    const calledUrl: string = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("/v1/traces/kpis");
  });

  test("passes date_from and date_to as query params when provided", async () => {
    const fetchMock = vi.fn(async () => jsonRes(SAMPLE_KPIS));
    vi.stubGlobal("fetch", fetchMock);

    const { useKpis } = await import("@/hooks/use-traces");
    const { result } = renderHook(() =>
      useKpis({ date_from: "2026-05-25", date_to: "2026-05-25" }),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));

    const calledUrl: string = fetchMock.mock.calls[0][0];
    expect(calledUrl).toContain("date_from=2026-05-25");
    expect(calledUrl).toContain("date_to=2026-05-25");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 5-7. KpiTiles component
// ─────────────────────────────────────────────────────────────────────────────

describe("KpiTiles component", () => {
  // 5. Loading skeleton
  test("renders loading skeleton when loading=true and no kpis", async () => {
    const { KpiTiles } = await import(
      "@/components/observability/kpi-tiles"
    );
    const { container } = render(<KpiTiles kpis={null} loading={true} />);
    // Skeleton tiles use animate-pulse
    const pulseDivs = container.querySelectorAll(".animate-pulse");
    expect(pulseDivs.length).toBeGreaterThan(0);
    // No cost value rendered
    expect(screen.queryByText(/\$0\./)).toBeNull();
  });

  // 6. Renders cost value when kpis provided
  test("renders cost value when kpis provided", async () => {
    const { KpiTiles } = await import(
      "@/components/observability/kpi-tiles"
    );
    render(<KpiTiles kpis={SAMPLE_KPIS} loading={false} />);
    // formatCost("0.012345") → "$0.012345"
    expect(screen.getByText("$0.012345")).toBeDefined();
  });

  // 7. Shows "—" for null cache_hit_rate
  test('shows "—" for null cache_hit_rate', async () => {
    const { KpiTiles } = await import(
      "@/components/observability/kpi-tiles"
    );
    render(
      <KpiTiles
        kpis={{ ...SAMPLE_KPIS, cache_hit_rate_24h: null }}
        loading={false}
      />,
    );
    // "Cache hit rate" tile shows "—"
    const cacheLabel = screen.getByText("Cache hit rate");
    const tile = cacheLabel.closest("div")!;
    expect(tile.textContent).toContain("—");
  });

  // 8. Failure count is red when > 0
  test("failure count text is styled as error when > 0", async () => {
    const { KpiTiles } = await import(
      "@/components/observability/kpi-tiles"
    );
    render(
      <KpiTiles
        kpis={{ ...SAMPLE_KPIS, failure_count_24h: 3 }}
        loading={false}
      />,
    );
    // The count element should have text-error class
    const countEl = screen.getByText("3");
    expect(countEl.className).toContain("text-error");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 9-11. TraceList component
// ─────────────────────────────────────────────────────────────────────────────

const NOOP_ASYNC = async () => {};

describe("TraceList component", () => {
  const baseProps = {
    total: 0,
    loading: false,
    error: null,
    hasMore: false,
    loadMore: NOOP_ASYNC,
    filters: {},
    onFiltersChange: vi.fn(),
    onTraceClick: vi.fn(),
    selectedTraceId: null,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // 9. Renders rows for provided items
  test("renders a row for each provided trace item", async () => {
    const { TraceList } = await import(
      "@/components/observability/trace-list"
    );
    const items = [
      makeTrace({ id: "t-1", trigger_name: "job_alpha" }),
      makeTrace({ id: "t-2", trigger_name: "job_beta" }),
    ];
    render(<TraceList {...baseProps} items={items} total={2} />);
    expect(screen.getByText("job_alpha")).toBeDefined();
    expect(screen.getByText("job_beta")).toBeDefined();
  });

  // 10. Highlights selected row
  test("highlights the selected trace row", async () => {
    const { TraceList } = await import(
      "@/components/observability/trace-list"
    );
    const items = [
      makeTrace({ id: "t-sel", trigger_name: "selected_job" }),
    ];
    render(
      <TraceList
        {...baseProps}
        items={items}
        total={1}
        selectedTraceId="t-sel"
      />,
    );
    // The row button should have the ring/bg selection class
    const rowBtn = screen.getByText("selected_job").closest("button")!;
    expect(rowBtn.className).toContain("ring-1");
  });

  // 11a. Date inputs render with correct aria-labels
  test("renders From date and To date inputs", async () => {
    const { TraceList } = await import(
      "@/components/observability/trace-list"
    );
    render(<TraceList {...baseProps} items={[]} total={0} />);
    expect(screen.getByLabelText("From date")).toBeDefined();
    expect(screen.getByLabelText("To date")).toBeDefined();
  });

  // 11. Calls onTraceClick when a row is clicked
  test("calls onTraceClick with the trace id when clicked", async () => {
    const { TraceList } = await import(
      "@/components/observability/trace-list"
    );
    const onTraceClick = vi.fn();
    const items = [makeTrace({ id: "t-click", trigger_name: "clickable_job" })];
    render(
      <TraceList
        {...baseProps}
        items={items}
        total={1}
        onTraceClick={onTraceClick}
      />,
    );
    fireEvent.click(screen.getByText("clickable_job").closest("button")!);
    expect(onTraceClick).toHaveBeenCalledWith("t-click");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 12-13. SpanTree component
// ─────────────────────────────────────────────────────────────────────────────

describe("SpanTree component", () => {
  // 12. Renders span items with correct icons
  test("renders span items with icon text", async () => {
    const { SpanTree } = await import(
      "@/components/observability/span-tree"
    );
    render(
      <SpanTree
        trace={SAMPLE_TRACE_DETAIL}
        selectedSpanId={null}
        onSpanSelect={vi.fn()}
      />,
    );
    // cron_step icon = "schedule", llm_call icon = "psychology"
    expect(screen.getByText("schedule")).toBeDefined();
    expect(screen.getByText("psychology")).toBeDefined();
    // Labels should be present
    expect(screen.getByText("distill")).toBeDefined();
    expect(screen.getByText("distill_memories")).toBeDefined();
  });

  // 13. Collapse/expand toggle hides/shows children
  test("collapse button hides children, expand shows them again", async () => {
    const { SpanTree } = await import(
      "@/components/observability/span-tree"
    );
    render(
      <SpanTree
        trace={SAMPLE_TRACE_DETAIL}
        selectedSpanId={null}
        onSpanSelect={vi.fn()}
      />,
    );

    // Initially child (llm_call) should be visible
    expect(screen.getByText("distill_memories")).toBeDefined();

    // Collapse the parent cron_step
    const collapseBtn = screen.getByLabelText("Collapse");
    fireEvent.click(collapseBtn);

    // Child span label should no longer be in the document
    expect(screen.queryByText("distill_memories")).toBeNull();

    // Expand again
    const expandBtn = screen.getByLabelText("Expand");
    fireEvent.click(expandBtn);

    expect(screen.getByText("distill_memories")).toBeDefined();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 14-16. TraceDetailPanel component
// ─────────────────────────────────────────────────────────────────────────────

// Mock the useTraceDetail hook so TraceDetailPanel doesn't need real network
vi.mock("@/hooks/use-trace-detail", () => ({
  useTraceDetail: vi.fn(),
  rerunTrace: vi.fn().mockResolvedValue({ new_trace_id: "new-123" }),
  replaySpan: vi.fn().mockResolvedValue({ new_span_id: "ns-1", status: "success" }),
}));

describe("TraceDetailPanel component", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // 14. Shows loading spinner while fetching
  test("shows loading spinner when useTraceDetail returns loading=true", async () => {
    (useTraceDetail as ReturnType<typeof vi.fn>).mockReturnValue({
      trace: null,
      loading: true,
      error: null,
      refresh: vi.fn(),
    });

    const { TraceDetailPanel } = await import(
      "@/components/observability/trace-detail"
    );
    render(
      <TraceDetailPanel
        traceId="trace-1"
        onClose={vi.fn()}
        onRerunComplete={vi.fn()}
      />,
    );

    // Loading spinner uses animate-spin
    const spinner = document.querySelector(".animate-spin");
    expect(spinner).not.toBeNull();
  });

  // 15. Rerun button always visible
  test("Rerun button is visible when trace loaded", async () => {
    (useTraceDetail as ReturnType<typeof vi.fn>).mockReturnValue({
      trace: SAMPLE_TRACE_DETAIL,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    const { TraceDetailPanel } = await import(
      "@/components/observability/trace-detail"
    );
    render(
      <TraceDetailPanel
        traceId="trace-1"
        onClose={vi.fn()}
        onRerunComplete={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /rerun/i })).toBeDefined();
  });

  // 17. Raw tab lazily fetches /v1/llm-calls/{id} when an llm_call span is selected
  test("Raw tab fetches /v1/llm-calls/{id} and renders payload", async () => {
    const rawPayload: LLMCallRaw = {
      id: "llm-1",
      raw_request: { model: "claude-haiku-4-5", messages: [{ role: "user", content: "hi" }] },
      raw_response: { content: "hello" },
      request_summary: { message_count: 1 },
      response_summary: null,
    };

    (useTraceDetail as ReturnType<typeof vi.fn>).mockReturnValue({
      trace: SAMPLE_TRACE_DETAIL,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    // Mock fetch so the api() call to /v1/llm-calls/{id} returns the payload
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes("/v1/llm-calls/")) {
        return jsonRes(rawPayload);
      }
      return jsonRes({});
    });
    vi.stubGlobal("fetch", fetchMock);
    setApiKey("test-key");

    const { TraceDetailPanel } = await import(
      "@/components/observability/trace-detail"
    );
    render(
      <TraceDetailPanel
        traceId="trace-1"
        onClose={vi.fn()}
        onRerunComplete={vi.fn()}
      />,
    );

    // Select the llm_call span
    const llmSpanBtn = screen.getByText("distill_memories").closest("button")!;
    fireEvent.click(llmSpanBtn);

    // Click the Raw tab
    const rawTab = screen.getByRole("button", { name: "Raw" });
    fireEvent.click(rawTab);

    // API should have been called with the correct URL
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/v1/llm-calls/llm-1"),
        expect.anything(),
      );
    });

    // Rendered content: "Request" and "Response" labels should appear
    await waitFor(() => {
      expect(screen.getByText("Request")).toBeDefined();
      expect(screen.getByText("Response")).toBeDefined();
    });

    vi.unstubAllGlobals();
  });

  // 16. Replay button visible only for failed llm_call span
  test("Replay button visible only when selected span is a failed llm_call", async () => {
    const failedLlmTrace: TraceDetail = {
      ...SAMPLE_TRACE_DETAIL,
      llm_calls: [
        {
          ...SAMPLE_TRACE_DETAIL.llm_calls[0],
          span_id: "span-llm-failed",
          status: "failed",
        },
      ],
    };

    (useTraceDetail as ReturnType<typeof vi.fn>).mockReturnValue({
      trace: failedLlmTrace,
      loading: false,
      error: null,
      refresh: vi.fn(),
    });

    const { TraceDetailPanel } = await import(
      "@/components/observability/trace-detail"
    );
    render(
      <TraceDetailPanel
        traceId="trace-1"
        onClose={vi.fn()}
        onRerunComplete={vi.fn()}
      />,
    );

    // Helper: find a button whose visible text ends with "Replay" (not "Rerun")
    // The material-icon span adds "replay" before the label; we match the full
    // accessible name which becomes "replay Replay" for the replay action and
    // "replay Starting…/Rerun" for the rerun action.
    function getReplayButton() {
      return screen.queryAllByRole("button").find((btn) => {
        // visible text nodes (not icon text)
        const text = btn.textContent ?? "";
        // Button has both icon text "replay" and visible label "Replay"
        // Rerun button has icon text "replay" and visible label "Rerun"
        return text.includes("Replay") && !text.includes("Rerun");
      }) ?? null;
    }

    // Initially no span selected → no Replay button
    await waitFor(() => {
      expect(getReplayButton()).toBeNull();
    });

    // Select the failed llm_call span
    const llmSpanBtn = screen.getByText("distill_memories").closest("button")!;
    fireEvent.click(llmSpanBtn);

    // Now Replay button should appear
    await waitFor(() => {
      expect(getReplayButton()).not.toBeNull();
    });

    // For comparison: if we select the cron_step (not an llm_call), no Replay
    const cronSpanBtn = screen.getByText("distill").closest("button")!;
    fireEvent.click(cronSpanBtn);

    await waitFor(() => {
      expect(getReplayButton()).toBeNull();
    });
  });
});
