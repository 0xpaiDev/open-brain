import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MorningPulse } from "@/components/dashboard/morning-pulse";

// Mock usePulse to return a sent pulse with bullet briefing
vi.mock("@/hooks/use-pulse", () => ({
  usePulse: () => ({
    pulse: {
      id: "1",
      pulse_date: "2026-05-21T00:00:00Z",
      status: "sent",
      ai_question: "• Today: Paulius's birthday\n• 3 open tasks — nothing else scheduled",
      ai_question_response: null,
      wake_time: null,
      sleep_quality: null,
      energy_level: null,
      clean_meal: null,
      alcohol: null,
      signal_type: "briefing",
      parsed_data: null,
      created_at: "2026-05-21T04:00:00Z",
      updated_at: "2026-05-21T04:00:00Z",
    },
    loading: false,
    error: null,
    createPulse: vi.fn(),
    submitPulse: vi.fn(),
  }),
}));

describe("MorningPulse briefing rendering", () => {
  it("renders each bullet as a list item", () => {
    render(<MorningPulse />);
    expect(screen.getByText("Today: Paulius's birthday")).toBeInTheDocument();
    expect(screen.getByText("3 open tasks — nothing else scheduled")).toBeInTheDocument();
  });

  it("does not render a notes textarea", () => {
    render(<MorningPulse />);
    expect(screen.queryByPlaceholderText("Anything else on your mind?")).toBeNull();
  });
});
