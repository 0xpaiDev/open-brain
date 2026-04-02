"use client";

import { useCalendar } from "@/hooks/use-calendar";
import type { CalendarEvent, CalendarTomorrowEvent } from "@/lib/types";
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from "@/components/ui/collapsible";

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

function isCurrentOrNext(event: CalendarEvent, now: Date): boolean {
  const start = new Date(event.start);
  const end = new Date(event.end);

  // Currently happening
  if (now >= start && now <= end) return true;

  // Next upcoming (within 2 hours)
  const twoHoursFromNow = new Date(now.getTime() + 2 * 60 * 60 * 1000);
  if (start > now && start <= twoHoursFromNow) return true;

  return false;
}

function EventPill({ event, highlighted }: { event: CalendarEvent; highlighted: boolean }) {
  return (
    <div
      className={`flex-shrink-0 rounded-xl px-4 py-2 text-sm transition-colors ${
        highlighted
          ? "bg-surface-container border-2 border-primary"
          : "bg-surface-container-high border border-outline-variant/30"
      }`}
    >
      {event.all_day ? (
        <span className="bg-secondary-container text-on-surface rounded-full px-2 py-0.5 text-xs font-label">
          All day
        </span>
      ) : (
        <span className="text-primary font-label font-medium mr-1.5">
          {formatTime(event.start)}
        </span>
      )}
      <span className="text-on-surface">{event.title}</span>
      {event.location && (
        <span className="text-on-surface-variant text-xs ml-1.5">
          <span className="material-symbols-outlined text-xs align-middle">location_on</span>
          {event.location}
        </span>
      )}
    </div>
  );
}

function TomorrowRow({ events }: { events: CalendarTomorrowEvent[] }) {
  if (events.length === 0) return null;

  return (
    <div className="flex items-center gap-2 mt-2 text-sm text-on-surface-variant">
      <span className="font-label text-xs uppercase tracking-wider">Tomorrow</span>
      <span className="text-xs">
        {events.map((e) => e.title).join(", ")}
      </span>
    </div>
  );
}

function CalendarSkeleton() {
  return (
    <div className="space-y-3" role="status" aria-busy="true">
      <div className="h-5 w-24 bg-surface-container-high rounded-lg animate-pulse" />
      <div className="flex gap-3">
        {[1, 2, 3].map((n) => (
          <div key={n} className="h-10 w-40 bg-surface-container-high rounded-xl animate-pulse flex-shrink-0" />
        ))}
      </div>
    </div>
  );
}

function EmptyCalendar({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-3 py-4 text-on-surface-variant text-sm">
      <span className="material-symbols-outlined text-xl">
        {connected ? "event_busy" : "cloud_off"}
      </span>
      <span>
        {connected ? "No calendar events today" : "Calendar not connected"}
      </span>
    </div>
  );
}

export function CalendarStrip() {
  const { data, loading, error } = useCalendar();

  if (loading) return <CalendarSkeleton />;
  if (error) {
    return (
      <div className="text-sm text-on-surface-variant flex items-center gap-2">
        <span className="material-symbols-outlined text-base text-error">error</span>
        {error}
      </div>
    );
  }
  if (!data) return null;

  if (data.status === "unavailable") return <EmptyCalendar connected={false} />;
  if (data.events.length === 0 && data.tomorrow_preview.length === 0) {
    return <EmptyCalendar connected={true} />;
  }

  const now = new Date();
  const timedEvents = data.events.filter((e) => !e.all_day);
  const allDayEvents = data.events.filter((e) => e.all_day);
  const orderedEvents = [...allDayEvents, ...timedEvents];

  return (
    <div>
      {/* Desktop: horizontal strip */}
      <div className="hidden md:block">
        <div className="flex items-center gap-2 mb-2">
          <span className="material-symbols-outlined text-primary text-lg">today</span>
          <h2 className="text-sm font-label font-medium text-on-surface-variant uppercase tracking-wider">
            Calendar
          </h2>
          <span className="text-xs text-on-surface-variant">
            {data.events.length} event{data.events.length !== 1 ? "s" : ""}
          </span>
        </div>
        <div className="flex gap-3 overflow-x-auto pb-2">
          {orderedEvents.map((event, i) => (
            <EventPill
              key={`${event.title}-${i}`}
              event={event}
              highlighted={!event.all_day && isCurrentOrNext(event, now)}
            />
          ))}
        </div>
        <TomorrowRow events={data.tomorrow_preview} />
      </div>

      {/* Mobile: collapsible */}
      <div className="md:hidden">
        <Collapsible>
          <CollapsibleTrigger className="flex items-center gap-2 w-full py-2">
            <span className="material-symbols-outlined text-primary text-lg">today</span>
            <span className="text-sm font-label font-medium text-on-surface-variant uppercase tracking-wider">
              Calendar
            </span>
            <span className="bg-primary text-on-primary rounded-full px-2 py-0.5 text-xs min-w-[1.5rem] text-center font-label">
              {data.events.length}
            </span>
            <span className="material-symbols-outlined text-on-surface-variant ml-auto text-base">
              expand_more
            </span>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="space-y-2 py-2">
              {orderedEvents.map((event, i) => (
                <div
                  key={`${event.title}-${i}`}
                  className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                    !event.all_day && isCurrentOrNext(event, now)
                      ? "bg-surface-container border border-primary"
                      : "bg-surface-container-high"
                  }`}
                >
                  {event.all_day ? (
                    <span className="bg-secondary-container text-on-surface rounded-full px-2 py-0.5 text-xs font-label">
                      All day
                    </span>
                  ) : (
                    <span className="text-primary font-label font-medium w-14 text-right">
                      {formatTime(event.start)}
                    </span>
                  )}
                  <span className="text-on-surface">{event.title}</span>
                </div>
              ))}
              {data.tomorrow_preview.length > 0 && (
                <div className="pt-2 border-t border-outline-variant/20 text-xs text-on-surface-variant">
                  <span className="font-label uppercase tracking-wider">Tomorrow: </span>
                  {data.tomorrow_preview.map((e) => e.title).join(", ")}
                </div>
              )}
            </div>
          </CollapsibleContent>
        </Collapsible>
      </div>
    </div>
  );
}
