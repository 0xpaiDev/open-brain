"use client";

import { useState, useEffect, useCallback } from "react";
import { api, ApiError } from "@/lib/api";
import type { PulseResponse, PulseUpdate } from "@/lib/types";
import { toast } from "sonner";

interface UsePulseReturn {
  pulse: PulseResponse | null;
  loading: boolean;
  error: string | null;
  createPulse: () => Promise<void>;
  submitPulse: (data: Omit<PulseUpdate, "status">) => Promise<void>;
}

export function usePulse(): UsePulseReturn {
  const [pulse, setPulse] = useState<PulseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPulse() {
      try {
        const data = await api<PulseResponse>("GET", "/v1/pulse/today");
        if (!cancelled) setPulse(data);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setPulse(null);
        } else {
          setError("Failed to load pulse");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchPulse();
    return () => {
      cancelled = true;
    };
  }, []);

  const createPulse = useCallback(async () => {
    try {
      setLoading(true);
      const data = await api<PulseResponse>("POST", "/v1/pulse/start");
      setPulse(data);
      toast.success("Day started!");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        try {
          const existing = await api<PulseResponse>("GET", "/v1/pulse/today");
          setPulse(existing);
        } catch {
          toast.error("Failed to load existing pulse");
        }
      } else {
        toast.error("Failed to start your day");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const submitPulse = useCallback(async (data: Omit<PulseUpdate, "status">) => {
    try {
      const updated = await api<PulseResponse>("PATCH", "/v1/pulse/today", {
        ...data,
        status: "completed",
      });
      setPulse(updated);
      toast.success("Morning pulse logged");
    } catch {
      toast.error("Failed to save pulse");
    }
  }, []);

  return { pulse, loading, error, createPulse, submitPulse };
}
