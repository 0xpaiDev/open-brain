# Open Brain — Backlog

Ideas and deferred improvements, not yet scheduled for a phase.

---

## Morning Pulse: Interactive Discord Modal

**Idea**: Replace the free-text DM reply flow with Discord interactive components.

**Current flow**: Bot sends embed → user types free-text reply → Haiku parses it (imprecise, can miss fields)

**Proposed flow**:
1. Morning embed includes a **"Log my morning"** button (`discord.ui.View`)
2. Clicking the button opens a **modal popup** (`discord.ui.Modal`) with structured fields:
   - Sleep quality — select menu or short text (1–5)
   - Energy level — select menu or short text (1–5)
   - Wake time — text input (`HH:MM`)
   - Notes / mood — text area (free text, optional)
3. On submit: bot stores fields directly — no Haiku parsing needed for core fields

**Why**: Structured input = no parsing ambiguity, cleaner data, better UX.

**Scope**: `pulse_cog.py` + `pulse.py` (embed builder). No schema changes needed.
Haiku still useful for summarising the notes field if provided.

---
