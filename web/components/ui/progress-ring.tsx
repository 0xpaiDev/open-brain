"use client";

import { cn } from "@/lib/utils";

interface ProgressRingProps {
  size: number;
  strokeWidth: number;
  pct: number;
  className?: string;
}

export function ProgressRing({ size, strokeWidth, pct, className }: ProgressRingProps) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dash = Math.max(0, Math.min(1, pct)) * circumference;
  const isComplete = pct >= 1;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className={cn("shrink-0 -rotate-90", className)}
      aria-hidden="true"
    >
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        className="stroke-surface-container-high"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={strokeWidth}
        strokeDasharray={`${dash} ${circumference}`}
        strokeLinecap="round"
        className={cn(
          "transition-[stroke-dasharray] duration-300",
          isComplete ? "stroke-streak-hit" : "stroke-primary",
        )}
      />
    </svg>
  );
}
