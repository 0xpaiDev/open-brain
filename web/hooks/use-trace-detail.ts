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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTrace = useCallback(async () => {
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

  useEffect(() => {
    if (!traceId) {
      setTrace(null);
      return;
    }
    fetchTrace();
  }, [traceId, fetchTrace]);

  return { trace, loading, error, refresh: fetchTrace };
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
