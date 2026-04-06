"use client";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AVAILABLE_MODELS } from "@/hooks/use-chat";

interface ModelSelectorProps {
  model: string;
  onModelChange: (model: string) => void;
  disabled?: boolean;
}

export function ModelSelector({
  model,
  onModelChange,
  disabled,
}: ModelSelectorProps) {
  return (
    <Select value={model} onValueChange={(v) => { if (v) onModelChange(v); }} disabled={disabled}>
      <SelectTrigger size="sm" className="text-on-surface-variant text-xs">
        <span className="material-symbols-outlined text-sm mr-1">smart_toy</span>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {AVAILABLE_MODELS.map((m) => (
          <SelectItem key={m.value} value={m.value}>
            {m.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
