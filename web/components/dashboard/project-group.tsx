"use client";

import { useState } from "react";
import type { TodoItem, TodoLabel, ProjectLabel } from "@/lib/types";
import type { AddTodoOptions } from "@/hooks/use-todos";
import { TaskRow } from "./task-row";
import { AddTaskForm } from "./add-task-form";
import { PERSONAL } from "./task-utils";

export interface ProjectGroupProps {
  name: string;
  color?: string;
  todos: TodoItem[];
  /** Total open todos in this project across all tabs (for the progress bar denominator). */
  totalInProject: number;
  collapsed: boolean;
  focusId: string | null;
  onToggleCollapsed: () => void;
  onSelectFocus: (id: string) => void;
  onComplete: (id: string) => void;
  onEdit: (id: string, description: string, dueDate: string | null, reason?: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onAdd: (
    description: string,
    priority: "high" | "normal" | "low",
    options?: AddTodoOptions,
  ) => Promise<void>;
  labels: TodoLabel[];
  projects: ProjectLabel[];
}

export function ProjectGroup({
  name,
  color,
  todos,
  totalInProject,
  collapsed,
  focusId,
  onToggleCollapsed,
  onSelectFocus,
  onComplete,
  onEdit,
  onDelete,
  onAdd,
  labels,
  projects,
}: ProjectGroupProps) {
  const [adding, setAdding] = useState(false);
  const accent = color ?? "var(--color-primary)";

  // Mini progress bar — proportion of "soon" tasks (overdue or due today/tomorrow).
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const tomorrow = new Date(today);
  tomorrow.setDate(tomorrow.getDate() + 1);

  let urgent = 0;
  for (const t of todos) {
    if (!t.due_date) continue;
    const d = new Date(t.due_date);
    d.setHours(0, 0, 0, 0);
    if (d <= tomorrow) urgent += 1;
  }
  const progressPct =
    todos.length === 0 ? 0 : Math.round((urgent / todos.length) * 100);

  return (
    <section className="mt-3 first:mt-2" aria-label={`${name} project group`}>
      <header className="flex items-center gap-2 px-1">
        <button
          type="button"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-controls={`project-group-${name}-body`}
          className="flex items-center gap-2 flex-1 min-w-0 py-1.5 rounded-md hover:bg-surface-container-high/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary cursor-pointer text-left"
        >
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: accent }}
            aria-hidden
          />
          <span className="text-xs font-label uppercase tracking-wider text-on-surface-variant truncate">
            {name}
          </span>
          <span
            className="h-[2.5px] w-9 rounded-full overflow-hidden shrink-0"
            style={{ backgroundColor: `${accent}33` }}
            aria-hidden
          >
            <span
              className="block h-full transition-[width] duration-300"
              style={{ width: `${progressPct}%`, backgroundColor: accent }}
            />
          </span>
          <span className="text-[11px] text-on-surface-variant tabular-nums">
            {todos.length}
            {totalInProject > todos.length ? `/${totalInProject}` : ""}
          </span>
          <span
            className={`material-symbols-outlined text-base text-on-surface-variant ml-auto transition-transform duration-200 ${
              collapsed ? "" : "rotate-180"
            }`}
            aria-hidden
          >
            expand_more
          </span>
        </button>
      </header>

      {!collapsed && (
        <div id={`project-group-${name}-body`} className="space-y-0.5 mt-1">
          {todos.map((todo) => (
            <TaskRow
              key={todo.id}
              todo={todo}
              focused={focusId === todo.id}
              accentColor={color}
              onSelectFocus={onSelectFocus}
              onComplete={onComplete}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          ))}

          {adding ? (
            <div className="pl-9 pr-1">
              <AddTaskForm
                onAdd={async (description, priority, options) => {
                  // Force this group's project regardless of caller's options.
                  const project = name === PERSONAL ? null : name;
                  await onAdd(description, priority, { ...options, project });
                  setAdding(false);
                }}
                labels={labels}
                projects={projects}
                defaultProject={name}
                lockProject
              />
              <button
                type="button"
                onClick={() => setAdding(false)}
                className="text-xs text-on-surface-variant hover:text-on-surface mt-1"
              >
                Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setAdding(true)}
              aria-label={`Add task to ${name}`}
              className="flex items-center gap-3 py-2 px-3 w-full rounded-lg hover:bg-surface-container-high/40 transition-colors text-left group/add cursor-pointer"
            >
              <span
                className="w-5 h-5 rounded-full border border-dashed flex items-center justify-center shrink-0"
                style={{ borderColor: accent, color: accent }}
                aria-hidden
              >
                <span className="material-symbols-outlined text-xs">add</span>
              </span>
              <span
                className="text-sm font-medium"
                style={{ color: accent }}
              >
                Add to {name}
              </span>
            </button>
          )}
        </div>
      )}
    </section>
  );
}
