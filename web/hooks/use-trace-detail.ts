"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { TraceDetail } from "@/lib/types";

interface UseTraceDetailReturn {
  trace: TraceDetail | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useTraceDetail(traceId: string | null): UseTraceDetailReturn {
  const [trace, setTrace] = useState<TraceDetail | null>(null);
  const [loading, setLoading] = useState(!!traceId);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!traceId) {
      setTrace(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    api<TraceDetail>("GET", `/v1/traces/${traceId}`)
      .then((res) => {
        if (!cancelled) setTrace(res);
      })
      .catch(() => {
        if (!cancelled) setError("Failed to load trace detail");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [traceId]);

  const refresh = useCallback(async () => {
    if (!traceId) return;
    setLoading(true);
    setError(null);
    try {
      const res = await api<TraceDetail>("GET", `/v1/traces/${traceId}`);
      setTrace(res);
    } catch {
      setError("Failed to load trace detail");
    } finally {
      setLoading(false);
    }
  }, [traceId]);

  return { trace, loading, error, refresh };
}

export async function rerunTrace(traceId: string): Promise<{ new_trace_id: string }> {
  return api<{ new_trace_id: string }>("POST", `/v1/traces/${traceId}/rerun`);
}

export async function replaySpan(
  spanId: string,
): Promise<{ new_span_id: string; status: string }> {
  return api<{ new_span_id: string; status: string }>(
    "POST",
    `/v1/spans/llm_calls/${spanId}/replay`,
  );
}
