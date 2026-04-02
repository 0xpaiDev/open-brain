"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/auth-provider";

export function TopNav() {
  const { logout } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [query, setQuery] = useState(searchParams.get("q") ?? "");

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed) {
      const params = new URLSearchParams(searchParams.toString());
      params.set("q", trimmed);
      params.delete("filter");
      router.push(`/memory?${params.toString()}`);
    } else {
      clearSearch();
    }
  }

  function clearSearch() {
    setQuery("");
    const params = new URLSearchParams(searchParams.toString());
    params.delete("q");
    const qs = params.toString();
    router.push(qs ? `/memory?${qs}` : "/memory");
  }

  return (
    <header className="fixed top-0 z-50 w-full flex justify-between items-center px-6 py-3 bg-background/80 backdrop-blur-xl shadow-2xl shadow-black/20 font-headline tracking-tight">
      <div className="flex items-center gap-4">
        <span className="text-xl font-bold text-primary">Open Brain</span>
      </div>

      <div className="flex items-center gap-6">
        {/* Desktop search bar */}
        <form
          onSubmit={handleSearch}
          className="hidden md:flex items-center bg-surface-container-low px-4 py-1.5 rounded-full border border-outline-variant/15"
        >
          <span className="material-symbols-outlined text-outline text-sm mr-2">
            search
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="bg-transparent border-none focus:ring-0 focus:outline-none text-sm text-on-surface-variant w-64 placeholder:text-outline/50 font-body"
            placeholder="Search memories..."
            type="text"
          />
          {query && (
            <button
              type="button"
              onClick={clearSearch}
              className="text-outline hover:text-on-surface transition-colors ml-1"
            >
              <span className="material-symbols-outlined text-sm">close</span>
            </button>
          )}
        </form>

        <div className="flex items-center gap-4">
          {/* Mobile search icon */}
          <button
            onClick={() => router.push("/memory")}
            className="md:hidden text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95"
          >
            <span className="material-symbols-outlined">search</span>
          </button>
          <button className="text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button
            onClick={logout}
            className="text-outline hover:bg-surface-container-high hover:text-on-surface transition-colors p-2 rounded-lg active:scale-95"
            title="Sign out"
          >
            <span className="material-symbols-outlined">logout</span>
          </button>
          <div className="w-8 h-8 rounded-full bg-primary-container flex items-center justify-center text-on-primary-container font-bold text-xs">
            S
          </div>
        </div>
      </div>
    </header>
  );
}
