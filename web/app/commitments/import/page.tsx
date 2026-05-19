"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { useCommitments } from "@/hooks/use-commitments";
import { useExercises } from "@/hooks/use-exercises";
import type { CommitmentImportResult, UnknownExercise, ResolvedExercise } from "@/lib/types";
import { toast } from "sonner";

type WizardStep = "validate" | "resolve" | "confirm";

const METRIC_OPTIONS = ["reps", "kg", "minutes", "seconds"] as const;

function ExerciseResolutionCard({
  unknown,
  exercises,
  onResolve,
}: {
  unknown: UnknownExercise;
  exercises: Array<{ id: string; display_name: string }>;
  onResolve: (resolved: ResolvedExercise) => void;
}) {
  const [mode, setMode] = useState<"create" | "match">("create");
  const [displayName, setDisplayName] = useState(unknown.name);
  const [metric, setMetric] = useState(unknown.metric);
  const [progressionMetric, setProgressionMetric] = useState(unknown.progression_metric);
  const [target, setTarget] = useState(unknown.target);
  const [sets, setSets] = useState<number | null>(unknown.sets);
  const [matchedId, setMatchedId] = useState("");

  const handleConfirm = () => {
    if (mode === "match" && matchedId) {
      onResolve({ name: unknown.name, exercise_id: matchedId, metric, progression_metric: progressionMetric, target, sets });
    } else {
      onResolve({ name: unknown.name, display_name: displayName, metric, progression_metric: progressionMetric, target, sets });
    }
  };

  const isReady = mode === "match" ? !!matchedId : !!displayName.trim();

  return (
    <div className="bg-surface-container rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-headline text-on-surface font-semibold">{unknown.name}</span>
        <div className="flex gap-2">
          <button
            onClick={() => setMode("create")}
            className={`text-xs px-3 py-1 rounded-full font-body transition-colors ${mode === "create" ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface-variant"}`}
          >
            Create new
          </button>
          <button
            onClick={() => setMode("match")}
            className={`text-xs px-3 py-1 rounded-full font-body transition-colors ${mode === "match" ? "bg-primary text-on-primary" : "bg-surface-container-high text-on-surface-variant"}`}
          >
            Match existing
          </button>
        </div>
      </div>

      {mode === "create" ? (
        <div className="grid grid-cols-2 gap-2">
          <div className="col-span-2">
            <label className="text-xs text-on-surface-variant font-body block mb-1">Display name</label>
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Metric</label>
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            >
              {METRIC_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Progression metric</label>
            <select
              value={progressionMetric}
              onChange={(e) => setProgressionMetric(e.target.value)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            >
              {METRIC_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Target</label>
            <input
              type="number"
              min={1}
              value={target}
              onChange={(e) => setTarget(Number(e.target.value))}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
          <div>
            <label className="text-xs text-on-surface-variant font-body block mb-1">Sets (optional)</label>
            <input
              type="number"
              min={1}
              value={sets ?? ""}
              onChange={(e) => setSets(e.target.value ? Number(e.target.value) : null)}
              className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
            />
          </div>
        </div>
      ) : (
        <div>
          <label className="text-xs text-on-surface-variant font-body block mb-1">Match to library exercise</label>
          <select
            value={matchedId}
            onChange={(e) => setMatchedId(e.target.value)}
            className="w-full bg-surface rounded-lg px-3 py-2 text-base md:text-sm text-on-surface border border-outline/20 focus:outline-none focus:border-primary"
          >
            <option value="">Select exercise…</option>
            {exercises.map((ex) => (
              <option key={ex.id} value={ex.id}>{ex.display_name}</option>
            ))}
          </select>
        </div>
      )}

      <button
        onClick={handleConfirm}
        disabled={!isReady}
        className="w-full bg-primary text-on-primary rounded-lg py-2 text-base md:text-sm font-body disabled:opacity-40 hover:opacity-90 transition-opacity"
      >
        Confirm
      </button>
    </div>
  );
}

export default function ImportPlanPage() {
  const router = useRouter();
  const { importPlan } = useCommitments();
  const { exercises } = useExercises();

  const [step, setStep] = useState<WizardStep>("validate");
  const [jsonText, setJsonText] = useState("");
  const [dryRunResult, setDryRunResult] = useState<CommitmentImportResult | null>(null);
  const [parsedPayload, setParsedPayload] = useState<unknown>(null);
  const [resolved, setResolved] = useState<Record<string, ResolvedExercise>>({});
  const [loading, setLoading] = useState(false);

  const handleValidate = async () => {
    let payload: unknown;
    try {
      payload = JSON.parse(jsonText);
    } catch {
      toast.error("Invalid JSON");
      return;
    }
    setLoading(true);
    try {
      const result = await importPlan(payload, true);
      setDryRunResult(result);
      setParsedPayload(payload);
      if (result.unknown_exercises.length === 0) {
        setStep("confirm");
      } else {
        setStep("resolve");
      }
    } catch {
      toast.error("Validation failed");
    } finally {
      setLoading(false);
    }
  };

  const handleResolve = (name: string, resolution: ResolvedExercise) => {
    setResolved((prev) => ({ ...prev, [name]: resolution }));
  };

  const allResolved =
    dryRunResult != null &&
    dryRunResult.unknown_exercises.every((ue) => resolved[ue.name] != null);

  const handleImport = async () => {
    if (!parsedPayload || !dryRunResult) return;
    setLoading(true);
    try {
      const payload = {
        ...(parsedPayload as object),
        resolved_exercises: Object.values(resolved),
      };
      const result = await importPlan(payload, false);
      if (result.commitment_id) {
        toast.success("Plan imported!");
        router.push(`/commitments/${result.commitment_id}`);
      }
    } catch {
      toast.error("Import failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href="/commitments" className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-6">Import Training Plan</h1>

      {/* Step indicators */}
      <div className="flex items-center gap-2 mb-8 text-sm font-body">
        {(["validate", "resolve", "confirm"] as WizardStep[]).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            {i > 0 && <span className="text-outline/40">→</span>}
            <span className={`px-3 py-1 rounded-full ${step === s ? "bg-primary text-on-primary" : "bg-surface-container text-on-surface-variant"}`}>
              {i + 1}. {s.charAt(0).toUpperCase() + s.slice(1)}
            </span>
          </div>
        ))}
      </div>

      {step === "validate" && (
        <div className="space-y-4">
          <textarea
            value={jsonText}
            onChange={(e) => setJsonText(e.target.value)}
            placeholder='{"name": "My Plan", "start_date": "2026-06-01", ...}'
            rows={12}
            className="w-full bg-surface-container rounded-xl p-4 text-base md:text-sm font-mono text-on-surface border border-outline/20 focus:outline-none focus:border-primary resize-y"
          />
          <button
            onClick={handleValidate}
            disabled={loading || !jsonText.trim()}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {loading ? "Validating…" : "Validate"}
          </button>
        </div>
      )}

      {step === "resolve" && dryRunResult && (
        <div className="space-y-4">
          <p className="text-on-surface-variant font-body text-sm">
            {dryRunResult.unknown_exercises.length} new exercise{dryRunResult.unknown_exercises.length !== 1 ? "s" : ""} found. Review each before importing.
          </p>
          {dryRunResult.unknown_exercises.map((ue) => (
            <div key={ue.name}>
              {resolved[ue.name] ? (
                <div className="bg-surface-container rounded-xl p-4 flex items-center justify-between">
                  <span className="font-body text-on-surface text-sm">{ue.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-body text-green-600">✓ Resolved</span>
                    <button onClick={() => setResolved((p) => { const n = {...p}; delete n[ue.name]; return n; })} className="text-xs text-outline hover:text-on-surface font-body">Edit</button>
                  </div>
                </div>
              ) : (
                <ExerciseResolutionCard
                  unknown={ue}
                  exercises={exercises}
                  onResolve={(res) => handleResolve(ue.name, res)}
                />
              )}
            </div>
          ))}
          <button
            onClick={() => setStep("confirm")}
            disabled={!allResolved}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            Next →
          </button>
        </div>
      )}

      {step === "confirm" && dryRunResult && (
        <div className="space-y-4">
          <div className="bg-surface-container rounded-xl p-4 space-y-2">
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Workout days</span>
              <span className="text-on-surface">{dryRunResult.workout_days}</span>
            </div>
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Rest days</span>
              <span className="text-on-surface">{dryRunResult.rest_days}</span>
            </div>
            <div className="flex justify-between text-sm font-body">
              <span className="text-on-surface-variant">Exercises</span>
              <span className="text-on-surface">
                {dryRunResult.exercise_count}
                {Object.keys(resolved).length > 0 && ` (${Object.keys(resolved).length} new)`}
              </span>
            </div>
          </div>
          <button
            onClick={handleImport}
            disabled={loading}
            className="w-full bg-primary text-on-primary rounded-xl py-3 font-body text-base md:text-sm disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {loading ? "Importing…" : "Import Plan"}
          </button>
          <button onClick={() => setStep("validate")} className="w-full text-on-surface-variant font-body text-sm hover:text-on-surface transition-colors">
            ← Start over
          </button>
        </div>
      )}
    </main>
  );
}
