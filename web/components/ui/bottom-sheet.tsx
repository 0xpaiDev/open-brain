"use client";

import * as React from "react";

import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";

/**
 * BottomSheet — thin wrapper over the base-ui Dialog that anchors the popup
 * to the bottom of the viewport and gives it a handle bar. Used for mobile
 * task action sheets; on larger viewports the caller is expected to use the
 * regular centered Dialog instead.
 */
export function BottomSheet({
  open,
  onOpenChange,
  children,
  className,
  ariaLabel,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        aria-label={ariaLabel}
        className={cn(
          // Override the centered positioning from DialogContent.
          // tailwind-merge collapses the conflicting base classes.
          "top-auto bottom-0 left-0 translate-x-0 translate-y-0",
          "w-full max-w-none rounded-t-2xl rounded-b-none",
          "bg-surface-container text-on-surface",
          // Animate up from the bottom.
          "data-open:slide-in-from-bottom data-closed:slide-out-to-bottom",
          "pb-[env(safe-area-inset-bottom)]",
          className,
        )}
      >
        <div
          aria-hidden
          className="mx-auto h-1 w-10 rounded-full bg-on-surface/20"
        />
        {children}
      </DialogContent>
    </Dialog>
  );
}
