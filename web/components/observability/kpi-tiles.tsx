"use client";

import type { KpiResponse, KpiSparklinePoint } from "@/lib/types";

interface KpiTilesProps {
  kpis: KpiResponse | null;
  loading: boolean;
}

function Sparkline({ points }: { points: KpiSparklinePoint[] }) {
  if (points.length < 2) return null;

  const values = points.map((p) => parseFloat(p.cost_usd));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const range = maxVal - minVal || 1;

  const w = 80;
  const h = 24;
  const coords = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - minVal) / range) * h;
    return `${x},${y}`;
  });

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="mt-1">
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        className="text-primary/60"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function formatCost(costStr: string): string {
  const n = parseFloat(costStr);
  return `$${n.toFixed(6)}`;
}

function formatAge(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return s > 0 ? `${m}m ${s}s ago` : `${m}m ago`;
  }
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `${h}h ${m}m ago` : `${h}h ago`;
}

function SkeletonTile() {
  return (
    <div className="bg-surface-container rounded-2xl p-4">
      <div className="h-3 w-20 bg-surface-container-high rounded animate-pulse mb-3" />
      <div className="h-8 w-24 bg-surface-container-high rounded animate-pulse" />
    </div>
  );
}

export function KpiTiles({ kpis, loading }: KpiTilesProps) {
  if (loading) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((n) => (
          <SkeletonTile key={n} />
        ))}
      </div>
    );
  }

  const failureCount = kpis?.failure_count_24h ?? 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <div className="bg-surface-container rounded-2xl p-4">
        <p className="text-xs text-on-surface-variant">Cost in range</p>
        <p className="text-2xl font-bold text-on-surface mt-1">
          {kpis ? formatCost(kpis.cost_in_range_usd) : "—"}
        </p>
        {kpis && kpis.sparkline_7d.length >= 2 && (
          <Sparkline points={kpis.sparkline_7d} />
        )}
      </div>

      <div className="bg-surface-container rounded-2xl p-4">
        <p className="text-xs text-on-surface-variant">Cache hit rate</p>
        <p className="text-2xl font-bold text-on-surface mt-1">
          {kpis?.cache_hit_rate_24h != null
            ? `${kpis.cache_hit_rate_24h.toFixed(1)}%`
            : "—"}
        </p>
      </div>

      <div className="bg-surface-container rounded-2xl p-4">
        <p className="text-xs text-on-surface-variant">24h failures</p>
        <p
          className={`text-2xl font-bold mt-1 ${failureCount > 0 ? "text-error" : "text-on-surface"}`}
        >
          {kpis ? failureCount : "—"}
        </p>
      </div>

      <div className="bg-surface-container rounded-2xl p-4">
        <p className="text-xs text-on-surface-variant">Oldest dead letter</p>
        <p className="text-2xl font-bold text-on-surface mt-1">
          {kpis
            ? kpis.oldest_dead_letter_age_seconds != null
              ? formatAge(kpis.oldest_dead_letter_age_seconds)
              : "none"
            : "—"}
        </p>
      </div>
    </div>
  );
}
