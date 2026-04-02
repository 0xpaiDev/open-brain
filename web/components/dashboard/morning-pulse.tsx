"use client";

import { useState } from "react";
import { usePulse } from "@/hooks/use-pulse";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

const SLEEP_LABELS = ["terrible", "poor", "okay", "good", "excellent"];
const ENERGY_LABELS = ["drained", "low", "moderate", "good", "charged"];

function RatingCircles({
  value,
  onChange,
  icon,
  filledIcon,
  labels,
}: {
  value: number;
  onChange: (v: number) => void;
  icon: string;
  filledIcon: string;
  labels: string[];
}) {
  return (
    <div className="flex items-center gap-2">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          onClick={() => onChange(n)}
          className={`w-9 h-9 rounded-full flex items-center justify-center text-sm transition-all active:scale-90 ${
            n <= value
              ? "bg-primary text-on-primary"
              : "bg-surface-container-high text-on-surface-variant border border-outline-variant"
          }`}
          title={labels[n - 1]}
        >
          <span
            className="material-symbols-outlined text-base"
            style={{ fontVariationSettings: n <= value ? "'FILL' 1" : "'FILL' 0" }}
          >
            {n <= value ? filledIcon : icon}
          </span>
        </button>
      ))}
      {value > 0 && (
        <span className="text-xs text-on-surface-variant ml-1 capitalize">
          {labels[value - 1]}
        </span>
      )}
    </div>
  );
}

function PulseSkeleton() {
  return (
    <div className="bg-surface-container rounded-2xl p-6 space-y-4" role="status" aria-busy="true">
      <div className="h-6 w-40 bg-surface-container-high rounded-lg animate-pulse" />
      <div className="h-20 w-full bg-surface-container-high rounded-lg animate-pulse" />
      <div className="flex gap-4">
        <div className="h-10 w-32 bg-surface-container-high rounded-lg animate-pulse" />
        <div className="h-10 w-48 bg-surface-container-high rounded-lg animate-pulse" />
      </div>
      <div className="h-10 w-36 bg-surface-container-high rounded-lg animate-pulse" />
    </div>
  );
}

function NoPulse({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center gap-4 py-12">
      <span className="material-symbols-outlined text-4xl text-primary">
        wb_twilight
      </span>
      <p className="text-on-surface-variant text-center">
        Your day hasn&apos;t started yet
      </p>
      <Button
        onClick={onCreate}
        className="bg-gradient-to-r from-primary to-primary-container text-on-primary active:scale-95 transition-transform"
      >
        <span className="material-symbols-outlined text-base mr-1">play_arrow</span>
        Start your day
      </Button>
    </div>
  );
}

function PulseForm({
  aiQuestion,
  onSubmit,
}: {
  aiQuestion: string | null;
  onSubmit: (data: {
    wake_time?: string;
    sleep_quality?: number;
    energy_level?: number;
    ai_question_response?: string;
    notes?: string;
  }) => Promise<void>;
}) {
  const [wakeTime, setWakeTime] = useState("");
  const [sleepQuality, setSleepQuality] = useState(0);
  const [energyLevel, setEnergyLevel] = useState(0);
  const [answer, setAnswer] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({
        wake_time: wakeTime || undefined,
        sleep_quality: sleepQuality || undefined,
        energy_level: energyLevel || undefined,
        ai_question_response: answer || undefined,
        notes: notes || undefined,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-surface-container rounded-2xl p-6 space-y-5">
      <h2 className="text-xl font-headline font-semibold text-on-surface flex items-center gap-2">
        <span className="material-symbols-outlined text-primary">wb_twilight</span>
        Morning Pulse
      </h2>

      {aiQuestion && (
        <blockquote className="border-l-4 border-primary pl-4 py-2 italic text-on-surface-variant text-sm">
          {aiQuestion}
        </blockquote>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
        {/* Left column: question + notes */}
        <div className="space-y-4">
          {aiQuestion && (
            <div>
              <label className="block text-sm font-label text-on-surface-variant mb-1.5">
                Your answer
              </label>
              <Textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="What's on your mind..."
                className="min-h-[100px]"
              />
            </div>
          )}
          <div>
            <label className="block text-sm font-label text-on-surface-variant mb-1.5">
              Notes
            </label>
            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Anything else on your mind?"
              className="min-h-[80px]"
            />
          </div>
        </div>

        {/* Right column: metrics */}
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-label text-on-surface-variant mb-1.5">
              Wake-up time
            </label>
            <Input
              type="time"
              value={wakeTime}
              onChange={(e) => setWakeTime(e.target.value)}
              className="w-36"
            />
          </div>
          <div>
            <label className="block text-sm font-label text-on-surface-variant mb-1.5">
              Sleep quality
            </label>
            <RatingCircles
              value={sleepQuality}
              onChange={setSleepQuality}
              icon="star"
              filledIcon="star"
              labels={SLEEP_LABELS}
            />
          </div>
          <div>
            <label className="block text-sm font-label text-on-surface-variant mb-1.5">
              Energy level
            </label>
            <RatingCircles
              value={energyLevel}
              onChange={setEnergyLevel}
              icon="bolt"
              filledIcon="bolt"
              labels={ENERGY_LABELS}
            />
          </div>
        </div>
      </div>

      <Button
        type="submit"
        disabled={submitting}
        className="bg-gradient-to-r from-primary to-primary-container text-on-primary active:scale-95 transition-transform"
      >
        {submitting ? (
          <>
            <span className="material-symbols-outlined text-base animate-spin mr-1">progress_activity</span>
            Saving...
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-base mr-1">check_circle</span>
            Log my morning
          </>
        )}
      </Button>
    </form>
  );
}

function PulseSummary({ pulse }: { pulse: NonNullable<ReturnType<typeof usePulse>["pulse"]> }) {
  const formatTime = (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return iso;
    }
  };

  return (
    <div className="bg-surface-container-high rounded-2xl p-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="material-symbols-outlined text-primary text-xl">wb_twilight</span>
        <h2 className="text-lg font-headline font-semibold text-on-surface">Morning Pulse</h2>
        <span className="ml-auto text-xs text-on-surface-variant">
          Logged at {formatTime(pulse.updated_at)}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm">
        {pulse.wake_time && (
          <div className="flex items-center gap-1.5 text-on-surface-variant">
            <span className="material-symbols-outlined text-base">schedule</span>
            <span>{pulse.wake_time}</span>
          </div>
        )}

        {pulse.sleep_quality && (
          <div className="flex items-center gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <span
                key={n}
                className="material-symbols-outlined text-base text-primary"
                style={{ fontVariationSettings: n <= pulse.sleep_quality! ? "'FILL' 1" : "'FILL' 0" }}
              >
                star
              </span>
            ))}
          </div>
        )}

        {pulse.energy_level && (
          <div className="flex items-center gap-0.5">
            {[1, 2, 3, 4, 5].map((n) => (
              <span
                key={n}
                className="material-symbols-outlined text-base text-tertiary"
                style={{
                  fontVariationSettings: n <= pulse.energy_level! ? "'FILL' 1" : "'FILL' 0",
                  opacity: n <= pulse.energy_level! ? 1 : 0.3,
                }}
              >
                bolt
              </span>
            ))}
          </div>
        )}
      </div>

      {pulse.ai_question && pulse.ai_question_response && (
        <div className="mt-3 text-sm">
          <p className="text-on-surface-variant italic line-clamp-1">Q: {pulse.ai_question}</p>
          <p className="text-on-surface line-clamp-2 mt-0.5">A: {pulse.ai_question_response}</p>
        </div>
      )}

      {pulse.notes && (
        <p className="mt-2 text-sm text-on-surface-variant line-clamp-2">{pulse.notes}</p>
      )}
    </div>
  );
}

export function MorningPulse() {
  const { pulse, loading, error, createPulse, submitPulse } = usePulse();

  if (loading) return <PulseSkeleton />;
  if (error) {
    return (
      <div className="bg-surface-container rounded-2xl p-6 flex flex-col items-center justify-center text-center" role="alert">
        <span className="material-symbols-outlined text-error text-2xl mb-2">error</span>
        <p className="text-sm text-error">{error}</p>
      </div>
    );
  }
  if (!pulse) return <NoPulse onCreate={createPulse} />;
  if (pulse.status === "sent") {
    return <PulseForm aiQuestion={pulse.ai_question} onSubmit={submitPulse} />;
  }
  return <PulseSummary pulse={pulse} />;
}
