"use client";

interface ToolsToggleProps {
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  disabled?: boolean;
}

export function ToolsToggle({ enabled, onToggle, disabled }: ToolsToggleProps) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-on-surface-variant cursor-pointer select-none">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(e) => onToggle(e.target.checked)}
        disabled={disabled}
        className="h-3.5 w-3.5 rounded accent-primary"
      />
      Tools
    </label>
  );
}
