"use client";

import { useState } from "react";
import type {
  TraceDetail,
  CronStepSpan,
  LLMCallSpan,
  ToolCallSpan,
  ObsEventSpan,
} from "@/lib/types";

type SpanType = "cron_step" | "llm_call" | "tool_call" | "event";

interface SpanTreeProps {
  trace: TraceDetail;
  selectedSpanId: string | null;
  onSpanSelect: (spanId: string, spanType: SpanType) => void;
}

interface SpanNode {
  spanId: string;
  parentSpanId: string | null;
  spanType: SpanType;
  label: string;
  status: string;
  durationMs: number | null;
  children: SpanNode[];
}

function getIcon(spanType: SpanType): string {
  switch (spanType) {
    case "cron_step":
      return "schedule";
    case "llm_call":
      return "psychology";
    case "tool_call":
      return "build";
    case "event":
      return "info";
  }
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    success: "bg-primary/10 text-primary",
    failed: "bg-error/10 text-error",
    running: "bg-tertiary/10 text-tertiary",
  };
  return (
    <span
      className={`inline-flex items-center rounded-full px-1.5 py-0 text-xs ${styles[status] ?? "bg-surface-container-high text-on-surface-variant"}`}
    >
      {status}
    </span>
  );
}

function formatDurationMs(ms: number | null): string {
  if (ms === null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function SpanRow({
  node,
  depth,
  selectedSpanId,
  onSpanSelect,
}: {
  node: SpanNode;
  depth: number;
  selectedSpanId: string | null;
  onSpanSelect: (spanId: string, spanType: SpanType) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasChildren = node.children.length > 0;
  const isSelected = selectedSpanId === node.spanId;

  return (
    <div>
      <div
        className={`flex items-center gap-1.5 px-2 py-1 rounded-lg cursor-pointer hover:bg-surface-container-low transition-colors ${
          isSelected ? "bg-primary/10" : ""
        }`}
        style={{ paddingLeft: `${8 + depth * 20}px` }}
        onClick={() => onSpanSelect(node.spanId, node.spanType)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            onSpanSelect(node.spanId, node.spanType);
          }
        }}
      >
        {hasChildren ? (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              setOpen((v) => !v);
            }}
            className="text-on-surface-variant hover:text-on-surface transition-colors flex-shrink-0"
            aria-label={open ? "Collapse" : "Expand"}
          >
            <span className="material-symbols-outlined text-sm">
              {open ? "expand_more" : "chevron_right"}
            </span>
          </button>
        ) : (
          <span className="w-4 flex-shrink-0" />
        )}

        <span className="material-symbols-outlined text-sm text-on-surface-variant flex-shrink-0">
          {getIcon(node.spanType)}
        </span>

        <span className="text-sm text-on-surface truncate flex-1 min-w-0">
          {node.label}
        </span>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          <StatusBadge status={node.status} />
          {node.durationMs !== null && (
            <span className="text-xs text-on-surface-variant">
              {formatDurationMs(node.durationMs)}
            </span>
          )}
        </div>
      </div>

      {hasChildren && open && (
        <div>
          {node.children.map((child) => (
            <SpanRow
              key={child.spanId}
              node={child}
              depth={depth + 1}
              selectedSpanId={selectedSpanId}
              onSpanSelect={onSpanSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function buildTree(trace: TraceDetail): SpanNode[] {
  const allSpans: SpanNode[] = [
    ...trace.cron_steps.map(
      (s: CronStepSpan): SpanNode => ({
        spanId: s.span_id,
        parentSpanId: s.parent_span_id,
        spanType: "cron_step",
        label: s.step_name,
        status: s.status,
        durationMs: s.duration_ms,
        children: [],
      }),
    ),
    ...trace.llm_calls.map(
      (s: LLMCallSpan): SpanNode => ({
        spanId: s.span_id,
        parentSpanId: s.parent_span_id,
        spanType: "llm_call",
        label: s.call_site || s.model,
        status: s.status,
        durationMs: s.duration_ms,
        children: [],
      }),
    ),
    ...trace.tool_calls.map(
      (s: ToolCallSpan): SpanNode => ({
        spanId: s.span_id,
        parentSpanId: s.parent_span_id,
        spanType: "tool_call",
        label: s.tool_name,
        status: s.status,
        durationMs: s.duration_ms,
        children: [],
      }),
    ),
    ...trace.events.map(
      (s: ObsEventSpan): SpanNode => ({
        spanId: s.span_id,
        parentSpanId: s.parent_span_id,
        spanType: "event",
        label: s.event_type,
        status: s.level,
        durationMs: null,
        children: [],
      }),
    ),
  ];

  const nodeMap = new Map<string, SpanNode>();
  for (const node of allSpans) {
    nodeMap.set(node.spanId, node);
  }

  const roots: SpanNode[] = [];
  for (const node of allSpans) {
    if (!node.parentSpanId || !nodeMap.has(node.parentSpanId)) {
      roots.push(node);
    } else {
      nodeMap.get(node.parentSpanId)!.children.push(node);
    }
  }

  return roots;
}

export function SpanTree({ trace, selectedSpanId, onSpanSelect }: SpanTreeProps) {
  const roots = buildTree(trace);

  if (roots.length === 0) {
    return (
      <div className="py-6 text-center">
        <span className="material-symbols-outlined text-on-surface-variant text-2xl mb-1 block">
          account_tree
        </span>
        <p className="text-xs text-on-surface-variant">No spans recorded</p>
      </div>
    );
  }

  return (
    <div className="space-y-0.5">
      {roots.map((node) => (
        <SpanRow
          key={node.spanId}
          node={node}
          depth={0}
          selectedSpanId={selectedSpanId}
          onSpanSelect={onSpanSelect}
        />
      ))}
    </div>
  );
}
