"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { validateApiKey } from "@/lib/api";

interface AuthGateDialogProps {
  onLogin: (key: string) => void;
}

export function AuthGateDialog({ onLogin }: AuthGateDialogProps) {
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [validating, setValidating] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;

    setError("");
    setValidating(true);

    try {
      const valid = await validateApiKey(key.trim());
      if (valid) {
        onLogin(key.trim());
      } else {
        setError("Invalid API key. Check your key and try again.");
      }
    } catch {
      setError("Could not reach the API. Is the server running?");
    } finally {
      setValidating(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-background">
      <Dialog open modal>
        <DialogContent showCloseButton={false} className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="font-headline text-xl text-primary">
              <span className="material-symbols-outlined mr-2 align-middle text-2xl">
                neurology
              </span>
              Open Brain
            </DialogTitle>
            <DialogDescription>
              Enter your API key to connect to your personal memory system.
            </DialogDescription>
          </DialogHeader>

          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label htmlFor="api-key-input" className="sr-only">API Key</label>
            <Input
              id="api-key-input"
              type="password"
              placeholder="API Key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              autoFocus
              className="bg-surface-container border-outline-variant"
            />

            {error && (
              <p className="text-sm text-error" role="alert">{error}</p>
            )}

            <Button
              type="submit"
              disabled={validating || !key.trim()}
              className="w-full bg-gradient-to-r from-primary to-primary-container text-on-primary font-bold hover:shadow-[0_0_20px_rgba(173,198,255,0.3)] transition-all active:scale-95"
            >
              {validating ? (
                <span className="flex items-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-on-primary border-t-transparent" />
                  Validating...
                </span>
              ) : (
                "Connect"
              )}
            </Button>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
