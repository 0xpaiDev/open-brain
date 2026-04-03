"use client";

import { MorningPulse } from "@/components/dashboard/morning-pulse";
import { CalendarStrip } from "@/components/dashboard/calendar-strip";
import { TaskList } from "@/components/dashboard/task-list";
import { OverdueModal } from "@/components/dashboard/overdue-modal";

export default function DashboardPage() {
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="py-8 space-y-6">
      <OverdueModal />
      <div>
        <h1 className="text-3xl font-headline font-bold text-primary">Today</h1>
        <p className="text-on-surface-variant text-sm">{today}</p>
      </div>
      <MorningPulse />
      <CalendarStrip />
      <TaskList />
    </div>
  );
}
