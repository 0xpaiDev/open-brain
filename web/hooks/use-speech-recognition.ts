"use client";

import { useState, useRef, useCallback, useEffect } from "react";

const VOICE_LANG_KEY = "ob_voice_lang";
const DEFAULT_LANG = "en-US";
const MAX_DURATION_MS = 5 * 60 * 1000; // 5 minutes
const RESTART_WINDOW_MS = 5_000; // sliding window for restart throttling
const MAX_RESTARTS_IN_WINDOW = 3;

function getSpeechRecognitionConstructor():
  | (new () => SpeechRecognition)
  | null {
  if (typeof window === "undefined") return null;
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function getVoiceLang(): string {
  if (typeof window === "undefined") return DEFAULT_LANG;
  return localStorage.getItem(VOICE_LANG_KEY) || DEFAULT_LANG;
}

interface UseSpeechRecognitionReturn {
  isSupported: boolean;
  isListening: boolean;
  transcript: string;
  interimTranscript: string;
  error: string | null;
  startListening: () => void;
  stopListening: () => void;
  resetTranscript: () => void;
}

export function useSpeechRecognition(): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [interimTranscript, setInterimTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);

  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const isListeningRef = useRef(false);
  const restartTimesRef = useRef<number[]>([]);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isSupported = getSpeechRecognitionConstructor() !== null;

  const cleanup = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (recognitionRef.current) {
      recognitionRef.current.onresult = null;
      recognitionRef.current.onerror = null;
      recognitionRef.current.onend = null;
      recognitionRef.current.abort();
      recognitionRef.current = null;
    }
    isListeningRef.current = false;
    restartTimesRef.current = [];
  }, []);

  const stopListening = useCallback(() => {
    isListeningRef.current = false;
    setIsListening(false);
    setInterimTranscript("");
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (recognitionRef.current) {
      recognitionRef.current.stop();
    }
  }, []);

  const startListening = useCallback(() => {
    const Ctor = getSpeechRecognitionConstructor();
    if (!Ctor) return;

    // Clean up any existing instance
    cleanup();
    setError(null);
    setInterimTranscript("");

    const recognition = new Ctor();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = getVoiceLang();

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let finalText = "";
      let interim = "";

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalText += result[0].transcript;
        } else {
          interim += result[0].transcript;
        }
      }

      if (finalText) {
        setTranscript((prev) => prev + finalText);
      }
      setInterimTranscript(interim);
    };

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // no-speech is expected during natural pauses in continuous mode
      if (event.error === "no-speech" && isListeningRef.current) {
        return;
      }

      const errorMap: Record<string, string> = {
        "not-allowed": "Microphone access denied. Please allow microphone permissions.",
        "no-speech": "No speech detected. Try again.",
        network: "Network error. Speech recognition requires an internet connection.",
        aborted: "",  // Intentional abort, no error message
      };

      const message = errorMap[event.error] ?? `Speech recognition error: ${event.error}`;
      if (message) {
        setError(message);
      }

      // Don't auto-restart on permission or abort errors
      if (event.error === "not-allowed" || event.error === "aborted") {
        isListeningRef.current = false;
        setIsListening(false);
        if (timeoutRef.current) {
          clearTimeout(timeoutRef.current);
          timeoutRef.current = null;
        }
      }
    };

    recognition.onend = () => {
      setInterimTranscript("");

      if (!isListeningRef.current) return;

      // Time-windowed restart: allow restarts unless too many happened recently
      const now = Date.now();
      restartTimesRef.current = restartTimesRef.current.filter(
        (t) => now - t < RESTART_WINDOW_MS
      );

      if (restartTimesRef.current.length < MAX_RESTARTS_IN_WINDOW) {
        restartTimesRef.current.push(now);
        try {
          recognition.start();
        } catch {
          // start() can throw if called too quickly
          isListeningRef.current = false;
          setIsListening(false);
        }
        return;
      }

      // Exhausted restarts within window — genuine failure
      isListeningRef.current = false;
      setIsListening(false);
    };

    recognitionRef.current = recognition;
    isListeningRef.current = true;
    restartTimesRef.current = [];
    setIsListening(true);

    // Auto-stop after 5 minutes
    timeoutRef.current = setTimeout(() => {
      stopListening();
      setError("Recording stopped — 5 minute limit reached.");
    }, MAX_DURATION_MS);

    try {
      recognition.start();
    } catch {
      isListeningRef.current = false;
      setIsListening(false);
      setError("Failed to start speech recognition.");
    }
  }, [cleanup, stopListening]);

  const resetTranscript = useCallback(() => {
    setTranscript("");
    setInterimTranscript("");
    setError(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return cleanup;
  }, [cleanup]);

  return {
    isSupported,
    isListening,
    transcript,
    interimTranscript,
    error,
    startListening,
    stopListening,
    resetTranscript,
  };
}
