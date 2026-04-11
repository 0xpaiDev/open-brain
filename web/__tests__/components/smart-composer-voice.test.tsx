import { describe, test, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SmartComposer } from "@/components/memory/smart-composer";
import type { VoiceCommandResponse } from "@/lib/types";

// Mock hooks
vi.mock("@/hooks/use-project-labels", () => ({
  useProjectLabels: () => ({ labels: [], loading: false }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() },
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

const mockOnVoiceCommand = vi.fn();

function makeVoiceResponse(
  action: VoiceCommandResponse["action"],
  message: string,
): VoiceCommandResponse {
  return { action, entity_id: null, title: null, confidence: 1.0, message };
}

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
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    expect(screen.getByRole("tab", { name: /voice/i })).toBeDefined();
  });

  test("shows mic button when speech is supported", () => {
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    expect(screen.getByRole("button", { name: /start recording/i })).toBeDefined();
  });

  test("shows unsupported message when speech is not available", () => {
    mockSpeechRecognition.isSupported = false;
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    expect(screen.getByText(/requires Chrome or Edge/i)).toBeDefined();
  });

  test("clicking mic button calls startListening", () => {
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /start recording/i }));
    expect(mockSpeechRecognition.startListening).toHaveBeenCalled();
  });

  test("clicking stop button calls stopListening when recording", () => {
    mockSpeechRecognition.isListening = true;
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /stop recording/i }));
    expect(mockSpeechRecognition.stopListening).toHaveBeenCalled();
  });

  test("commit calls onVoiceCommand with transcript and shows success toast for 'created'", async () => {
    const { toast } = await import("sonner");
    mockOnVoiceCommand.mockResolvedValue(
      makeVoiceResponse("created", 'Added todo: "buy groceries"'),
    );
    mockSpeechRecognition.transcript = "buy groceries tomorrow";

    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(mockOnVoiceCommand).toHaveBeenCalledWith("buy groceries tomorrow");
      expect(toast.success).toHaveBeenCalledWith('Added todo: "buy groceries"');
      expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
    });
  });

  test("shows success toast and resets transcript for 'completed' action", async () => {
    const { toast } = await import("sonner");
    mockOnVoiceCommand.mockResolvedValue(
      makeVoiceResponse("completed", 'Completed: "buy groceries"'),
    );
    mockSpeechRecognition.transcript = "finish buy groceries";

    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith('Completed: "buy groceries"');
      expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
    });
  });

  test("shows success toast and resets transcript for 'memory' action", async () => {
    const { toast } = await import("sonner");
    mockOnVoiceCommand.mockResolvedValue(
      makeVoiceResponse("memory", "Saved to memory."),
    );
    mockSpeechRecognition.transcript = "remember to drink water";

    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith("Saved to memory.");
      expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
    });
  });

  test("shows warning toast and preserves transcript for 'ambiguous' action", async () => {
    const { toast } = await import("sonner");
    mockOnVoiceCommand.mockResolvedValue(
      makeVoiceResponse(
        "ambiguous",
        'No confident match for "um hello". Nothing was changed.',
      ),
    );
    mockSpeechRecognition.transcript = "um hello";

    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(toast.warning).toHaveBeenCalledWith(
        'No confident match for "um hello". Nothing was changed.',
      );
      expect(mockSpeechRecognition.resetTranscript).not.toHaveBeenCalled();
    });
  });

  test("shows error toast and preserves transcript when onVoiceCommand returns null", async () => {
    const { toast } = await import("sonner");
    mockOnVoiceCommand.mockResolvedValue(null);
    mockSpeechRecognition.transcript = "some voice note";

    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /commit memory/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Failed to process voice command");
      expect(mockSpeechRecognition.resetTranscript).not.toHaveBeenCalled();
    });
  });

  test("clear button calls resetTranscript", () => {
    mockSpeechRecognition.transcript = "some text to clear";
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    fireEvent.click(screen.getByRole("button", { name: /clear/i }));
    expect(mockSpeechRecognition.resetTranscript).toHaveBeenCalled();
  });

  test("displays error message when speech error occurs", () => {
    mockSpeechRecognition.error = "Microphone access denied.";
    render(<SmartComposer onIngest={vi.fn()} onVoiceCommand={mockOnVoiceCommand} />);
    fireEvent.click(screen.getByRole("tab", { name: /voice/i }));
    expect(screen.getByText(/Microphone access denied/i)).toBeDefined();
  });
});
