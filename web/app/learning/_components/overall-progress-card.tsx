"use client";

import { ProgressRing } from "@/components/ui/progress-ring";

interface OverallProgressCardProps {
  pct: number;
}

export function OverallProgressCard({ pct }: OverallProgressCardProps) {
  return (
    <div className="flex items-center gap-3 rounded-[12px] border border-border bg-surface-container px-4 py-3 h-full">
      <ProgressRing size={38} strokeWidth={3} pct={pct} />
      <div>
        <p className="text-[11px] text-on-surface-variant">Overall progress</p>
        <p className="text-sm font-semibold">{Math.round(pct * 100)}% complete</p>
      </div>
    </div>
  );
}
