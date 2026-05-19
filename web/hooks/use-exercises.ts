"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { Exercise } from "@/lib/types";

export function useExercises() {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const data = await api<Exercise[]>("GET", "/v1/exercises");
      setExercises(data);
    } catch {
      // Silently fail — library may be empty on first use
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { exercises, loading, refresh };
}
