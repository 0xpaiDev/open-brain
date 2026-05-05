"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { buttonVariants } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import type { CommitmentImportResult } from "@/lib/types";

const EXAMPLE = `{
  "name": "Stronglifts 5x5",
  "start_date": "2026-05-10",
  "end_date": "2026-05-17",
  "schedule": [
    {
      "day": "2026-05-10",
      "rest": false,
      "exercises": [
        {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        {"name": "Bench Press", "target": 5, "metric": "reps", "progression_metric": "kg"}
      ]
    },
    {"day": "2026-05-11", "rest": true},
    {
      "day": "2026-05-12",
      "rest": false,
      "exercises": [
        {"name": "Squat", "target": 5, "metric": "reps", "progression_metric": "kg"},
        {"name": "Overhead Press", "target": 5, "metric": "reps", "progression_metric": "kg"}
      ]
    }
  ]
}`;

export default function CommitmentImportPage() {
  const router = useRouter();

  const [jsonText, setJsonText] = useState("");
  const [showExample, setShowExample] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [dryRunResult, setDryRunResult] = useState<CommitmentImportResult | null>(null);
  const [validating, setValidating] = useState(false);
  const [importing, setImporting] = useState(false);

  const handleValidate = async () => {
    setParseError(null);
    setApiError(null);
    setDryRunResult(null);

    let payload: unknown;
    try {
      payload = JSON.parse(jsonText);
    } catch (e) {
      setParseError(`Invalid JSON: ${(e as Error).message}`);
      return;
    }

    setValidating(true);
    try {
      const result = await api<CommitmentImportResult>(
        "POST",
        "/v1/commitments/import?dry_run=true",
        payload,
      );
      setDryRunResult(result);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        setApiError("Too many requests — wait a minute and try again.");
      } else if (e instanceof ApiError) {
        setApiError(e.message);
      } else {
        setApiError("Unexpected error during validation.");
      }
    } finally {
      setValidating(false);
    }
  };

  const handleImport = async () => {
    if (!dryRunResult) return;

    let payload: unknown;
    try {
      payload = JSON.parse(jsonText);
    } catch {
      setParseError("JSON changed after validation — please re-validate.");
      return;
    }

    setImporting(true);
    try {
      const result = await api<CommitmentImportResult>(
        "POST",
        "/v1/commitments/import?dry_run=false",
        payload,
      );
      if (result.already_exists) {
        toast.success("Plan already imported — opening existing commitment.");
      } else {
        toast.success("Plan imported successfully!");
      }
      router.push("/commitments");
    } catch (e) {
      if (e instanceof ApiError) {
        setApiError(e.message);
      } else {
        setApiError("Import failed — please try again.");
      }
    } finally {
      setImporting(false);
    }
  };

  return (
    <main className="min-h-screen bg-background p-4 md:p-8 max-w-2xl mx-auto">
      <div className="mb-6">
        <Link href="/commitments" className={buttonVariants({ variant: "ghost" })}>
          ← Back
        </Link>
      </div>

      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-2">
        Import Training Plan
      </h1>
      <p className="text-on-surface-variant text-sm font-body mb-6">
        Paste a JSON training plan. Use Validate to preview before importing.
      </p>

      <div className="space-y-4">
        <div>
          <div className="flex items-center justify-between mb-1">
            <label htmlFor="plan-json" className="text-sm font-body text-on-surface-variant">
              Plan JSON
            </label>
            <button
              onClick={() => setShowExample(!showExample)}
              className="text-xs text-primary font-body cursor-pointer hover:underline"
            >
              {showExample ? "Hide example" : "Show example"}
            </button>
          </div>
          {showExample && (
            <pre className="bg-surface-container-high rounded-lg p-3 text-xs font-mono text-on-surface-variant overflow-x-auto mb-2">
              {EXAMPLE}
            </pre>
          )}
          <Textarea
            id="plan-json"
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              setDryRunResult(null);
              setParseError(null);
              setApiError(null);
            }}
            placeholder="Paste your plan JSON here…"
            rows={12}
            className={`font-mono text-base md:text-sm ${parseError || apiError ? "border-error" : ""}`}
          />
          {(parseError || apiError) && (
            <p role="alert" className="text-error text-sm font-body mt-1">
              {parseError ?? apiError}
            </p>
          )}
        </div>

        <button
          onClick={handleValidate}
          disabled={!jsonText.trim() || validating}
          className={`${buttonVariants({ variant: "outline" })} w-full cursor-pointer disabled:opacity-50`}
        >
          {validating ? "Validating…" : "Validate"}
        </button>

        {dryRunResult && (
          <div className="bg-surface-container rounded-xl p-4 space-y-2">
            <h2 className="font-headline font-semibold text-on-surface">Preview</h2>
            <div className="grid grid-cols-3 gap-2 text-sm font-body">
              <div className="bg-surface-container-high rounded-lg p-3 text-center">
                <div className="text-2xl font-headline text-primary">{dryRunResult.workout_days}</div>
                <div className="text-on-surface-variant text-xs">Workout days</div>
              </div>
              <div className="bg-surface-container-high rounded-lg p-3 text-center">
                <div className="text-2xl font-headline text-primary">{dryRunResult.rest_days}</div>
                <div className="text-on-surface-variant text-xs">Rest days</div>
              </div>
              <div className="bg-surface-container-high rounded-lg p-3 text-center">
                <div className="text-2xl font-headline text-primary">{dryRunResult.exercise_count}</div>
                <div className="text-on-surface-variant text-xs">Exercises</div>
              </div>
            </div>

            <button
              onClick={handleImport}
              disabled={importing}
              className={`${buttonVariants({ variant: "default" })} w-full cursor-pointer disabled:opacity-50`}
            >
              {importing ? "Importing…" : "Import Plan"}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
