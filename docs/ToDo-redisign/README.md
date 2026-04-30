# Handoff: ToDo — Focus + Groups

## Overview
A mobile task manager screen combining two UX patterns:
1. **Focus Card** — surfaces the single most important task with Done/Skip actions
2. **Project Groups** — collapsible sections grouping tasks by project, each with a mini progress bar

The user can tap any queued task to promote it to the Focus Card. Tapping a group header collapses/expands it.

## About the Design Files
The files in this bundle are **design references built in HTML/React** — interactive prototypes showing intended look, layout, and behavior. The task is to **recreate these designs in your existing codebase** (React Native, Swift, Kotlin, etc.) using its established patterns and component library. Do not ship the HTML directly.

## Fidelity
**High-fidelity.** Colors, typography, spacing, border radii, and interactions are all final and should be matched precisely.

---

## Screens / Views

### Main Screen — Task List

**Layout:** Vertical flex column, full mobile viewport (390×720 reference). Three zones stacked top→bottom:
1. Status bar (44px, decorative)
2. Header strip (tabs + title)
3. Scrollable body (flex:1, overflow-y scroll)

---

### Zone 1 — Header

**Title row** (padding: 4px 20px, margin-bottom 14px):
- Left: icon + "TASKS" label (15px, weight 700, letter-spacing .08em) + count badge
  - Badge: background `#e07060`, white text, 11px bold, border-radius 10px, padding 1px 7px
- Right: overall progress bar (48×3px, `#4caf7d` fill, `#2c2c2e` track, border-radius 2px) + "done/total" label (11px, `#5a5a5c`) + add button (32×32px, border-radius 10px, `#2c2c2e` bg)

**Tab bar** (border-bottom `#333335`):
- Tabs: "Today", "This Week" (with count chip), "All" (with count chip)
- Active tab: color `#f0efed`, font-weight 600, 2px solid bottom border
- Inactive tab: color `#9a9a9c`, font-weight 400
- Count chip (active): bg `#2c2c2e`, text `#f0efed`
- Count chip (inactive): bg `#333335`, text `#9a9a9c`
- Tab padding: 7px 14px, font-size 13px

---

### Zone 2 — Focus Card

Container: margin 14px 16px 0, background `#242426`, border-radius 16px, border `1px solid #333335`

**Accent strip:** 3px tall gradient `linear-gradient(90deg, #e07060, transparent)`

**Card content** (padding 14px 16px):
- Label: "FOCUS NOW", 10px, letter-spacing .1em, color `#5a5a5c`
- Checkbox (24px): see Checkbox component below
- Task text: 15px, weight 600, line-height 1.4, color `#f0efed`
- Below text: project tag chip + date label
  - Tag chip: background = project's bg color (translucent), text = project color, 11px bold, border-radius 6px, padding 2px 8px
- **Done button:** flex:1, background `#4caf7d`, border-radius 10px, 9px padding, white text, 13px bold
- **Skip button:** flex:1, background `#2c2c2e`, border-radius 10px, 9px padding, color `#9a9a9c`, 13px weight 500
- Buttons in a row with 8px gap, margin-top 12px

**Behavior:**
- Done → marks task complete, advances focus to next remaining task
- Skip → cycles focus to next remaining task without completing
- Checking the checkbox inside the card also marks done

---

### Zone 3 — Project Groups (scrollable)

margin-top 20px, list of project sections

**Group Header** (padding 9px 20px, tap to collapse/expand):
- 8×8px colored dot (border-radius 2px)
- Project name: 11px bold, letter-spacing .09em, project color
- Mini progress bar: 36×2.5px, project color fill, `#333335` track
- "done/total" count: 11px, `#5a5a5c`
- Chevron: rotates 0° (expanded) / -90° (collapsed), transition .2s

**Task Row** (padding 9px 20px 9px 38px — left indent 38px):
- Checkbox (20px)
- Task text: 13.5px, line-height 1.35
  - Default: color `#9a9a9c`, weight 400
  - Focused task: color `#f0efed`, weight 500, row background = project bg color
  - Completed: color `#5a5a5c`, opacity .4, strikethrough
- Focused indicator: 6×6px dot, project color, right side
- Tap non-focused row → promotes it to Focus Card

**Add row** (padding 8px 20px 8px 38px, opacity .45):
- Dashed circle (20px, 1px dashed border, project color) with + icon
- "Add to {Project}" label, 12px, project color

**Divider:** 1px `#333335`, margin 4px 20px, opacity .6

---

## Checkbox Component

```
size: 20–24px, border-radius: 50%
unchecked: border 1.5px solid #333335, transparent bg
checked:   border 1.5px solid #4caf7d, bg #4caf7d, white checkmark SVG inside
transition: all .18s
```

---

## Project Color Tokens

| Project  | Color     | Background (translucent)       |
|----------|-----------|-------------------------------|
| OB       | `#e07060` | `rgba(224,112,96,0.12)`        |
| Personal | `#7b8fc7` | `rgba(123,143,199,0.12)`       |

---

## Design Tokens

### Colors
```
bg:        #1c1c1e   — main background
surface:   #242426   — card / elevated surface
surface2:  #2c2c2e   — input / button backgrounds
border:    #333335   — dividers and borders
text:      #f0efed   — primary text
textMid:   #9a9a9c   — secondary text
textDim:   #5a5a5c   — tertiary / labels
salmon:    #e07060   — OB project + primary accent
indigo:    #7b8fc7   — Personal project accent
green:     #4caf7d   — success / done state
```

### Typography
```
Font: Helvetica Neue, Helvetica, Arial, sans-serif

Header label:  15px / 700 / #f0efed / ls .08em
Section label: 11px / 700 / project color / ls .09em
Focus title:   15px / 600 / #f0efed / lh 1.4
Task text:     13.5px / 400–500 / varies / lh 1.35
Caption:       11px / 400 / #5a5a5c / ls .1em
Badge:         11px / 700
Tab active:    13px / 600
Tab inactive:  13px / 400
Button:        13px / 600 (primary), 500 (secondary)
```

### Spacing
```
Outer horizontal padding:   20px
Task left indent:           38px
Group header padding:       9px 20px
Focus card margin:          14px 16px 0
Focus card inner padding:   14px 16px
Row vertical padding:       9px
Gap between action buttons: 8px
Gap checkbox–text:          12px
```

### Border Radii
```
Phone shell:    44px
Focus card:     16px
Tag chip:        6px
Action buttons: 10px
Add button:     10px
Checkbox:       50%
Progress bar:    2px
```

---

## Interactions & Behavior

| Trigger | Action |
|---|---|
| Tap focus Done button | Mark focusTask done, advance focus to next remaining |
| Tap focus Skip button | Cycle focus to next remaining (no completion) |
| Check focus checkbox | Same as Done button |
| Check task row checkbox | Toggle done state for that task; if it was focused, advance |
| Tap unfocused task row | Set as new focus task |
| Tap group header | Collapse / expand section (animated chevron) |
| Tap Add row | Open new task sheet pre-filled with project |

Transitions:
- Checkbox: all .18s
- Progress bar fill: width .3–.4s ease
- Group chevron: transform rotate .2s
- Task opacity (done state): .2s
- Focus row background: .2s

---

## State
```
activeTab:  "today" | "week" | "all"
doneIds:    Set<taskId>        — completed task IDs
collapsed:  Set<projectKey>   — collapsed project keys
focusId:    taskId             — currently focused task
```

Derived:
```
remaining = tasks.filter(t => !doneIds.has(t.id))
focusTask = remaining.find(t => t.id === focusId) || remaining[0]
```

---

## Files

| File | Description |
|---|---|
| `ToDo Combined.html` | Full interactive prototype — open in any browser |

---

## Notes for Developer
- The prototype is single-screen; tab switching doesn't filter yet — wire it to real data
- Projects are currently hardcoded (OB, Personal); make them dynamic from user's project list
- Add swipe-to-complete on task rows (swipe right = done, swipe left = delete/snooze)
- The Focus Card could persist between sessions via local storage / user preference
