"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useCommitments } from "@/hooks/use-commitments";
import type { CommitmentResponse, ExerciseProgression } from "@/lib/types";
import {
  LineChart,
  Line,
  XAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const SERIES_COLORS = [
  "var(--color-series-1, #adc6ff)",
  "var(--color-series-2, #4ade80)",
  "var(--color-series-3, #fb923c)",
  "var(--color-series-4, #c084fc)",
  "var(--color-series-5, #38bdf8)",
];

function ProgressionChart({
  series,
  color,
}: {
  series: ExerciseProgression;
  color: string;
}) {
  if (series.points.length === 0) {
    return (
      <div className="h-24 flex items-center justify-center text-on-surface-variant text-sm font-body">
        No logs yet
      </div>
    );
  }

  const data = series.points.slice(-30).map((p) => ({
    date: p.date,
    value: p.value,
  }));

  return (
    <ResponsiveContainer width="100%" height={96}>
      <LineChart data={data}>
        <XAxis dataKey="date" hide />
        <Tooltip
          contentStyle={{
            background: "var(--color-surface-container-high)",
            border: "none",
            borderRadius: "8px",
            fontSize: "12px",
          }}
          labelStyle={{ color: "var(--color-on-surface-variant)" }}
          itemStyle={{ color }}
          formatter={(value) => [
            `${value} ${series.points[0]?.metric ?? ""}`,
            series.exercise_name,
          ]}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke={color}
          strokeWidth={2}
          dot={{ fill: color, r: 3 }}
          isAnimationActive
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export default function CommitmentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { commitments, getProgression } = useCommitments();
  const [commitment, setCommitment] = useState<CommitmentResponse | null>(null);
  const [progression, setProgression] = useState<ExerciseProgression[]>([]);

  useEffect(() => {
    const found = commitments.find((c) => c.id === id) ?? null;
    setCommitment(found);
  }, [commitments, id]);

  useEffect(() => {
    if (!commitment) return;
    const kind = commitment.kind;
    if (kind === "routine" || kind === "plan") {
      getProgression(id).then(setProgression).catch(() => {});
    }
  }, [commitment, id, getProgression]);

  if (!commitment) {
    return (
      <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
        <div className="mb-6">
          <Link href="/" className={buttonVariants({ variant: "ghost" })}>
            ← Back
          </Link>
        </div>
        <div className="h-48 bg-surface-container rounded-2xl animate-pulse" />
      </main>
    );
  }

  const isMultiExercise = commitment.kind === "routine" || commitment.kind === "plan";

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href="/" className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-headline font-semibold text-on-surface">
            {commitment.name}
          </h1>
          <p className="text-on-surface-variant text-sm font-body mt-1">
            {commitment.start_date} → {commitment.end_date} ·{" "}
            <span className="capitalize">{commitment.kind}</span>
          </p>
        </div>

        {isMultiExercise && progression.length > 0 && (
          <div className="space-y-4">
            <h2 className="font-headline font-semibold text-on-surface text-lg">Progression</h2>
            {progression.map((series, idx) => (
              <div key={series.exercise_id} className="bg-surface-container rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-body text-sm text-on-surface">{series.exercise_name}</span>
                  <span className="text-on-surface-variant text-xs font-body">
                    {series.points.length} log{series.points.length !== 1 ? "s" : ""}
                  </span>
                </div>
                <ProgressionChart
                  series={series}
                  color={SERIES_COLORS[idx % SERIES_COLORS.length]}
                />
              </div>
            ))}
          </div>
        )}

        {!isMultiExercise && (
          <div className="bg-surface-container rounded-xl p-4">
            <div className="text-on-surface-variant text-sm font-body">
              Streak: <span className="text-on-surface font-semibold">{commitment.current_streak} days</span>
            </div>
            <div className="text-on-surface-variant text-sm font-body mt-1">
              Target: <span className="text-on-surface">{commitment.daily_target} {commitment.metric}/day</span>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
