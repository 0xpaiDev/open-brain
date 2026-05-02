"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useLearning } from "@/hooks/use-learning";
import type { LearningImportResult } from "@/lib/types";

const TEMPLATE = `{
  "topics": [
    {
      "name": "Example Topic",
      "description": "Optional description",
      "depth": "foundational",
      "sections": [
        {
          "name": "Section 1",
          "items": [
            { "title": "Item 1" },
            { "title": "Item 2" }
          ]
        }
      ],
      "material": "# Optional markdown\\nOmit this key entirely if no material yet — do not pass empty string."
    }
  ]
}`;

export default function ImportPage() {
  const router = useRouter();
  const { refresh } = useLearning();

  const [jsonText, setJsonText] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [dryRunResult, setDryRunResult] = useState<LearningImportResult | null>(null);
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
      const result = await api<LearningImportResult>(
        "POST",
        "/v1/learning/import?dry_run=true",
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
      toast.error("JSON changed since last validate — please re-validate");
      return;
    }

    setImporting(true);
    try {
      const result = await api<LearningImportResult>(
        "POST",
        "/v1/learning/import?dry_run=false",
        payload,
      );
      await refresh();
      toast.success(`Imported ${result.topics_created} topic${result.topics_created === 1 ? "" : "s"}`);
      router.push("/learning");
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) {
        toast.error("Too many imports — wait a minute");
      } else if (e instanceof ApiError) {
        toast.error(`Import failed: ${e.message}`);
      } else {
        toast.error("Import failed");
      }
    } finally {
      setImporting(false);
    }
  };

  const canImport =
    dryRunResult !== null &&
    dryRunResult.topics_created > 0 &&
    !importing;

  return (
    <div className="py-8 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="space-y-1">
          <Link
            href="/learning"
            className="text-sm text-on-surface-variant hover:text-primary transition-colors"
          >
            ← Library
          </Link>
          <h1 className="text-2xl font-headline font-bold text-primary">Import Curriculum</h1>
          <p className="text-sm text-on-surface-variant">
            Paste a JSON curriculum to bulk-import topics, sections, items, and materials.
          </p>
        </div>
      </div>

      {/* Template reference */}
      <details className="rounded-lg border border-outline-variant bg-surface-container p-4">
        <summary className="text-sm font-medium cursor-pointer select-none">
          Show JSON template
        </summary>
        <pre className="mt-3 text-xs font-mono text-on-surface-variant overflow-x-auto whitespace-pre-wrap">
          {TEMPLATE}
        </pre>
      </details>

      {/* Two-pane layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Left pane — JSON paste */}
        <div className="space-y-2">
          <label htmlFor="json-paste" className="text-sm font-medium">
            Curriculum JSON
          </label>
          <Textarea
            id="json-paste"
            value={jsonText}
            onChange={(e) => {
              setJsonText(e.target.value);
              setDryRunResult(null);
              setParseError(null);
              setApiError(null);
            }}
            placeholder='{ "topics": [ ... ] }'
            className="font-mono text-base md:text-sm h-[60vh] resize-none"
          />
          {parseError && (
            <p className="text-sm text-red-500">{parseError}</p>
          )}
          <div className="flex gap-2 flex-wrap">
            <Button
              onClick={handleValidate}
              disabled={!jsonText.trim() || validating}
              variant="outline"
            >
              {validating ? "Validating…" : "Validate (dry run)"}
            </Button>
            <Button
              onClick={handleImport}
              disabled={!canImport}
            >
              {importing ? "Importing…" : "Import"}
            </Button>
          </div>
        </div>

        {/* Right pane — preview */}
        <div className="space-y-2">
          <p className="text-sm font-medium">Preview</p>
          <div className="rounded-lg border border-outline-variant bg-surface-container p-4 min-h-[200px]">
            {apiError ? (
              <div className="space-y-1">
                <p className="text-sm font-medium text-red-500">Validation failed</p>
                <p className="text-sm text-on-surface-variant whitespace-pre-wrap">{apiError}</p>
              </div>
            ) : dryRunResult ? (
              <div className="space-y-3">
                <p className="text-sm font-medium text-primary">
                  Dry run complete — ready to import
                </p>
                <ul className="text-sm space-y-1">
                  <li>
                    <span className="text-on-surface-variant">Topics:</span>{" "}
                    <span className="font-medium">{dryRunResult.topics_created}</span> will be created
                  </li>
                  <li>
                    <span className="text-on-surface-variant">Sections:</span>{" "}
                    <span className="font-medium">{dryRunResult.sections_created}</span>
                  </li>
                  <li>
                    <span className="text-on-surface-variant">Items:</span>{" "}
                    <span className="font-medium">{dryRunResult.items_created}</span>
                  </li>
                  {dryRunResult.materials_created > 0 && (
                    <li>
                      <span className="text-on-surface-variant">Materials:</span>{" "}
                      <span className="font-medium">{dryRunResult.materials_created}</span>
                    </li>
                  )}
                </ul>
                {dryRunResult.topics_skipped.length > 0 && (
                  <div>
                    <p className="text-sm text-on-surface-variant mb-1">
                      Skipped ({dryRunResult.topics_skipped.length}):
                    </p>
                    <ul className="text-xs space-y-0.5">
                      {dryRunResult.topics_skipped.map((skip) => (
                        <li key={skip.name} className="text-muted-foreground">
                          {skip.name} — {skip.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {dryRunResult.topics_created === 0 && (
                  <p className="text-sm text-yellow-500">
                    No new topics to create — all were skipped.
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-on-surface-variant">
                Paste JSON and click Validate to preview.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
