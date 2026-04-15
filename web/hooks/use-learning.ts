"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  LearningItem,
  LearningSection,
  LearningTopic,
  LearningTreeResponse,
} from "@/lib/types";
import { toast } from "sonner";

interface UseLearningReturn {
  topics: LearningTopic[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  createTopic: (name: string, depth?: "foundational" | "deep") => Promise<void>;
  toggleTopicActive: (id: string, isActive: boolean) => Promise<void>;
  createSection: (topicId: string, name: string) => Promise<void>;
  createItem: (sectionId: string, title: string) => Promise<void>;
  updateItem: (id: string, patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>) => Promise<void>;
  triggerRefresh: () => Promise<void>;
}

export function useLearning(): UseLearningReturn {
  const [topics, setTopics] = useState<LearningTopic[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTree = useCallback(async () => {
    try {
      const res = await api<LearningTreeResponse>("GET", "/v1/learning");
      setTopics(res.topics);
      setError(null);
    } catch {
      setError("Failed to load learning library");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTree();
  }, [fetchTree]);

  const createTopic = useCallback(
    async (name: string, depth: "foundational" | "deep" = "foundational") => {
      try {
        await api("POST", "/v1/learning/topics", { name, depth });
        await fetchTree();
        toast.success("Topic created");
      } catch {
        toast.error("Failed to create topic");
      }
    },
    [fetchTree],
  );

  const toggleTopicActive = useCallback(
    async (id: string, isActive: boolean) => {
      setTopics((prev) => prev.map((t) => (t.id === id ? { ...t, is_active: isActive } : t)));
      try {
        await api("PATCH", `/v1/learning/topics/${id}`, { is_active: isActive });
      } catch {
        toast.error("Failed to toggle topic");
        await fetchTree();
      }
    },
    [fetchTree],
  );

  const createSection = useCallback(
    async (topicId: string, name: string) => {
      try {
        await api<LearningSection>("POST", "/v1/learning/sections", { topic_id: topicId, name });
        await fetchTree();
      } catch {
        toast.error("Failed to create section");
      }
    },
    [fetchTree],
  );

  const createItem = useCallback(
    async (sectionId: string, title: string) => {
      try {
        await api<LearningItem>("POST", "/v1/learning/items", { section_id: sectionId, title });
        await fetchTree();
      } catch {
        toast.error("Failed to create item");
      }
    },
    [fetchTree],
  );

  const updateItem = useCallback(
    async (
      id: string,
      patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
    ) => {
      try {
        await api<LearningItem>("PATCH", `/v1/learning/items/${id}`, patch);
        await fetchTree();
      } catch {
        toast.error("Failed to update item");
      }
    },
    [fetchTree],
  );

  const triggerRefresh = useCallback(async () => {
    try {
      const res = await api<{ created: number; fallback: boolean }>(
        "POST",
        "/v1/learning/refresh",
      );
      toast.success(
        `Created ${res.created} learning todo${res.created === 1 ? "" : "s"}${
          res.fallback ? " (fallback)" : ""
        }`,
      );
    } catch {
      toast.error("Failed to trigger refresh");
    }
  }, []);

  return {
    topics,
    loading,
    error,
    refresh: fetchTree,
    createTopic,
    toggleTopicActive,
    createSection,
    createItem,
    updateItem,
    triggerRefresh,
  };
}
