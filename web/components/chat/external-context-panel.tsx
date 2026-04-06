"use client";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";

interface ExternalContextPanelProps {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

const MAX_CHARS = 20_000;

export function ExternalContextPanel({
  value,
  onChange,
  disabled,
}: ExternalContextPanelProps) {
  return (
    <Collapsible>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs text-outline hover:text-on-surface-variant transition-colors py-1.5 px-1 cursor-pointer w-full">
        <span className="material-symbols-outlined text-sm">attach_file</span>
        External context
        {value && (
          <span className="ml-1 text-primary">
            ({value.length.toLocaleString()} chars)
          </span>
        )}
        <span className="material-symbols-outlined text-sm ml-auto">
          expand_more
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="pt-1 pb-2 space-y-2">
          <Textarea
            value={value}
            onChange={(e) => onChange(e.target.value.slice(0, MAX_CHARS))}
            placeholder="Paste meeting notes, documents, or other context here…"
            className="min-h-20 max-h-40 text-xs bg-surface-container-lowest border-outline-variant/15 text-on-surface resize-y"
            disabled={disabled}
          />
          <div className="flex items-center justify-between text-xs text-outline px-1">
            <span>
              {value.length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
            </span>
            {value && (
              <Button
                variant="ghost"
                size="xs"
                onClick={() => onChange("")}
                disabled={disabled}
              >
                <span className="material-symbols-outlined text-xs">close</span>
                Clear
              </Button>
            )}
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
