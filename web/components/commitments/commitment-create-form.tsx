"use client";

import { useState } from "react";
import type { CommitmentCreate, CommitmentResponse } from "@/lib/types";

const METRICS = [
  { value: "reps", label: "Reps" },
  { value: "minutes", label: "Minutes" },
  { value: "tss", label: "TSS" },
];

const AGGREGATE_METRICS = [
  { value: "km", label: "Kilometers" },
  { value: "tss", label: "TSS" },
  { value: "minutes", label: "Minutes" },
  { value: "hours", label: "Hours" },
  { value: "elevation_m", label: "Elevation (m)" },
];

interface CommitmentCreateFormProps {
  createCommitment: (data: CommitmentCreate) => Promise<CommitmentResponse | null>;
  onCreated?: () => void;
}

export function CommitmentCreateForm({ createCommitment, onCreated }: CommitmentCreateFormProps) {
  const [cmtName, setCmtName] = useState("");
  const [cmtExercise, setCmtExercise] = useState("");
  const [cmtTarget, setCmtTarget] = useState("");
  const [cmtMetric, setCmtMetric] = useState("reps");
  const [cmtCadence, setCmtCadence] = useState<"daily" | "aggregate">("daily");
  const [cmtAggMetric, setCmtAggMetric] = useState("km");
  const [cmtAggTarget, setCmtAggTarget] = useState("");
  const [cmtStart, setCmtStart] = useState(() => new Date().toISOString().slice(0, 10));
  const [cmtEnd, setCmtEnd] = useState("");
  const [cmtSubmitting, setCmtSubmitting] = useState(false);

  const cmtFormValid = cmtCadence === "daily"
    ? cmtName.trim() && cmtExercise.trim() && cmtTarget && cmtEnd
    : cmtName.trim() && cmtExercise.trim() && cmtAggTarget && cmtEnd;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!cmtFormValid || cmtSubmitting) return;
    setCmtSubmitting(true);

    let result: CommitmentResponse | null;
    if (cmtCadence === "daily") {
      result = await createCommitment({
        name: cmtName.trim(),
        exercise: cmtExercise.trim(),
        daily_target: parseInt(cmtTarget, 10),
        metric: cmtMetric,
        cadence: "daily",
        start_date: cmtStart,
        end_date: cmtEnd,
      });
    } else {
      result = await createCommitment({
        name: cmtName.trim(),
        exercise: cmtExercise.trim(),
        daily_target: 0,
        cadence: "aggregate",
        targets: { [cmtAggMetric]: parseFloat(cmtAggTarget) },
        start_date: cmtStart,
        end_date: cmtEnd,
      });
    }

    setCmtSubmitting(false);
    if (result) {
      setCmtName("");
      setCmtExercise("");
      setCmtTarget("");
      setCmtAggTarget("");
      setCmtEnd("");
      onCreated?.();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      {/* Cadence toggle */}
      <div className="flex gap-2">
        {(["daily", "aggregate"] as const).map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setCmtCadence(c)}
            className={`px-3 py-1.5 rounded-lg text-base md:text-sm font-body cursor-pointer transition-colors ${
              cmtCadence === c
                ? "bg-primary text-on-primary"
                : "bg-surface-container-high text-on-surface-variant hover:bg-surface-container-low"
            }`}
          >
            {c === "daily" ? "Daily" : "Period"}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input
          type="text"
          value={cmtName}
          onChange={(e) => setCmtName(e.target.value)}
          placeholder="Challenge name"
          maxLength={100}
          className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
        />
        <input
          type="text"
          value={cmtExercise}
          onChange={(e) => setCmtExercise(e.target.value)}
          placeholder={cmtCadence === "daily" ? "Exercise (e.g. push-ups)" : "Exercise (e.g. cycling)"}
          maxLength={100}
          className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Daily-specific fields */}
      {cmtCadence === "daily" && (
        <div className="grid grid-cols-3 gap-3">
          <input
            type="number"
            value={cmtTarget}
            onChange={(e) => setCmtTarget(e.target.value)}
            placeholder="Daily target"
            min={1}
            className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <select
            value={cmtMetric}
            onChange={(e) => setCmtMetric(e.target.value)}
            className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
          >
            {METRICS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <div />
        </div>
      )}

      {/* Aggregate-specific fields */}
      {cmtCadence === "aggregate" && (
        <div className="grid grid-cols-3 gap-3">
          <select
            value={cmtAggMetric}
            onChange={(e) => setCmtAggMetric(e.target.value)}
            className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
          >
            {AGGREGATE_METRICS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
          <input
            type="number"
            value={cmtAggTarget}
            onChange={(e) => setCmtAggTarget(e.target.value)}
            placeholder="Period target"
            min={1}
            step="any"
            className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
          />
          <div />
        </div>
      )}

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="cmt-start-date" className="block text-xs text-on-surface-variant mb-1">Start date</label>
          <input
            id="cmt-start-date"
            type="date"
            value={cmtStart}
            onChange={(e) => setCmtStart(e.target.value)}
            className="w-full bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
        <div>
          <label htmlFor="cmt-end-date" className="block text-xs text-on-surface-variant mb-1">End date</label>
          <input
            id="cmt-end-date"
            type="date"
            value={cmtEnd}
            onChange={(e) => setCmtEnd(e.target.value)}
            min={cmtStart}
            className="w-full bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>
      <button
        type="submit"
        disabled={!cmtFormValid || cmtSubmitting}
        className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2 px-5 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none"
      >
        <span className="material-symbols-outlined text-sm">add</span>
        Create Commitment
      </button>
    </form>
  );
}
