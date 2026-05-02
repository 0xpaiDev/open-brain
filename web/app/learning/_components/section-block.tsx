"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ItemRow } from "./item-row";
import type { LearningItem, LearningSection } from "@/lib/types";

export function SectionBlock({
  section,
  onAddItem,
  onUpdateItem,
}: {
  section: LearningSection;
  onAddItem?: (title: string) => void;
  onUpdateItem?: (
    id: string,
    patch: Partial<Pick<LearningItem, "title" | "status" | "feedback" | "notes">>,
  ) => void;
}) {
  const [title, setTitle] = useState("");
  return (
    <div className="rounded border border-outline-variant/50 p-3 space-y-2">
      <h3 className="text-sm font-medium text-muted-foreground">{section.name}</h3>
      <ul className="space-y-1">
        {section.items.map((item) => (
          <ItemRow key={item.id} item={item} onUpdate={onUpdateItem} />
        ))}
      </ul>
      {onAddItem && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) {
              onAddItem(title.trim());
              setTitle("");
            }
          }}
        >
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="New item"
          />
          <Button type="submit" variant="outline" size="sm" disabled={!title.trim()}>
            Add
          </Button>
        </form>
      )}
    </div>
  );
}
