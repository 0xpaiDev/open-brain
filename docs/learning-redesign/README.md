# Handoff: Learning Library — Open Brain

## Overview

This is a redesign of the **Learning Library** page inside the Open Brain app. The page lets users manage structured learning topics, each containing sections and checklist items. Active topics feed into the morning todo list.

The redesign focuses on visual hierarchy, progress visibility, and interaction quality — transforming a flat list of checkboxes into a clean, scannable topic management UI.

## About the Design Files

The files in this bundle are **design references created in HTML** — high-fidelity interactive prototypes showing intended look and behavior. They are **not** production code to copy directly.

Your task is to **recreate these designs in the Open Brain codebase** using its existing framework, component library, and patterns. Match the visual output and interactions as precisely as possible, adapting the implementation to whatever stack the project uses (React, Next.js, etc.).

The design uses the existing Open Brain dark theme with a blue accent (`#6f95e2`).

---

## Fidelity

**High-fidelity.** Pixel-perfect mockup with final colors, typography, spacing, animations, and interactions. Recreate the UI precisely using the codebase's existing design system where possible, otherwise implement the values specified here.

---

## Screens / Views

### 1. Full Page Layout

The page is a two-column layout:

| Zone | Width | Notes |
|---|---|---|
| Sidebar | 168px fixed | Left, full height |
| Main content | flex: 1 | Top bar + scrollable content |

**Page background:** `#111113`

---

### 2. Sidebar

- **Width:** 168px
- **Background:** `#0f0f11`
- **Right border:** `1px solid #232328`

**Logo area** (top, padding `20px 18px 28px`):
- 24×24 rounded square (`border-radius: 7px`), background `#e07060` (salmon), contains a concentric-circle icon in white
- "Open Brain" text: `13.5px`, `font-weight: 700`, `letter-spacing: 0.02em`, color `#f0efed`

**Nav section label** ("LIBRARY"):
- `10px`, `font-weight: 600`, `letter-spacing: 0.1em`, `text-transform: uppercase`, color `#505056`
- Padding: `0 8px 8px`

**Nav items** (7 total: Today, Memory, Chat, Diary, Analytics, **Learning** (active), Logs):
- Each: `padding: 8px 10px`, `border-radius: 8px`, `font-size: 13px`, `margin-bottom: 1px`
- Default state: color `#888890`, background `transparent`
- Hover state: background `#222226`
- **Active state** (Learning): background `rgba(224,112,96,0.1)`, color `#e07060`, `font-weight: 600`
- Each has a 16×16 stroke icon to the left (see HTML for SVG paths)

**Bottom area:**
- "Ingest New Memory" button: full width, background `#e07060`, `border-radius: 9px`, `padding: 9px 0`, white text `12.5px font-weight: 600`
- Thin divider `1px solid #232328`
- "Settings" link: `font-size: 12px`, color `#505056`

---

### 3. Top Bar

- **Height:** 52px
- **Bottom border:** `1px solid #232328`
- **Padding:** `0 24px`
- Contents right-aligned:

**Search field:**
- Width: 220px, background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 8px`, padding `6px 12px`
- Placeholder text "Search memories…", `font-size: 12px`, color `#505056`
- 13×13 search icon in `#505056`

**Notification bell icon:**
- 30×30 container, `border-radius: 8px`, background `#1a1a1d`, border `1px solid #2e2e33`
- 14×14 bell SVG, stroke `#888890`

**Avatar:**
- 30×30 circle, background `#e07060`, white letter "S", `font-size: 12px`, `font-weight: 700`

---

### 4. Page Header

Padding: `28px 32px` (this wraps the entire scrollable content area).

**Left side:**
- `<h1>` "Learning Library": `22px`, `font-weight: 700`, `letter-spacing: -0.015em`, color `#f0efed`
- Subtitle: `13px`, color `#505056` — "Topics, sections, and items. Active topics feed into the morning todo list."
- `margin-bottom: 4px` between title and subtitle

**Right side (actions row):**
- Two ghost buttons: "Refresh today" and "Import"
- Style: background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 8px`, `padding: 7px 14px`, `font-size: 12.5px`, `font-weight: 500`, color `#888890`

`margin-bottom: 24px` below header.

---

### 5. Stats Row

`display: flex`, `gap: 10px`, `margin-bottom: 24px`

Three stat cards (Topics, Active, Items done) + one progress card on the right:

**Stat card:**
- Background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 10px`, `padding: 11px 18px`
- Value: `font-size: 20px`, `font-weight: 700`, `line-height: 1`, color `#f0efed` (or `#6f95e2` for the "Active" card)
- Label: `font-size: 11px`, color `#505056`

**Overall progress card** (right-aligned via `flex: 1` spacer):
- Same card style, `min-width: 160px`, `display: flex`, `align-items: center`, `gap: 14px`
- Contains a **38px progress ring** (see Ring component below) + text
- Text: "Overall progress" `13px font-weight: 600` / "X% complete" `11px #505056`

---

### 6. Add Topic + Filter Row

`display: flex`, `gap: 10px`, `margin-bottom: 20px`

**Topic input bar** (flex: 1):
- Container: background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 9px`, overflow hidden
- On focus-within: border transitions to accent color `#6f95e2` (0.15s)
- Text input inside: transparent background, `font-size: 13px`, `padding: 10px 14px`, placeholder "New topic name…"
- "Add topic" button flush right: background `#6f95e2`, no border, `padding: 10px 18px`, white text `13px font-weight: 600`. On hover: opacity 0.85

**Filter pills** (3 buttons: All, Active, Inactive):
- `gap: 4px`
- Default: background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 8px`, `padding: 8px 14px`, `font-size: 12.5px`, color `#888890`
- Active/selected: background `#6f95e2`, border `1px solid #6f95e2`, white text, `font-weight: 600`
- Transition: `all 0.15s`

---

### 7. Topic Card

Each topic is a card:

- Background `#1a1a1d`, border `1px solid #2e2e33`, `border-radius: 14px`, `margin-bottom: 12px`
- On hover: border-color transitions to `#2a2a2e`
- Entrance animation: `fadeIn` — `opacity: 0 → 1`, `translateY(6px → 0)`, duration `0.22s ease`

**Topic header row** (`padding: 14px 18px`, flex, gap 12px, clickable to collapse):

1. **Progress ring** (34px, stroke 2.5px) — see Ring spec below
2. **Name + meta** (flex: 1):
   - Topic name: `14.5px`, `font-weight: 600`, color `#f0efed`, truncate with ellipsis
   - Meta row: `font-size: 11px`, color `#505056` — "N sections · X/Y items" (dot separator is 2×2px circle)
   - "Complete" badge (shown when 100%): background `rgba(76,175,125,0.14)`, color `#4caf7d`, `font-size: 10px`, `font-weight: 600`, `border-radius: 6px`, `padding: 1px 7px`
3. **Active toggle area** (stops click propagation):
   - Label: "Active" (green `#4caf7d`) or "Inactive" (dim `#505056`), `11px font-weight: 500`
   - **Pill toggle:** 36×20px, `border-radius: 10px`. OFF: background `#2a2a2e`, border `#2e2e33`. ON: background `#4caf7d`, border `#4caf7d`. Thumb: 14×14px circle, top 2px, left 2px (off) or 18px (on), white when on / `#505056` when off. Transition: `0.2s`
4. **Chevron** (10×6 SVG): rotates `0°` (expanded) or `-90°` (collapsed), transition `0.2s`

**Progress bar** (shown when expanded + has items):
- `padding: 0 18px`, `margin-bottom: 14px`
- Track: `height: 2px`, background `#222226`, `border-radius: 2px`
- Fill: width = `pct * 100%`, background = accent color (or `#4caf7d` when complete), `border-radius: 2px`, transition `width 0.4s ease`

**Sections area** (`padding: 0 12px 12px`):
- Contains N `SectionBlock` components
- Below sections: "Add section" button (dashed border, full width — see below)

---

### 8. Section Block

- Background `#222226`, border `1px solid #232328`, `border-radius: 10px`, `margin-bottom: 6px` (compact) or `8px`
- overflow hidden

**Section header** (`padding: 8px 12px` compact / `10px 14px` default, flex, gap 10px, clickable):

1. **Left accent bar:** 3px wide × 28px tall, `border-radius: 2px`
   - Gradient: `linear-gradient(180deg, #6f95e2 {pct*100}%, #2e2e33 {pct*100}%)`
   - Animates as items complete (transition `0.4s`)
2. **Section name:** `font-size: 11.5px`, `font-weight: 600`, `letter-spacing: 0.07em`, `text-transform: uppercase`, color `#888890`
3. **Done count badge** (shown when > 0 done): background `rgba(76,175,125,0.14)`, color `#4caf7d`, `font-size: 10px`, `font-weight: 600`, `border-radius: 6px`, `padding: 2px 7px` — format: "N/M"
4. **Chevron** same as topic

**Item rows** (each, flex, `align-items: flex-start`, gap 10px):
- Padding: `5px 14px 5px 29px` (compact) or `7px 14px 7px 29px`
- First item has `border-top: 1px solid #232328`
- On hover: background `#2a2a2e`, transition `0.15s`

  1. **Checkbox** (18×18, `border-radius: 5px`):
     - Unchecked: border `1.5px solid #2e2e33`, transparent bg
     - Checked: border + background = accent color `#6f95e2`, white checkmark SVG
     - On check: `checkPop` animation — scale `1 → 1.22 → 1`, duration `0.18s`
     - Transition: `border-color 0.15s, background 0.15s`
  2. **Item text** (flex: 1):
     - Undone: `#f0efed`, `font-size: 12.5px` (compact) or `13px`, `line-height: 1.45`
     - Done: color `#505056`, `text-decoration: line-through`
     - Transition: `color 0.15s`
     - Double-click → inline edit mode (text input, transparent bg, bottom border `1px solid #2e2e33`)
  3. **Delete X** (16×16, hidden by default):
     - `opacity: 0`, reveals on row hover to `opacity: 1`
     - 10×10 × SVG, stroke `#505056`

**Add item row** (below items, `padding: 4px 14px 6px 29px` compact):
- Default state: ghost "+ Add item" button, `font-size: 12px`, color `#505056`, transitions to accent on hover
- Active state (clicked): shows dashed-border checkbox placeholder + text input inline

**Add section button** (below all sections, inside topic card):
- `width: 100%`, `border: 1px dashed #2e2e33`, `border-radius: 8px`, `padding: 8px 14px`
- Color `#505056`, `font-size: 12px`, centered with + icon
- On hover: border-color and color transition to accent `#6f95e2`

---

### 9. Progress Ring Component

SVG ring, rotated -90° so fill starts from top.

```
outer circle: stroke #2e2e33 (track)
inner circle: stroke = accent color (or #4caf7d when pct >= 1)
strokeDasharray: [circ * pct, circ * (1 - pct)]
strokeLinecap: round
transition: stroke-dasharray 0.4s ease
```

Sizes used:
- Topic card header: 34px, stroke 2.5px
- Overall progress widget: 38px, stroke 3px

---

## Interactions & Behavior

| Interaction | Behavior |
|---|---|
| Click topic header | Collapse/expand the topic (sections hidden) |
| Click section header | Collapse/expand that section (items hidden) |
| Check item checkbox | Marks item done; progress ring/bar update live; `checkPop` animation fires |
| Double-click item text | Enters inline edit mode; Enter or blur to commit; Escape to cancel |
| Toggle active pill | Flips `active` boolean; label and pill color update immediately |
| Click "Add item" | Reveals inline input in that section; Enter to add; Escape or blur to cancel |
| Click "Add section" | Reveals inline input in that topic; Enter to add |
| Filter pills (All / Active / Inactive) | Filters topic list; no animation needed |
| Add topic input | Enter key or "Add topic" button creates new topic with `active: false` |
| Topic card hover | Border-color lightens from `#2e2e33` → `#2a2a2e` |
| "Add section" button hover | Border and text color → accent `#6f95e2` |
| "Add item" button hover | Text color → accent |
| Delete icon | Hidden by default; fades in on row hover; click removes item |

### Animations

| Name | Keyframes | Duration | Easing |
|---|---|---|---|
| `fadeIn` | `opacity: 0, translateY(6px)` → `opacity: 1, translateY(0)` | 220ms | ease |
| `checkPop` | `scale(1)` → `scale(1.22)` → `scale(1)` | 180ms | ease |

---

## State Shape

```ts
type Item = {
  id: number;
  text: string;
  done: boolean;
};

type Section = {
  id: number;
  name: string;
  items: Item[];
};

type Topic = {
  id: number;
  name: string;
  active: boolean;
  sections: Section[];
};
```

**Derived values** (computed, not stored):
- `topicProgress(topic)` → `doneItems / totalItems` (0–1)
- `sectionProgress(section)` → `doneItems / totalItems` (0–1)
- `activeCount` → `topics.filter(t => t.active).length`
- `totalItems / doneItems` → flattened across all topics

---

## Design Tokens

### Colors

| Token | Value | Usage |
|---|---|---|
| `bg` | `#111113` | Page background |
| `sidebar` | `#0f0f11` | Sidebar background |
| `surface` | `#1a1a1d` | Cards, inputs |
| `surface2` | `#222226` | Section blocks, nested surfaces |
| `surface3` | `#2a2a2e` | Hover states |
| `border` | `#2e2e33` | Default borders |
| `borderFaint` | `#232328` | Subtle borders |
| `salmon` | `#e07060` | Brand color, logo, sidebar active, CTA button |
| `salmonDim` | `rgba(224,112,96,0.1)` | Sidebar active bg |
| `accent` | `#6f95e2` | Checkboxes, progress fills, filter active, add topic button |
| `text` | `#f0efed` | Primary text |
| `textMid` | `#888890` | Secondary text, nav items |
| `textDim` | `#505056` | Tertiary text, placeholders, labels |
| `green` | `#4caf7d` | Completed states, active toggle |
| `greenDim` | `rgba(76,175,125,0.14)` | Complete badge background |

### Typography

- **Font stack:** `'Helvetica Neue', Helvetica, Arial, sans-serif`
- Page title: `22px / 700 / letter-spacing -0.015em`
- Topic name: `14.5px / 600`
- Section name: `11.5px / 600 / uppercase / letter-spacing 0.07em`
- Item text: `12.5px` (compact) or `13px` / `line-height 1.45`
- Meta/labels: `11px`
- Badges: `10px / 600`

### Spacing

- Page content padding: `28px 32px`
- Topic card padding: `14px 18px` (header)
- Section header padding: `8px 12px` (compact)
- Item row padding: `5px 14px 5px 29px` (compact)
- Gap between topic cards: `12px`
- Gap between section blocks: `6px` (compact)

### Border Radius

| Element | Radius |
|---|---|
| Topic card | 14px |
| Section block | 10px |
| Stat cards / buttons | 10px / 8px |
| Checkboxes | 5px |
| Pill toggle | 10px |
| Badges | 6px |

### Scrollbar

- Width: 4px
- Track: transparent
- Thumb: `#333`, `border-radius: 4px`

---

## Files in This Package

| File | Description |
|---|---|
| `Learning Library.html` | Full interactive prototype — open in any browser |
| `screenshot-learning-library.png` | Visual reference screenshot |
| `README.md` | This document |

> **Note:** The prototype uses a standalone React + Babel setup for portability. In production, implement using the project's existing component/routing conventions.
