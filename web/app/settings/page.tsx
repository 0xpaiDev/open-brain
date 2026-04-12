"use client";

import { useState } from "react";
import { useProjectLabels } from "@/hooks/use-project-labels";
import { useCommitments } from "@/hooks/use-commitments";
import { ModelSelector } from "@/components/chat/model-selector";

const MODEL_STORAGE_KEY = "ob_chat_model";
const DEFAULT_MODEL = "claude-haiku-4-5-20251001";
const VOICE_LANG_KEY = "ob_voice_lang";
const DEFAULT_VOICE_LANG = "en-US";

const VOICE_LANGUAGES = [
  { value: "en-US", label: "English (US)" },
  { value: "lt-LT", label: "Lithuanian" },
  { value: "de-DE", label: "German" },
  { value: "ru-RU", label: "Russian" },
  { value: "pl-PL", label: "Polish" },
  { value: "fr-FR", label: "French" },
  { value: "es-ES", label: "Spanish" },
];

const PRESET_COLORS = [
  "#6750A4", "#E8175D", "#0B57D0", "#0D652D", "#E65100",
  "#6D4C41", "#546E7A", "#7B1FA2", "#00838F", "#AD1457",
];

const METRICS = [
  { value: "reps", label: "Reps" },
  { value: "minutes", label: "Minutes" },
  { value: "tss", label: "TSS" },
];

const AGGREGATE_METRICS = [
  { value: "km", label: "Kilometers" },
  { value: "tss", label: "TSS" },
  { value: "minutes", label: "Minutes" },
  { value: "hours", label: "Hours" },
  { value: "elevation_m", label: "Elevation (m)" },
];

export default function SettingsPage() {
  const { labels, loading, createLabel, deleteLabel } = useProjectLabels();
  const {
    commitments,
    loading: commitmentsLoading,
    createCommitment,
    abandonCommitment,
  } = useCommitments("all");
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(PRESET_COLORS[0]);
  const [submitting, setSubmitting] = useState(false);

  // Commitment form state
  const [cmtName, setCmtName] = useState("");
  const [cmtExercise, setCmtExercise] = useState("");
  const [cmtTarget, setCmtTarget] = useState("");
  const [cmtMetric, setCmtMetric] = useState("reps");
  const [cmtCadence, setCmtCadence] = useState<"daily" | "aggregate">("daily");
  const [cmtAggMetric, setCmtAggMetric] = useState("km");
  const [cmtAggTarget, setCmtAggTarget] = useState("");
  const [cmtStart, setCmtStart] = useState(() => new Date().toISOString().slice(0, 10));
  const [cmtEnd, setCmtEnd] = useState("");
  const [cmtSubmitting, setCmtSubmitting] = useState(false);

  const cmtFormValid = cmtCadence === "daily"
    ? cmtName.trim() && cmtExercise.trim() && cmtTarget && cmtEnd
    : cmtName.trim() && cmtExercise.trim() && cmtAggTarget && cmtEnd;

  async function handleCreateCommitment(e: React.FormEvent) {
    e.preventDefault();
    if (!cmtFormValid || cmtSubmitting) return;
    setCmtSubmitting(true);

    if (cmtCadence === "daily") {
      await createCommitment({
        name: cmtName.trim(),
        exercise: cmtExercise.trim(),
        daily_target: parseInt(cmtTarget, 10),
        metric: cmtMetric,
        cadence: "daily",
        start_date: cmtStart,
        end_date: cmtEnd,
      });
    } else {
      await createCommitment({
        name: cmtName.trim(),
        exercise: cmtExercise.trim(),
        daily_target: 0,
        cadence: "aggregate",
        targets: { [cmtAggMetric]: parseFloat(cmtAggTarget) },
        start_date: cmtStart,
        end_date: cmtEnd,
      });
    }

    setCmtSubmitting(false);
    setCmtName("");
    setCmtExercise("");
    setCmtTarget("");
    setCmtAggTarget("");
    setCmtEnd("");
  }

  // RAG Chat model preference (read/write localStorage directly)
  const [chatModel, setChatModel] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem(MODEL_STORAGE_KEY) ?? DEFAULT_MODEL
      : DEFAULT_MODEL
  );
  const [voiceLang, setVoiceLang] = useState(() =>
    typeof window !== "undefined"
      ? localStorage.getItem(VOICE_LANG_KEY) ?? DEFAULT_VOICE_LANG
      : DEFAULT_VOICE_LANG
  );
  function handleModelChange(model: string) {
    setChatModel(model);
    localStorage.setItem(MODEL_STORAGE_KEY, model);
  }
  function handleVoiceLangChange(lang: string) {
    setVoiceLang(lang);
    localStorage.setItem(VOICE_LANG_KEY, lang);
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim() || submitting) return;

    setSubmitting(true);
    await createLabel(newName.trim(), newColor);
    setSubmitting(false);
    setNewName("");
  }

  return (
    <div className="py-8 space-y-8 max-w-2xl">
      <div>
        <h1 className="text-3xl font-headline font-bold text-primary mb-2">
          Settings
        </h1>
        <p className="text-on-surface-variant text-sm">
          Manage your Open Brain configuration.
        </p>
      </div>

      {/* RAG Chat section */}
      <section className="bg-surface-container rounded-2xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface mb-1">
            RAG Chat
          </h2>
          <p className="text-xs text-outline font-body">
            Configure the model used for chat conversations.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-on-surface-variant font-body">Model</span>
          <ModelSelector
            model={chatModel}
            onModelChange={handleModelChange}
            disabled={false}
          />
        </div>
      </section>

      {/* Voice Input section */}
      <section className="bg-surface-container rounded-2xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface mb-1">
            Voice Input
          </h2>
          <p className="text-xs text-outline font-body">
            Configure language for voice note transcription.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-on-surface-variant font-body">Language</span>
          <select
            value={voiceLang}
            onChange={(e) => handleVoiceLangChange(e.target.value)}
            className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
          >
            {VOICE_LANGUAGES.map((lang) => (
              <option key={lang.value} value={lang.value}>
                {lang.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      {/* Commitments section */}
      <section className="bg-surface-container rounded-2xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface mb-1">
            Commitments
          </h2>
          <p className="text-xs text-outline font-body">
            Create and manage training challenges (daily or period-based).
          </p>
        </div>

        {/* Commitment list */}
        {commitmentsLoading ? (
          <div className="flex items-center gap-2 py-4">
            <div className="h-3 w-32 rounded bg-outline-variant/20 animate-pulse" />
          </div>
        ) : commitments.length === 0 ? (
          <p className="text-sm text-outline py-2">
            No commitments yet. Create one below.
          </p>
        ) : (
          <ul className="space-y-1">
            {commitments.map((c) => {
              const totalDays = Math.ceil(
                (new Date(c.end_date).getTime() - new Date(c.start_date).getTime()) / 86400000
              ) + 1;
              const hits = c.entries.filter((e) => e.status === "hit").length;
              return (
                <li
                  key={c.id}
                  className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors group"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <span className={`text-xs font-body px-2 py-0.5 rounded-full ${
                      c.status === "active"
                        ? "bg-streak-hit/20 text-streak-hit"
                        : c.status === "completed"
                          ? "bg-primary/20 text-primary"
                          : "bg-outline/20 text-outline"
                    }`}>
                      {c.status}
                    </span>
                    <span className="text-sm font-body text-on-surface truncate">
                      {c.name}
                    </span>
                    <span className="text-xs text-on-surface-variant">
                      {c.cadence === "aggregate"
                        ? Object.entries(c.targets ?? {}).map(([k, v]) => `${v} ${k}`).join(", ")
                        : `${hits}/${totalDays} days · ${c.daily_target} ${c.metric}/day`}
                    </span>
                  </div>
                  {c.status === "active" && (
                    <button
                      onClick={() => abandonCommitment(c.id)}
                      className="text-outline hover:text-error opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                      title="Abandon commitment"
                    >
                      <span className="material-symbols-outlined text-lg">close</span>
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        {/* New commitment form */}
        <form
          onSubmit={handleCreateCommitment}
          className="space-y-3 pt-2 border-t border-outline-variant/10"
        >
          {/* Cadence toggle */}
          <div className="flex gap-2">
            {(["daily", "aggregate"] as const).map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setCmtCadence(c)}
                className={`px-3 py-1.5 rounded-lg text-base md:text-sm font-body cursor-pointer transition-colors ${
                  cmtCadence === c
                    ? "bg-primary text-on-primary"
                    : "bg-surface-container-high text-on-surface-variant hover:bg-surface-container-low"
                }`}
              >
                {c === "daily" ? "Daily" : "Period"}
              </button>
            ))}
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <input
              type="text"
              value={cmtName}
              onChange={(e) => setCmtName(e.target.value)}
              placeholder="Challenge name"
              maxLength={100}
              className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
            />
            <input
              type="text"
              value={cmtExercise}
              onChange={(e) => setCmtExercise(e.target.value)}
              placeholder={cmtCadence === "daily" ? "Exercise (e.g. push-ups)" : "Exercise (e.g. cycling)"}
              maxLength={100}
              className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>

          {/* Daily-specific fields */}
          {cmtCadence === "daily" && (
            <div className="grid grid-cols-3 gap-3">
              <input
                type="number"
                value={cmtTarget}
                onChange={(e) => setCmtTarget(e.target.value)}
                placeholder="Daily target"
                min={1}
                className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <select
                value={cmtMetric}
                onChange={(e) => setCmtMetric(e.target.value)}
                className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
              >
                {METRICS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <div />
            </div>
          )}

          {/* Aggregate-specific fields */}
          {cmtCadence === "aggregate" && (
            <div className="grid grid-cols-3 gap-3">
              <select
                value={cmtAggMetric}
                onChange={(e) => setCmtAggMetric(e.target.value)}
                className="bg-surface-container-low border border-outline-variant/15 text-on-surface text-base md:text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-primary appearance-none cursor-pointer"
              >
                {AGGREGATE_METRICS.map((m) => (
                  <option key={m.value} value={m.value}>{m.label}</option>
                ))}
              </select>
              <input
                type="number"
                value={cmtAggTarget}
                onChange={(e) => setCmtAggTarget(e.target.value)}
                placeholder="Period target"
                min={1}
                step="any"
                className="bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <div />
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">Start date</label>
              <input
                type="date"
                value={cmtStart}
                onChange={(e) => setCmtStart(e.target.value)}
                className="w-full bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
            <div>
              <label className="block text-xs text-on-surface-variant mb-1">End date</label>
              <input
                type="date"
                value={cmtEnd}
                onChange={(e) => setCmtEnd(e.target.value)}
                min={cmtStart}
                className="w-full bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={!cmtFormValid || cmtSubmitting}
            className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2 px-5 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none"
          >
            <span className="material-symbols-outlined text-sm">add</span>
            Create Commitment
          </button>
        </form>
      </section>

      {/* Projects section */}
      <section className="bg-surface-container rounded-2xl p-6 space-y-5">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface mb-1">
            Projects
          </h2>
          <p className="text-xs text-outline font-body">
            Tag memories with a project to organize and filter them.
          </p>
        </div>

        {/* Project list */}
        {loading ? (
          <div className="flex items-center gap-2 py-4">
            <div className="w-4 h-4 rounded-full bg-outline-variant/30 animate-pulse" />
            <div className="h-3 w-32 rounded bg-outline-variant/20 animate-pulse" />
          </div>
        ) : labels.length === 0 ? (
          <p className="text-sm text-outline py-2">
            No projects yet. Create one below.
          </p>
        ) : (
          <ul className="space-y-1">
            {labels.map((label) => (
              <li
                key={label.id}
                className="flex items-center justify-between px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors group"
              >
                <div className="flex items-center gap-3">
                  <span
                    className="w-3 h-3 rounded-full shrink-0"
                    style={{ backgroundColor: label.color }}
                  />
                  <span className="text-sm font-body text-on-surface">
                    {label.name}
                  </span>
                </div>
                <button
                  onClick={() => deleteLabel(label.name)}
                  className="text-outline hover:text-error opacity-0 group-hover:opacity-100 transition-opacity"
                  title={`Delete ${label.name}`}
                >
                  <span className="material-symbols-outlined text-lg">
                    close
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {/* Add project form */}
        <form
          onSubmit={handleCreate}
          className="flex flex-col sm:flex-row gap-3 pt-2 border-t border-outline-variant/10"
        >
          <div className="flex items-center gap-2 flex-1">
            {/* Color picker */}
            <div className="relative">
              <input
                type="color"
                value={newColor}
                onChange={(e) => setNewColor(e.target.value)}
                className="w-8 h-8 rounded-full border-2 border-outline-variant/20 cursor-pointer appearance-none bg-transparent [&::-webkit-color-swatch-wrapper]:p-0 [&::-webkit-color-swatch]:rounded-full [&::-webkit-color-swatch]:border-none [&::-moz-color-swatch]:rounded-full [&::-moz-color-swatch]:border-none"
                title="Pick a color"
              />
            </div>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Project name"
              maxLength={100}
              className="flex-1 bg-surface-container-low border border-outline-variant/15 rounded-lg px-3 py-2 text-base md:text-sm text-on-surface placeholder:text-outline/50 focus:outline-none focus:ring-1 focus:ring-primary"
            />
          </div>
          <button
            type="submit"
            disabled={!newName.trim() || submitting}
            className="bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-2 px-5 rounded-xl text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95 disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap"
          >
            <span className="material-symbols-outlined text-sm">add</span>
            Add Project
          </button>
        </form>
      </section>
    </div>
  );
}
