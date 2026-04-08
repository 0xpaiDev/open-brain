"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const tabs = [
  { href: "/dashboard", icon: "today", label: "Today" },
  { href: "/memory", icon: "database", label: "Memory" },
  { href: "/chat", icon: "chat", label: "Chat" },
  { href: "/diary", icon: "auto_stories", label: "Diary" },
  { href: "/analytics", icon: "analytics", label: "Analytics" },
];

export function BottomTabs() {
  const pathname = usePathname();

  return (
    <nav className="flex md:hidden fixed bottom-0 left-0 right-0 z-50 bg-surface-container-lowest border-t border-outline-variant/15 px-2 pt-1 pb-[calc(0.25rem+env(safe-area-inset-bottom,0px))]">
      {tabs.map((tab) => {
        const isActive = pathname === tab.href;
        return (
          <Link
            key={tab.href}
            href={tab.href}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-label transition-colors ${
              isActive ? "text-primary" : "text-outline"
            }`}
          >
            <span
              className="material-symbols-outlined text-xl"
              style={
                isActive
                  ? { fontVariationSettings: '"FILL" 1' }
                  : undefined
              }
            >
              {tab.icon}
            </span>
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
