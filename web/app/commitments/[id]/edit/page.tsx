"use client";

import { use, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useCommitments } from "@/hooks/use-commitments";
import type { CommitmentResponse, ScheduleResponse, ScheduleDay } from "@/lib/types";
import { toast } from "sonner";

function ExercisePicker({
  exercises,
  selected,
  onConfirm,
  onCancel,
}: {
  exercises: Array<{ id: string; name: string; sets: number | null }>;
  selected: string[];
  onConfirm: (ids: string[]) => void;
  onCancel: () => void;
}) {
  const [checked, setChecked] = useState<Set<string>>(new Set(selected));

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div className="bg-surface-container-high rounded-xl p-4 space-y-3 border border-outline/20">
      <p className="text-sm font-body text-on-surface-variant">Select exercises for this day:</p>
      <div className="space-y-2">
        {exercises.map((ex) => (
          <label key={ex.id} className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={checked.has(ex.id)}
              onChange={() => toggle(ex.id)}
              className="w-4 h-4"
            />
            <span className="font-body text-sm text-on-surface">
              {ex.name}{ex.sets ? ` (${ex.sets} sets)` : ""}
            </span>
          </label>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onConfirm(Array.from(checked))}
          disabled={checked.size === 0}
          className="flex-1 bg-primary text-on-primary rounded-lg py-2 text-base md:text-sm font-body disabled:opacity-40"
        >
          Confirm
        </button>
        <button
          onClick={onCancel}
          className="flex-1 bg-surface-container rounded-lg py-2 text-base md:text-sm font-body text-on-surface-variant"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function CommitmentEditPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const { fetchById, getSchedule, swapDay, updateDayExercises } = useCommitments();
  const [commitment, setCommitment] = useState<CommitmentResponse | null>(null);
  const [schedule, setSchedule] = useState<ScheduleResponse | null>(null);
  const [pickerDay, setPickerDay] = useState<ScheduleDay | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    const c = await fetchById(id);
    setCommitment(c);
    const s = await getSchedule(id);
    setSchedule(s);
  }, [id, fetchById, getSchedule]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  if (!commitment || !schedule) {
    return (
      <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
        <div className="h-48 bg-surface-container rounded-2xl animate-pulse" />
      </main>
    );
  }

  const handleMakeWorkout = async (day: ScheduleDay, exerciseIds: string[]) => {
    setLoading(true);
    try {
      await swapDay(id, day.date, "to_workout", exerciseIds);
      await load();
      toast.success("Converted to workout day");
    } catch {
      toast.error("Failed to update day");
    } finally {
      setLoading(false);
      setPickerDay(null);
    }
  };

  const handleMakeRest = async (day: ScheduleDay) => {
    if (!confirm(`Convert ${day.date} to a rest day? This will delete any pending logs.`)) return;
    setLoading(true);
    try {
      await swapDay(id, day.date, "to_rest", []);
      await load();
      toast.success("Converted to rest day");
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to update day";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleEditExercises = async (day: ScheduleDay, exerciseIds: string[]) => {
    if (!day.entry_id) return;
    setLoading(true);
    try {
      await updateDayExercises(id, day.entry_id, exerciseIds);
      await load();
      toast.success("Exercises updated");
    } catch {
      toast.error("Failed to update exercises");
    } finally {
      setLoading(false);
      setPickerDay(null);
    }
  };

  // Group days by week
  const weeks: ScheduleDay[][] = [];
  schedule.days.forEach((day, i) => {
    const weekIdx = Math.floor(i / 7);
    if (!weeks[weekIdx]) weeks[weekIdx] = [];
    weeks[weekIdx].push(day);
  });

  const allExercises = commitment.exercises;
  const today = new Date().toISOString().slice(0, 10);

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href={`/commitments/${id}`} className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-1">
        {commitment.name}
      </h1>
      <p className="text-on-surface-variant text-sm font-body mb-6">
        {commitment.start_date} → {commitment.end_date}
      </p>

      <div className="space-y-6">
        {weeks.map((week, wi) => (
          <div key={wi} className="space-y-2">
            <h2 className="text-xs font-body text-on-surface-variant uppercase tracking-wide">
              Week {wi + 1}
            </h2>
            {week.map((day) => {
              const isRest = day.status === "rest";
              const isPast = day.date < today;
              const isHitMiss = day.status === "hit" || day.status === "miss";

              return (
                <div key={day.date}>
                  <div
                    className={`bg-surface-container rounded-xl p-3 flex items-center justify-between ${isRest ? "opacity-60" : ""}`}
                  >
                    <div>
                      <p className="text-sm font-body text-on-surface">{day.date}</p>
                      {!isRest && (
                        <p className="text-xs text-on-surface-variant font-body mt-0.5">
                          {day.exercises.map((e) => e.name).join(", ")}
                        </p>
                      )}
                      {isRest && (
                        <p className="text-xs text-outline font-body mt-0.5">Rest</p>
                      )}
                    </div>
                    {!isHitMiss && !isPast && (
                      <div className="flex gap-2">
                        {isRest ? (
                          <button
                            onClick={() => setPickerDay(day)}
                            disabled={loading}
                            className="text-xs bg-primary-container text-on-primary-container rounded-full px-3 py-1 font-body hover:bg-primary hover:text-on-primary transition-colors disabled:opacity-40"
                          >
                            Make workout
                          </button>
                        ) : (
                          <>
                            <button
                              onClick={() => setPickerDay(day)}
                              disabled={loading}
                              className="text-xs bg-surface-container-high text-on-surface-variant rounded-full px-3 py-1 font-body hover:text-on-surface transition-colors disabled:opacity-40"
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleMakeRest(day)}
                              disabled={loading}
                              className="text-xs text-outline rounded-full px-3 py-1 font-body hover:text-error transition-colors disabled:opacity-40"
                            >
                              Make rest
                            </button>
                          </>
                        )}
                      </div>
                    )}
                    {isHitMiss && (
                      <span
                        className={`text-xs font-body ${day.status === "hit" ? "text-green-600" : "text-red-600"}`}
                      >
                        {day.status}
                      </span>
                    )}
                  </div>

                  {pickerDay?.date === day.date && (
                    <div className="mt-2">
                      <ExercisePicker
                        exercises={allExercises}
                        selected={day.exercises.map((e) => e.exercise_id)}
                        onConfirm={(ids) => {
                          if (isRest) {
                            handleMakeWorkout(day, ids);
                          } else {
                            handleEditExercises(day, ids);
                          }
                        }}
                        onCancel={() => setPickerDay(null)}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </main>
  );
}
