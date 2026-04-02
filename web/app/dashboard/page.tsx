"use client";

import { MorningPulse } from "@/components/dashboard/morning-pulse";
import { CalendarStrip } from "@/components/dashboard/calendar-strip";
import { TaskList } from "@/components/dashboard/task-list";

export default function DashboardPage() {
  const today = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });

  return (
    <div className="py-8 space-y-6">
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
