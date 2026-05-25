"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Button, buttonVariants } from "@/components/ui/button";
import { KpiTiles } from "@/components/observability/kpi-tiles";
import { TraceList } from "@/components/observability/trace-list";
import { TraceDetailPanel } from "@/components/observability/trace-detail";
import { useTraces, useKpis, type TraceFilters } from "@/hooks/use-traces";

type RefreshInterval = "off" | "5s" | "30s";

export default function ExecutionExplorerPage() {
  const [filters, setFilters] = useState<TraceFilters>({});
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [refreshInterval, setRefreshInterval] = useState<RefreshInterval>("off");

  const traces = useTraces(filters);
  const kpis = useKpis();

  const refresh = useCallback(async () => {
    await Promise.all([traces.refresh(), kpis.refresh()]);
  }, [traces, kpis]);

  useEffect(() => {
    if (refreshInterval === "off") return;
    const ms = refreshInterval === "5s" ? 5000 : 30000;
    const id = setInterval(() => {
      traces.refresh();
      kpis.refresh();
    }, ms);
    return () => clearInterval(id);
  }, [refreshInterval, traces, kpis]);

  function handleTraceClick(id: string) {
    setSelectedTraceId((prev) => (prev === id ? null : id));
  }

  function handleClose() {
    setSelectedTraceId(null);
  }

  function handleRerunComplete(_newId: string) {
    traces.refresh();
    kpis.refresh();
  }

  return (
    <div className="py-8 space-y-6">
      {/* Header row */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">
            Execution Explorer
          </h1>
          <p className="text-on-surface-variant text-sm">
            Trace &amp; cost visibility
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={refreshInterval}
            onChange={(e) =>
              setRefreshInterval(e.target.value as RefreshInterval)
            }
            className="rounded-lg border border-outline-variant/30 bg-surface px-2.5 py-1.5 text-base md:text-sm text-on-surface"
            aria-label="Auto-refresh interval"
          >
            <option value="off">Off</option>
            <option value="5s">5s</option>
            <option value="30s">30s</option>
          </select>

          <Link
            href="/logs/legacy"
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            Legacy logs
          </Link>

          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            aria-label="Refresh"
          >
            <span className="material-symbols-outlined text-sm">refresh</span>
            Refresh
          </Button>
        </div>
      </div>

      {/* KPI tiles */}
      <KpiTiles kpis={kpis.kpis} loading={kpis.loading} />

      {/* Trace list */}
      <TraceList
        items={traces.items}
        total={traces.total}
        loading={traces.loading}
        error={traces.error}
        hasMore={traces.hasMore}
        loadMore={traces.loadMore}
        filters={filters}
        onFiltersChange={setFilters}
        onTraceClick={handleTraceClick}
        selectedTraceId={selectedTraceId}
      />

      {/* Slide-in detail panel */}
      {selectedTraceId && (
        <div className="bg-surface-container rounded-2xl p-6 min-h-96">
          <TraceDetailPanel
            traceId={selectedTraceId}
            onClose={handleClose}
            onRerunComplete={handleRerunComplete}
          />
        </div>
      )}
    </div>
  );
}
