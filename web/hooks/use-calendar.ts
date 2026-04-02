"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import type { CalendarResponse } from "@/lib/types";

interface UseCalendarReturn {
  data: CalendarResponse | null;
  loading: boolean;
  error: string | null;
}

export function useCalendar(): UseCalendarReturn {
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchCalendar() {
      try {
        const res = await api<CalendarResponse>("GET", "/v1/calendar/today");
        if (!cancelled) setData(res);
      } catch {
        if (!cancelled) setError("Failed to load calendar");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchCalendar();
    return () => {
      cancelled = true;
    };
  }, []);

  return { data, loading, error };
}
