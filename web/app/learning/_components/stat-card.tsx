"use client";

import { cn } from "@/lib/utils";

interface StatCardProps {
  value: string | number;
  label: string;
  accent?: boolean;
}

export function StatCard({ value, label, accent }: StatCardProps) {
  return (
    <div className="rounded-[12px] border border-border bg-surface-container px-4 py-3 min-w-[90px]">
      <p className={cn("text-2xl font-bold leading-none", accent ? "text-primary" : "text-foreground")}>
        {value}
      </p>
      <p className="text-[11px] text-on-surface-variant mt-1">{label}</p>
    </div>
  );
}
