import { describe, test, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatThread } from "@/components/chat/chat-thread";
import type { ChatDisplayMessage } from "@/lib/types";

// Mock scrollIntoView
Element.prototype.scrollIntoView = vi.fn();

const USER_MSG: ChatDisplayMessage = {
  id: "u-1",
  role: "user",
  content: "What projects have I worked on?",
};

const ASSISTANT_MSG: ChatDisplayMessage = {
  id: "a-1",
  role: "assistant",
  content: "Here are your recent projects.",
  searchQuery: "recent projects",
  sources: [
    {
      id: "s-1",
      content: "Working on Open Brain — personal memory system",
      summary: "Open Brain project work",
      type: "context",
      importance_score: 0.8,
      combined_score: 0.92,
      project: "open-brain",
    },
  ],
};

describe("ChatThread", () => {
  test("renders empty state when no messages", () => {
    render(<ChatThread messages={[]} loading={false} error={null} />);

    expect(
      screen.getByText("Ask anything about your memories."),
    ).toBeInTheDocument();
  });

  test("renders user message", () => {
    render(
      <ChatThread messages={[USER_MSG]} loading={false} error={null} />,
    );

    expect(
      screen.getByText("What projects have I worked on?"),
    ).toBeInTheDocument();
  });

  test("renders assistant message with search query", () => {
    render(
      <ChatThread
        messages={[USER_MSG, ASSISTANT_MSG]}
        loading={false}
        error={null}
      />,
    );

    expect(
      screen.getByText("Here are your recent projects."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Searched for:.*"recent projects"/),
    ).toBeInTheDocument();
  });

  test("renders sources count", () => {
    render(
      <ChatThread
        messages={[USER_MSG, ASSISTANT_MSG]}
        loading={false}
        error={null}
      />,
    );

    expect(screen.getByText("Sources (1)")).toBeInTheDocument();
  });

  test("renders loading indicator", () => {
    render(<ChatThread messages={[USER_MSG]} loading={true} error={null} />);

    expect(screen.getByText("Thinking…")).toBeInTheDocument();
  });

  test("renders error message", () => {
    render(
      <ChatThread
        messages={[USER_MSG]}
        loading={false}
        error="API error: 500"
      />,
    );

    expect(screen.getByText("API error: 500")).toBeInTheDocument();
  });

  test("renders multiple messages in order", () => {
    const messages: ChatDisplayMessage[] = [
      USER_MSG,
      ASSISTANT_MSG,
      { id: "u-2", role: "user", content: "Tell me more" },
      {
        id: "a-2",
        role: "assistant",
        content: "More details here.",
        sources: [],
        searchQuery: "more details",
      },
    ];

    render(<ChatThread messages={messages} loading={false} error={null} />);

    expect(
      screen.getByText("What projects have I worked on?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Here are your recent projects."),
    ).toBeInTheDocument();
    expect(screen.getByText("Tell me more")).toBeInTheDocument();
    expect(screen.getByText("More details here.")).toBeInTheDocument();
  });

  test("does not render sources section when sources empty", () => {
    const msg: ChatDisplayMessage = {
      id: "a-empty",
      role: "assistant",
      content: "No sources found.",
      sources: [],
      searchQuery: "test",
    };

    render(<ChatThread messages={[msg]} loading={false} error={null} />);

    expect(screen.queryByText(/Sources/)).not.toBeInTheDocument();
  });
});
