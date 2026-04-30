"use client";

import { useState } from "react";
import type { TodoLabel, ProjectLabel } from "@/lib/types";
import type { AddTodoOptions } from "@/hooks/use-todos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { formatDateButtonText, getTomorrowDateString, PERSONAL } from "./task-utils";

function DatePickerDialog({
  dueDate,
  startDate,
  isRange,
  onApply,
  disabled,
}: {
  dueDate: string;
  startDate: string;
  isRange: boolean;
  onApply: (dueDate: string, startDate: string, isRange: boolean) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [localDue, setLocalDue] = useState(dueDate);
  const [localStart, setLocalStart] = useState(startDate);
  const [localRange, setLocalRange] = useState(isRange);

  function handleOpenChange(next: boolean) {
    if (next) {
      setLocalDue(dueDate);
      setLocalStart(startDate);
      setLocalRange(isRange);
    }
    setOpen(next);
  }

  function handleApply() {
    onApply(localDue, localRange ? localStart : "", localRange);
    setOpen(false);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <button
            type="button"
            disabled={disabled}
            className="flex items-center gap-2 text-sm px-3 py-2 rounded-full bg-surface-container hover:bg-surface-container-high transition-colors ring-1 ring-inset ring-outline-variant/10 active:scale-95"
            aria-label="Pick date"
          />
        }
      >
        <span className="material-symbols-outlined text-base">calendar_month</span>
        <span>{formatDateButtonText(dueDate)}</span>
      </DialogTrigger>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>Due Date</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3 px-1 py-2">
          <Input
            type="date"
            value={localDue}
            onChange={(e) => setLocalDue(e.target.value)}
            aria-label="Due date"
          />
          <label className="flex items-center gap-2 text-sm text-on-surface-variant">
            <input
              type="checkbox"
              checked={localRange}
              onChange={(e) => setLocalRange(e.target.checked)}
              className="accent-primary"
            />
            Date range
          </label>
          {localRange && (
            <Input
              type="date"
              value={localStart}
              onChange={(e) => setLocalStart(e.target.value)}
              aria-label="Start date"
            />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleApply}>
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export interface AddTaskFormProps {
  onAdd: (
    description: string,
    priority: "high" | "normal" | "low",
    options?: AddTodoOptions,
  ) => Promise<void>;
  labels: TodoLabel[];
  projects: ProjectLabel[];
  /** Project pre-selected on render and after submit. Use PERSONAL for the default bucket. */
  defaultProject?: string;
  /** When true, the project picker is hidden (used by per-group "Add to {Project}" composers). */
  lockProject?: boolean;
}

export function AddTaskForm({
  onAdd,
  labels,
  projects,
  defaultProject = PERSONAL,
  lockProject = false,
}: AddTaskFormProps) {
  const [description, setDescription] = useState("");
  const [priority, setPriority] = useState<"high" | "normal" | "low">("normal");
  const [dueDate, setDueDate] = useState(getTomorrowDateString());
  const [startDate, setStartDate] = useState("");
  const [isRange, setIsRange] = useState(false);
  const [label, setLabel] = useState("");
  const [project, setProject] = useState(defaultProject);
  const [adding, setAdding] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = description.trim();
    if (!trimmed) return;

    setAdding(true);
    try {
      // PERSONAL is a UI-only bucket — translate to null on the wire.
      const wireProject = project === PERSONAL ? null : project;
      await onAdd(trimmed, priority, {
        dueDate: dueDate || undefined,
        startDate: isRange && startDate ? startDate : undefined,
        label: label || undefined,
        project: wireProject,
      });
      setDescription("");
      setDueDate(getTomorrowDateString());
      setStartDate("");
      setPriority("normal");
      setIsRange(false);
      setLabel("");
      setProject(defaultProject);
    } finally {
      setAdding(false);
    }
  }

  function handleDateApply(newDue: string, newStart: string, newRange: boolean) {
    setDueDate(newDue);
    setStartDate(newStart);
    setIsRange(newRange);
  }

  return (
    <form onSubmit={handleSubmit} className="relative group mt-4">
      <div className="absolute -inset-0.5 bg-gradient-to-r from-primary/10 to-transparent rounded-full blur opacity-0 group-focus-within:opacity-20 transition duration-500" />

      <div className="relative bg-surface-container-low p-2 pr-2.5 rounded-2xl sm:rounded-full ring-1 ring-white/5 shadow-xl">
        <div className="flex flex-wrap items-center gap-y-2 sm:gap-x-3">
          <div className="flex-1 min-w-0 px-4 sm:px-6 flex items-center">
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={lockProject ? `Add to ${defaultProject}…` : "Add a task..."}
              disabled={adding}
              aria-label="Task description"
              className="w-full bg-transparent border-none focus:ring-0 text-on-surface placeholder:text-on-surface-variant text-base py-2.5 sm:py-3 outline-none disabled:opacity-50"
            />
          </div>

          <button
            type="submit"
            disabled={adding || !description.trim()}
            aria-label="Add task"
            className="w-10 h-10 sm:w-11 sm:h-11 flex items-center justify-center rounded-full bg-primary text-on-primary hover:bg-primary-dim transition-all shadow-lg active:scale-90 disabled:opacity-50 disabled:pointer-events-none shrink-0 group/add sm:order-last"
          >
            <span className="material-symbols-outlined text-xl sm:text-2xl transition-transform group-hover/add:rotate-90">
              add
            </span>
          </button>

          <div className="flex items-center gap-2 sm:gap-3 w-full sm:w-auto px-2 pr-3 sm:px-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-outline-variant/10 sm:order-2 flex-wrap">
            <div className="flex items-center bg-surface-container p-0.5 sm:p-1 rounded-full gap-0.5 sm:gap-1">
              {(["high", "normal", "low"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={`px-2.5 sm:px-3 py-1 sm:py-1.5 rounded-full text-xs font-label font-medium transition-all active:scale-95 ${
                    priority === p
                      ? "bg-primary text-on-primary font-semibold"
                      : "text-on-surface-variant hover:text-on-surface"
                  }`}
                >
                  {p === "high" ? "High" : p === "normal" ? "Med" : "Low"}
                </button>
              ))}
            </div>

            {!lockProject && (
              <Select value={project} onValueChange={(v) => setProject(v ?? PERSONAL)}>
                <SelectTrigger
                  size="sm"
                  className="rounded-full bg-surface-container ring-1 ring-inset ring-outline-variant/10 border-none"
                  aria-label="Project"
                >
                  <SelectValue placeholder="Project" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PERSONAL}>{PERSONAL}</SelectItem>
                  {projects.map((p) => (
                    <SelectItem key={p.id} value={p.name}>
                      <span className="flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: p.color }}
                        />
                        {p.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            {labels.length > 0 && (
              <Select value={label} onValueChange={(v) => setLabel(v ?? "")}>
                <SelectTrigger
                  size="sm"
                  className="rounded-full bg-surface-container ring-1 ring-inset ring-outline-variant/10 border-none"
                  aria-label="Label"
                >
                  <SelectValue placeholder="Label" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">None</SelectItem>
                  {labels.map((l) => (
                    <SelectItem key={l.name} value={l.name}>
                      <span className="flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: l.color }}
                        />
                        {l.name}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            <DatePickerDialog
              dueDate={dueDate}
              startDate={startDate}
              isRange={isRange}
              onApply={handleDateApply}
              disabled={adding}
            />
          </div>
        </div>
      </div>
    </form>
  );
}
