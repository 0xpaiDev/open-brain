import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SmartComposer } from "@/components/memory/smart-composer";

// Mock hooks
vi.mock("@/hooks/use-project-labels", () => ({
  useProjectLabels: () => ({ labels: [], loading: false }),
}));

const mockSpeechRecognition = {
  isSupported: true,
  isListening: false,
  transcript: "",
  interimTranscript: "",
  error: null,
  startListening: vi.fn(),
  stopListening: vi.fn(),
  resetTranscript: vi.fn(),
};

vi.mock("@/hooks/use-speech-recognition", () => ({
  useSpeechRecognition: () => mockSpeechRecognition,
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockSpeechRecognition.isSupported = true;
  mockSpeechRecognition.isListening = false;
  mockSpeechRecognition.transcript = "";
  mockSpeechRecognition.interimTranscript = "";
  mockSpeechRecognition.error = null;
});

describe("SmartComposer Voice Tab", () => {
  test("renders Voice tab trigger", () => {
    render(<SmartComposer onIngest={vi.fn()} />);
    expect(screen.getByRole("tab", { name: /voice/i })).toBeDefined();
  });

  test("shows mic button when speech is supported", () => {
    render(<SmartComposer onIngest={vi.fn()} />);

    // Click the Voice tab
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    expect(screen.getByRole("button", { name: /start recording/i })).toBeDefined();
  });

  test("shows unsupported message when speech is not available", () => {
    mockSpeechRecognition.isSupported = false;

    render(<SmartComposer onIngest={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    expect(screen.getByText(/requires Chrome or Edge/i)).toBeDefined();
  });

  test("clicking mic button calls startListening", () => {
    render(<SmartComposer onIngest={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /start recording/i }));

    expect(mockSpeechRecognition.startListening).toHaveBeenCalled();
  });

  test("clicking stop button calls stopListening when recording", () => {
    mockSpeechRecognition.isListening = true;

    render(<SmartComposer onIngest={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /stop recording/i }));

    expect(mockSpeechRecognition.stopListening).toHaveBeenCalled();
  });

  test("commit button calls onIngest with voice source and metadata", async () => {
    const onIngest = vi.fn().mockResolvedValue(true);
    mockSpeechRecognition.transcript = "buy groceries tomorrow";

    render(<SmartComposer onIngest={onIngest} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    const commitBtn = screen.getByRole("button", { name: /commit memory/i });
    fireEvent.click(commitBtn);

    await waitFor(() => {
      expect(onIngest).toHaveBeenCalledWith(
        "buy groceries tomorrow",
        "voice",
        { transcription_method: "web_speech_api" },
      );
    });
  });

  test("successful commit resets transcript", async () => {
    const onIngest = vi.fn().mockResolvedValue(true);
    mockSpeechRecognition.transcript = "some voice note";

    render(<SmartComposer onIngest={onIngest} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
    });
  });

  test("clear button calls resetTranscript", () => {
    mockSpeechRecognition.transcript = "some text to clear";

    render(<SmartComposer onIngest={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
  });

  test("displays error message when speech error occurs", () => {
    mockSpeechRecognition.error = "Microphone access denied.";

    render(<SmartComposer onIngest={vi.fn()} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));

    expect(screen.getByText(/Microphone access denied/i)).toBeDefined();
  });
});
