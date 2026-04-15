"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { useProjectLabels } from "@/hooks/use-project-labels";

const navItems = [
  { href: "/dashboard", icon: "today", label: "Today" },
  { href: "/memory", icon: "database", label: "Memory" },
  { href: "/chat", icon: "chat", label: "Chat" },
  { href: "/diary", icon: "auto_stories", label: "Diary" },
  { href: "/analytics", icon: "analytics", label: "Analytics" },
  { href: "/learning", icon: "school", label: "Learning" },
  { href: "/logs", icon: "terminal", label: "Logs" },
];

const memoryFilters = [
  { label: "All Memories", filter: "", icon: "database" },
  { label: "Decisions", filter: "decision", icon: "gavel" },
  { label: "Tasks", filter: "task", icon: "task_alt" },
  { label: "Todos", filter: "todo", icon: "checklist" },
  { label: "Pulse", filter: "daily_pulse", icon: "vitals" },
  { label: "Context", filter: "context", icon: "info" },
];

export function Sidebar() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isMemoryRoute = pathname === "/memory";
  const activeFilter = searchParams.get("filter") ?? "";
  const activeProject = searchParams.get("project") ?? "";
  const { labels: projectLabels } = useProjectLabels();

  return (
    <aside className="hidden md:flex flex-col h-screen w-64 fixed left-0 top-0 bg-surface-container-lowest border-r border-outline-variant/15 p-4 gap-y-4 pt-20 z-40">
      <div className="px-2 mb-4">
        <h2 className="text-primary font-headline font-bold text-lg">
          Library
        </h2>
      </div>

      <nav className="flex flex-col gap-1">
        {navItems.map((item) => {
          const isActive = pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg font-body text-sm transition-all ${
                isActive
                  ? "bg-surface-container-low text-primary font-semibold"
                  : "text-outline hover:text-on-surface hover:bg-surface-container-low"
              }`}
            >
              <span
                className="material-symbols-outlined"
                style={
                  isActive
                    ? { fontVariationSettings: '"FILL" 1' }
                    : undefined
                }
              >
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      {/* Memory filters — shown only on /memory route */}
      {isMemoryRoute && (
        <div className="flex flex-col gap-0.5 mt-1">
          <span className="text-[10px] font-label text-outline uppercase tracking-wider px-3 mb-1">
            Filter
          </span>
          {memoryFilters.map((f) => {
            const isActive = activeFilter === f.filter && !activeProject;
            const href = f.filter ? `/memory?filter=${f.filter}` : "/memory";
            return (
              <Link
                key={f.filter}
                href={href}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg font-body text-xs transition-all ${
                  isActive
                    ? "bg-surface-container-low text-primary font-semibold"
                    : "text-outline hover:text-on-surface hover:bg-surface-container-low"
                }`}
              >
                <span className="material-symbols-outlined text-sm">
                  {f.icon}
                </span>
                {f.label}
              </Link>
            );
          })}
        </div>
      )}

      {/* Project filters — shown only on /memory route when projects exist */}
      {isMemoryRoute && projectLabels.length > 0 && (
        <div className="flex flex-col gap-0.5 mt-1">
          <span className="text-[10px] font-label text-outline uppercase tracking-wider px-3 mb-1">
            Projects
          </span>
          {projectLabels.map((p) => {
            const isActive = activeProject === p.name;
            const params = new URLSearchParams();
            params.set("project", p.name);
            if (activeFilter) params.set("filter", activeFilter);
            const href = `/memory?${params.toString()}`;
            return (
              <Link
                key={p.id}
                href={isActive ? "/memory" : href}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg font-body text-xs transition-all ${
                  isActive
                    ? "bg-surface-container-low text-primary font-semibold"
                    : "text-outline hover:text-on-surface hover:bg-surface-container-low"
                }`}
              >
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{ backgroundColor: p.color }}
                />
                {p.name}
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-auto flex flex-col gap-1 border-t border-outline-variant/10 pt-4">
        <Link
          href="/memory"
          className="w-full bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold py-3 rounded-xl mb-4 text-sm flex items-center justify-center gap-2 hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95"
        >
          <span className="material-symbols-outlined text-sm">add</span>
          Ingest New Memory
        </Link>
        <Link
          href="/settings"
          className="flex items-center gap-3 px-3 py-2 text-outline hover:text-on-surface hover:bg-surface-container-low rounded-lg font-body text-sm transition-all"
        >
          <span className="material-symbols-outlined">settings</span>
          Settings
        </Link>
      </div>
    </aside>
  );
}
