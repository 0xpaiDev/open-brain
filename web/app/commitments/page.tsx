"use client";

import { useState } from "react";
import Link from "next/link";
import { buttonVariants } from "@/components/ui/button";
import { Collapsible, CollapsibleContent } from "@/components/ui/collapsible";
import { useCommitments } from "@/hooks/use-commitments";
import {
  CommitmentCard,
  AggregateCommitmentCard,
  MultiExerciseCommitmentCard,
} from "@/components/dashboard/commitment-list";
import { CommitmentCreateForm } from "@/components/commitments/commitment-create-form";
import type { CommitmentResponse } from "@/lib/types";

function statusBadgeClass(c: CommitmentResponse): string {
  const notReached = c.status === "completed" && c.goal_reached === false;
  if (notReached) return "bg-streak-miss/20 text-streak-miss";
  if (c.status === "active") return "bg-streak-hit/20 text-streak-hit";
  if (c.status === "completed") return "bg-primary/20 text-primary";
  return "bg-outline/20 text-outline";
}

function statusBadgeLabel(c: CommitmentResponse): string {
  if (c.status === "completed" && c.goal_reached === false) return "not reached";
  if (c.status === "completed" && c.goal_reached === true) return "reached";
  return c.status;
}

function historyDetail(c: CommitmentResponse): string {
  if (c.cadence === "aggregate") {
    const progress = c.progress ?? {};
    return Object.entries(c.targets ?? {})
      .map(([k, v]) => {
        const actual = progress[k] ?? 0;
        return `${actual.toFixed(1)}/${v} ${k}`;
      })
      .join(", ");
  }
  const totalDays =
    Math.ceil(
      (new Date(c.end_date).getTime() - new Date(c.start_date).getTime()) / 86400000,
    ) + 1;
  const hits = c.entries.filter((e) => e.status === "hit").length;
  return `${hits}/${totalDays} days · ${c.daily_target} ${c.metric}/day`;
}

export default function CommitmentsPage() {
  const { commitments, loading, refresh, logCount, logExercise, createCommitment, abandonCommitment } =
    useCommitments("all");
  const [formOpen, setFormOpen] = useState(false);

  const active = commitments.filter((c) => c.status === "active");
  const history = [...commitments.filter((c) => c.status !== "active")].sort((a, b) =>
    b.end_date.localeCompare(a.end_date),
  );

  function handleCreated() {
    setFormOpen(false);
    void refresh();
  }

  return (
    <div className="py-8 space-y-8 max-w-2xl">
      <div>
        <h1 className="text-3xl font-headline font-bold text-primary mb-2">Commitments</h1>
        <p className="text-on-surface-variant text-sm">
          Manage your training challenges and track progress.
        </p>
      </div>

      {/* Active commitments */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-headline font-semibold text-on-surface">Active</h2>
          <div className="flex items-center gap-2">
            <Link
              href="/commitments/import"
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <span className="material-symbols-outlined text-sm mr-1">upload</span>
              Import plan
            </Link>
            <button
              onClick={() => setFormOpen((v) => !v)}
              className={buttonVariants({ variant: "default", size: "sm" })}
            >
              <span className="material-symbols-outlined text-sm mr-1">add</span>
              New
            </button>
          </div>
        </div>

        {/* Collapsible create form */}
        <Collapsible open={formOpen} onOpenChange={(open) => setFormOpen(open)}>
          <CollapsibleContent>
            <div className="bg-surface-container rounded-2xl p-6 space-y-4 mb-4">
              <h3 className="text-base font-headline font-semibold text-on-surface">
                New commitment
              </h3>
              <CommitmentCreateForm
                createCommitment={createCommitment}
                onCreated={handleCreated}
              />
            </div>
          </CollapsibleContent>
        </Collapsible>

        {loading ? (
          <div className="space-y-3">
            {[1, 2].map((n) => (
              <div key={n} className="h-36 bg-surface-container rounded-2xl animate-pulse" />
            ))}
          </div>
        ) : active.length === 0 ? (
          <div className="bg-surface-container rounded-2xl p-6 text-center">
            <span className="material-symbols-outlined text-3xl text-outline mb-2 block">
              task_alt
            </span>
            <p className="text-sm text-on-surface-variant font-body">
              No active commitments — create one or import a plan.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {active.map((c) => (
              <div key={c.id} className="relative group">
                <Link
                  href={`/commitments/${c.id}`}
                  className="absolute inset-0 rounded-2xl z-0"
                  aria-label={`View ${c.name} details`}
                />
                <div className="relative z-10">
                  {c.cadence === "aggregate" ? (
                    <AggregateCommitmentCard commitment={c} />
                  ) : c.kind === "routine" || c.kind === "plan" ? (
                    <MultiExerciseCommitmentCard
                      commitment={c}
                      onLogExercise={async (commitmentId, exerciseId) => {
                        await logExercise(commitmentId, exerciseId, {});
                      }}
                    />
                  ) : (
                    <CommitmentCard commitment={c} onLog={logCount} />
                  )}
                </div>
                {c.status === "active" && (
                  <button
                    onClick={() => abandonCommitment(c.id)}
                    className="absolute top-3 right-3 z-20 text-outline hover:text-error opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                    title="Abandon commitment"
                    aria-label={`Abandon ${c.name}`}
                  >
                    <span className="material-symbols-outlined text-lg">close</span>
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* History */}
      <section className="bg-surface-container rounded-2xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface mb-1">History</h2>
          <p className="text-xs text-outline font-body">Completed and abandoned commitments.</p>
        </div>

        {history.length === 0 ? (
          <p className="text-sm text-on-surface-variant font-body py-2">
            No completed commitments yet.
          </p>
        ) : (
          <ul className="space-y-1">
            {history.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/commitments/${c.id}`}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-xs font-body px-2 py-0.5 rounded-full ${statusBadgeClass(c)}`}>
                      {statusBadgeLabel(c)}
                    </span>
                    <span className="text-sm font-body text-on-surface truncate">{c.name}</span>
                    <span className="text-xs text-on-surface-variant hidden sm:inline">
                      {historyDetail(c)}
                    </span>
                  </div>
                  <span className="text-xs text-on-surface-variant font-body shrink-0 ml-2">
                    {c.end_date}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
