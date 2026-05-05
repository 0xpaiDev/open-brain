"use client";

import { useState } from "react";
import { useProjectLabels } from "@/hooks/use-project-labels";
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

export default function SettingsPage() {
  const { labels, loading, createLabel, deleteLabel, renameLabel } = useProjectLabels();
  const [editingProjectName, setEditingProjectName] = useState<string | null>(null);
  const [editingDraft, setEditingDraft] = useState("");
  const [renameSubmitting, setRenameSubmitting] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState(PRESET_COLORS[0]);
  const [submitting, setSubmitting] = useState(false);

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
            {labels.map((label) => {
              const isEditing = editingProjectName === label.name;
              async function commitRename() {
                if (renameSubmitting) return;
                const trimmed = editingDraft.trim();
                if (!trimmed || trimmed === label.name) {
                  setEditingProjectName(null);
                  return;
                }
                setRenameSubmitting(true);
                try {
                  const ok = await renameLabel(label.name, trimmed);
                  if (ok) setEditingProjectName(null);
                } finally {
                  setRenameSubmitting(false);
                }
              }
              return (
                <li
                  key={label.id}
                  className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg hover:bg-surface-container-low transition-colors group"
                >
                  <div className="flex items-center gap-3 flex-1 min-w-0">
                    <span
                      className="w-3 h-3 rounded-full shrink-0"
                      style={{ backgroundColor: label.color }}
                    />
                    {isEditing ? (
                      <input
                        type="text"
                        value={editingDraft}
                        onChange={(e) => setEditingDraft(e.target.value)}
                        autoFocus
                        maxLength={100}
                        disabled={renameSubmitting}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void commitRename();
                          } else if (e.key === "Escape") {
                            e.preventDefault();
                            setEditingProjectName(null);
                          }
                        }}
                        onBlur={() => void commitRename()}
                        aria-label={`Rename project ${label.name}`}
                        className="flex-1 min-w-0 bg-surface-container-low border border-outline-variant/15 rounded-md px-2 py-1 text-base md:text-sm text-on-surface focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    ) : (
                      <span className="text-sm font-body text-on-surface truncate">
                        {label.name}
                      </span>
                    )}
                  </div>
                  {!isEditing && (
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                      <button
                        type="button"
                        onClick={() => {
                          setEditingDraft(label.name);
                          setEditingProjectName(label.name);
                        }}
                        className="text-outline hover:text-on-surface min-w-9 min-h-9 flex items-center justify-center rounded-md hover:bg-surface-container-high"
                        aria-label={`Rename ${label.name}`}
                      >
                        <span className="material-symbols-outlined text-lg">edit</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteLabel(label.name)}
                        className="text-outline hover:text-error min-w-9 min-h-9 flex items-center justify-center rounded-md hover:bg-error/10"
                        aria-label={`Delete ${label.name}`}
                      >
                        <span className="material-symbols-outlined text-lg">close</span>
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
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
