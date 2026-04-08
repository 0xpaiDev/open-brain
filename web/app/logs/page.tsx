"use client";

import { useState, useCallback } from "react";
import { useJobHistory } from "@/hooks/use-job-history";
import { useQueueStatus } from "@/hooks/use-queue-status";
import { useDeadLetters } from "@/hooks/use-dead-letters";
import { useJobStatus } from "@/hooks/use-job-status";
import { HealthBanner } from "@/components/logs/health-banner";
import { JobRunsTab } from "@/components/logs/job-runs-tab";
import { PipelineTab } from "@/components/logs/pipeline-tab";
import { DeadLettersTab } from "@/components/logs/dead-letters-tab";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";

export default function LogsPage() {
  // Job runs filters
  const [jobName, setJobName] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);

  // Dead letters filter
  const [resolved, setResolved] = useState(false);

  // Hooks
  const jobHistory = useJobHistory(jobName, statusFilter);
  const queueStatus = useQueueStatus();
  const deadLetters = useDeadLetters(resolved);
  const jobStatus = useJobStatus();

  const [refreshing, setRefreshing] = useState(false);

  const refreshAll = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([
      jobHistory.refresh(),
      queueStatus.refresh(),
      deadLetters.refresh(),
      jobStatus.refresh(),
    ]);
    setRefreshing(false);
  }, [jobHistory, queueStatus, deadLetters, jobStatus]);

  return (
    <div className="py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-headline font-bold text-primary">
            Logs
          </h1>
          <p className="text-on-surface-variant text-sm">
            System health & job history
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={refreshAll}
          disabled={refreshing}
          className="gap-1.5"
        >
          <span
            className={`material-symbols-outlined text-base ${refreshing ? "animate-spin" : ""}`}
          >
            refresh
          </span>
          {refreshing ? "Refreshing..." : "Refresh"}
        </Button>
      </div>

      <HealthBanner
        jobStatus={jobStatus.jobStatus}
        deadLetterCount={deadLetters.total}
        loading={jobStatus.loading || deadLetters.loading}
      />

      <div className="bg-surface-container rounded-2xl p-6">
        <Tabs defaultValue={0}>
          <TabsList variant="line" className="mb-4">
            <TabsTrigger value={0}>
              Job Runs
              {jobHistory.total > 0 && (
                <span className="bg-primary/10 text-primary rounded-full px-1.5 py-0.5 text-xs font-label ml-1">
                  {jobHistory.total}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value={1}>Pipeline</TabsTrigger>
            <TabsTrigger value={2}>
              Dead Letters
              {deadLetters.total > 0 && !resolved && (
                <span className="bg-error/10 text-error rounded-full px-1.5 py-0.5 text-xs font-label ml-1">
                  {deadLetters.total}
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value={0}>
            <JobRunsTab
              items={jobHistory.items}
              total={jobHistory.total}
              loading={jobHistory.loading}
              error={jobHistory.error}
              hasMore={jobHistory.hasMore}
              loadMore={jobHistory.loadMore}
              jobName={jobName}
              setJobName={setJobName}
              statusFilter={statusFilter}
              setStatusFilter={setStatusFilter}
            />
          </TabsContent>

          <TabsContent value={1}>
            <PipelineTab
              status={queueStatus.status}
              loading={queueStatus.loading}
              error={queueStatus.error}
            />
          </TabsContent>

          <TabsContent value={2}>
            <DeadLettersTab
              items={deadLetters.items}
              total={deadLetters.total}
              loading={deadLetters.loading}
              error={deadLetters.error}
              hasMore={deadLetters.hasMore}
              loadMore={deadLetters.loadMore}
              resolved={resolved}
              setResolved={setResolved}
              onRetried={deadLetters.refresh}
            />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
