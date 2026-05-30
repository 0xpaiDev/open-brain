"use client";

import { useState, useEffect } from "react";
import { toast } from "sonner";
import type {
  CronStepSpan,
  LLMCallSpan,
  LLMCallRaw,
  ToolCallSpan,
  ObsEventSpan,
  TraceDetail,
} from "@/lib/types";
import { useTraceDetail, rerunTrace, replaySpan } from "@/hooks/use-trace-detail";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { SpanTree } from "./span-tree";

type SpanType = "cron_step" | "llm_call" | "tool_call" | "event";
type DetailTab = "summary" | "inputs" | "output" | "raw" | "children";

interface TraceDetailProps {
  traceId: string;
  onClose: () => void;
  onRerunComplete: (newTraceId: string) => void;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    success: "bg-primary/10 text-primary",
    failed: "bg-error/10 text-error",
    running: "bg-tertiary/10 text-tertiary",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-label ${styles[status] ?? "bg-surface-container-high text-on-surface-variant"}`}
    >
      {status}
    </span>
  );
}

function formatDurationMs(ms: number | null): string {
  if (ms === null) return "—";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatCost(costStr: string | null | undefined): string {
  if (!costStr) return "—";
  const n = parseFloat(costStr);
  if (n === 0) return "$0";
  return `$${n.toFixed(6)}`;
}

function JsonBlock({ value }: { value: Record<string, unknown> | null | undefined }) {
  if (!value) return <p className="text-xs text-on-surface-variant">—</p>;
  return (
    <pre className="text-xs text-on-surface bg-surface-container-low rounded-lg p-3 overflow-auto whitespace-pre-wrap break-words font-mono max-h-64">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-xs text-on-surface-variant w-28 flex-shrink-0">{label}</span>
      <span className="text-xs text-on-surface">{value}</span>
    </div>
  );
}

function findSpan(
  trace: TraceDetail,
  spanId: string,
  spanType: SpanType,
): CronStepSpan | LLMCallSpan | ToolCallSpan | ObsEventSpan | null {
  switch (spanType) {
    case "cron_step":
      return trace.cron_steps.find((s) => s.span_id === spanId) ?? null;
    case "llm_call":
      return trace.llm_calls.find((s) => s.span_id === spanId) ?? null;
    case "tool_call":
      return trace.tool_calls.find((s) => s.span_id === spanId) ?? null;
    case "event":
      return trace.events.find((s) => s.span_id === spanId) ?? null;
  }
}

function countChildren(trace: TraceDetail, spanId: string): number {
  return [
    ...trace.cron_steps,
    ...trace.llm_calls,
    ...trace.tool_calls,
    ...trace.events,
  ].filter((s) => s.parent_span_id === spanId).length;
}

interface SpanDetailPanelProps {
  trace: TraceDetail;
  selectedSpanId: string | null;
  selectedSpanType: SpanType | null;
  onReplaySpan: (spanId: string) => void;
  replayingSpanId: string | null;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function SpanDetailPanel({
  trace,
  selectedSpanId,
  selectedSpanType,
  onReplaySpan,
  replayingSpanId,
}: SpanDetailPanelProps) {
  const [tab, setTab] = useState<DetailTab>("summary");
  const [rawPayload, setRawPayload] = useState<LLMCallRaw | null>(null);
  const [rawLoading, setRawLoading] = useState(false);
  const [rawError, setRawError] = useState<string | null>(null);

  useEffect(() => {
    setTab("summary");
    setRawPayload(null);
  }, [selectedSpanId]);

  const span =
    selectedSpanId && selectedSpanType
      ? findSpan(trace, selectedSpanId, selectedSpanType)
      : null;

  useEffect(() => {
    if (tab !== "raw" || selectedSpanType !== "llm_call" || !selectedSpanId) {
      setRawPayload(null);
      setRawError(null);
      setRawLoading(false);
      return;
    }
    const spanObj = findSpan(trace, selectedSpanId, selectedSpanType) as LLMCallSpan | null;
    if (!spanObj) return;
    const spanId = spanObj.id;
    let cancelled = false;
    setRawLoading(true);
    setRawError(null);
    api<LLMCallRaw>("GET", `/v1/llm-calls/${spanId}`)
      .then((res) => { if (!cancelled) setRawPayload(res); })
      .catch(() => { if (!cancelled) setRawError("Failed to load raw payload"); })
      .finally(() => { if (!cancelled) setRawLoading(false); });
    return () => { cancelled = true; };
  }, [tab, selectedSpanType, selectedSpanId, trace]);

  const tabs: { id: DetailTab; label: string }[] = [
    { id: "summary", label: "Summary" },
    { id: "inputs", label: "Inputs" },
    { id: "output", label: "Output" },
    { id: "raw", label: "Raw" },
    { id: "children", label: "Children" },
  ];

  const childCount = selectedSpanId ? countChildren(trace, selectedSpanId) : 0;

  const canReplay =
    selectedSpanType === "llm_call" &&
    span != null &&
    (span as LLMCallSpan).status === "failed";

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-1 border-b border-outline-variant/20 mb-3 flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm transition-colors ${
              tab === t.id
                ? "text-primary border-b-2 border-primary"
                : "text-on-surface-variant hover:text-on-surface"
            }`}
          >
            {t.label}
            {t.id === "children" && childCount > 0 && (
              <span className="ml-1 text-xs text-on-surface-variant">
                ({childCount})
              </span>
            )}
          </button>
        ))}

        {canReplay && selectedSpanId && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            onClick={() => onReplaySpan(selectedSpanId)}
            disabled={replayingSpanId === selectedSpanId}
          >
            <span className="material-symbols-outlined text-sm">replay</span>
            {replayingSpanId === selectedSpanId ? "Replaying…" : "Replay"}
          </Button>
        )}
      </div>

      <div className="overflow-auto flex-1 space-y-2">
        {tab === "summary" && (
          <div className="space-y-2">
            {!span ? (
              <>
                <MetaRow label="Trigger" value={trace.trigger_name} />
                <MetaRow label="Type" value={trace.trigger_type} />
                <MetaRow label="Status" value={trace.status} />
                <MetaRow label="Duration" value={formatDurationMs(trace.duration_ms)} />
                <MetaRow label="Total cost" value={formatCost(trace.total_cost_usd)} />
                <MetaRow label="LLM calls" value={String(trace.llm_call_count)} />
                <MetaRow label="Tool calls" value={String(trace.tool_call_count)} />
              </>
            ) : selectedSpanType === "llm_call" ? (
              <>
                <MetaRow label="Call site" value={(span as LLMCallSpan).call_site} />
                <MetaRow label="Model" value={(span as LLMCallSpan).model} />
                <MetaRow label="Provider" value={(span as LLMCallSpan).provider} />
                <MetaRow label="Status" value={(span as LLMCallSpan).status} />
                <MetaRow label="Duration" value={formatDurationMs((span as LLMCallSpan).duration_ms)} />
                <MetaRow label="Cost" value={formatCost((span as LLMCallSpan).cost_usd)} />
                <MetaRow label="Input tokens" value={String((span as LLMCallSpan).input_tokens)} />
                <MetaRow label="Output tokens" value={String((span as LLMCallSpan).output_tokens)} />
                <MetaRow label="Stop reason" value={(span as LLMCallSpan).stop_reason ?? "—"} />
              </>
            ) : selectedSpanType === "tool_call" ? (
              <>
                <MetaRow label="Tool" value={(span as ToolCallSpan).tool_name} />
                <MetaRow label="Status" value={(span as ToolCallSpan).status} />
                <MetaRow label="Duration" value={formatDurationMs((span as ToolCallSpan).duration_ms)} />
                {(span as ToolCallSpan).is_error && (
                  <MetaRow label="Error" value={(span as ToolCallSpan).error_message ?? "unknown"} />
                )}
              </>
            ) : selectedSpanType === "cron_step" ? (
              <>
                <MetaRow label="Step" value={(span as CronStepSpan).step_name} />
                <MetaRow label="Status" value={(span as CronStepSpan).status} />
                <MetaRow label="Duration" value={formatDurationMs((span as CronStepSpan).duration_ms)} />
                {(span as CronStepSpan).error_message && (
                  <MetaRow label="Error" value={(span as CronStepSpan).error_message!} />
                )}
              </>
            ) : selectedSpanType === "event" ? (
              <>
                <MetaRow label="Event type" value={(span as ObsEventSpan).event_type} />
                <MetaRow label="Level" value={(span as ObsEventSpan).level} />
                <MetaRow label="Occurred at" value={formatTime((span as ObsEventSpan).occurred_at)} />
              </>
            ) : null}
          </div>
        )}

        {tab === "inputs" && (
          <div>
            {!span ? (
              <JsonBlock value={trace.trigger_metadata ?? undefined} />
            ) : selectedSpanType === "llm_call" ? (
              <JsonBlock value={(span as LLMCallSpan).request_summary} />
            ) : selectedSpanType === "tool_call" ? (
              <JsonBlock value={(span as ToolCallSpan).args} />
            ) : selectedSpanType === "cron_step" ? (
              <JsonBlock value={(span as CronStepSpan).step_metadata} />
            ) : selectedSpanType === "event" ? (
              <JsonBlock value={(span as ObsEventSpan).payload} />
            ) : (
              <p className="text-xs text-on-surface-variant">—</p>
            )}
          </div>
        )}

        {tab === "output" && (
          <div>
            {!span ? (
              <p className="text-xs text-on-surface-variant">—</p>
            ) : selectedSpanType === "llm_call" ? (
              <JsonBlock value={(span as LLMCallSpan).response_summary ?? undefined} />
            ) : selectedSpanType === "tool_call" ? (
              <JsonBlock value={(span as ToolCallSpan).result ?? undefined} />
            ) : (
              <p className="text-xs text-on-surface-variant">—</p>
            )}
          </div>
        )}

        {tab === "raw" && (
          <div className="space-y-3">
            {selectedSpanType === "llm_call" ? (
              rawLoading ? (
                <p className="text-xs text-on-surface-variant">Loading…</p>
              ) : rawError ? (
                <p className="text-xs text-error">{rawError}</p>
              ) : rawPayload ? (
                <>
                  <div>
                    <p className="text-xs text-on-surface-variant mb-1">Request</p>
                    <JsonBlock value={rawPayload.raw_request ?? rawPayload.request_summary} />
                  </div>
                  <div>
                    <p className="text-xs text-on-surface-variant mb-1">Response</p>
                    <JsonBlock value={rawPayload.raw_response ?? rawPayload.response_summary ?? undefined} />
                  </div>
                </>
              ) : null
            ) : (
              <p className="text-xs text-on-surface-variant">
                Raw data is only available for LLM calls.
              </p>
            )}
          </div>
        )}

        {tab === "children" && (
          <div>
            {childCount === 0 ? (
              <p className="text-xs text-on-surface-variant">No child spans.</p>
            ) : (
              <p className="text-xs text-on-surface-variant">
                {childCount} child span{childCount === 1 ? "" : "s"}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function TraceDetailPanel({
  traceId,
  onClose,
  onRerunComplete,
}: TraceDetailProps) {
  const { trace, loading, error } = useTraceDetail(traceId);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [selectedSpanType, setSelectedSpanType] = useState<SpanType | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const [replayingSpanId, setReplayingSpanId] = useState<string | null>(null);

  function handleSpanSelect(spanId: string, spanType: SpanType) {
    setSelectedSpanId(spanId);
    setSelectedSpanType(spanType);
  }

  async function handleRerun() {
    if (rerunning) return;
    setRerunning(true);
    try {
      const result = await rerunTrace(traceId);
      toast.success(`Rerun started: ${result.new_trace_id}`);
      onRerunComplete(result.new_trace_id);
    } catch {
      toast.error("Failed to start rerun");
    } finally {
      setRerunning(false);
    }
  }

  async function handleReplay(spanId: string) {
    if (replayingSpanId) return;
    setReplayingSpanId(spanId);
    try {
      const result = await replaySpan(spanId);
      toast.success(`Replay started: ${result.new_span_id}`);
    } catch {
      toast.error("Failed to start replay");
    } finally {
      setReplayingSpanId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <span className="material-symbols-outlined text-on-surface-variant text-3xl animate-spin">
          progress_activity
        </span>
      </div>
    );
  }

  if (error || !trace) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-center">
        <span className="material-symbols-outlined text-error text-2xl mb-2">
          error
        </span>
        <p className="text-sm text-error">{error ?? "Trace not found"}</p>
        <Button variant="ghost" size="sm" onClick={onClose} className="mt-3">
          Close
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-4 flex-shrink-0">
        <span className="text-sm font-medium text-on-surface truncate flex-1 min-w-0">
          {trace.trigger_name}
        </span>
        <StatusBadge status={trace.status} />
        <Button
          variant="outline"
          size="sm"
          onClick={handleRerun}
          disabled={rerunning}
        >
          <span className="material-symbols-outlined text-sm">replay</span>
          {rerunning ? "Starting…" : "Rerun"}
        </Button>
        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close">
          <span className="material-symbols-outlined text-sm">close</span>
        </Button>
      </div>

      <div className="flex flex-col md:flex-row gap-4 flex-1 min-h-0 overflow-hidden">
        <div className="md:w-2/5 overflow-auto border border-outline-variant/20 rounded-xl p-2">
          <SpanTree
            trace={trace}
            selectedSpanId={selectedSpanId}
            onSpanSelect={handleSpanSelect}
          />
        </div>

        <div className="md:w-3/5 overflow-hidden flex flex-col bg-surface-container rounded-2xl p-4">
          <SpanDetailPanel
            trace={trace}
            selectedSpanId={selectedSpanId}
            selectedSpanType={selectedSpanType}
            onReplaySpan={handleReplay}
            replayingSpanId={replayingSpanId}
          />
        </div>
      </div>
    </div>
  );
}
