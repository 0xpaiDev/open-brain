# iOS Voice Shortcut

Capture voice notes, create todos, and close todos from anywhere on your iPhone using Back Tap + Siri Dictation.

Two endpoints are supported:

| Endpoint | Use case | Status |
|---|---|---|
| `POST /v1/voice/command` | **Recommended.** One shortcut that routes dictation into create-todo / complete-todo / save-memory based on explicit keyword triggers. | Current |
| `POST /v1/memory` | Legacy memory-only capture. Still works byte-identical for backward compatibility. | Legacy |

New shortcuts should target `/v1/voice/command`. The legacy section at the bottom remains for reference.

## Prerequisites

- iPhone with iOS 16+ (Back Tap requires iPhone 8 or later)
- Open Brain API key
- Open Brain API accessible from the internet (e.g. `https://0xpai.com/v1/voice/command`)

## How the intent router works

Dictation is classified deterministically by keyword — **no LLM is involved in routing**, only in field extraction after the intent is locked in. Classification rules (first match wins):

1. **Create todo** — if dictation *starts with* any of:
   - `todo …`
   - `task …`
   - `remind me to …`
   - `create a todo …` / `create todo …` / `new todo …`
   - `add a todo …` / `add todo …`

   Example: "remind me to buy milk tomorrow" → create. Haiku then extracts `description="buy milk"` and `due_date=<tomorrow>`.

   > ⚠️ The create prefix wins even if a completion verb like "close" or "done" appears later in the sentence. "**Remind me to close** the fridge" creates a todo called "close the fridge" — it does not complete anything.

2. **Complete todo** — if dictation contains a completion verb (`close`, `complete`, `done`, `finish`, `mark done`, `mark as done`) **and** a todo-reference token (`todo`, `task`, `the`). Haiku extracts the target phrase, which is fuzzy-matched (`difflib`, confidence ≥ 0.70) against your open todos.

   Example: "mark buy milk at the corner store as done" → finds the matching open todo and closes it, recording the original dictation + match score in the `todo_history.reason` column for audit.

   Sub-threshold or tied matches return `action="ambiguous"` with **zero side effects** — nothing is written.

3. **Save memory** — everything else. The dictation is stored verbatim as a raw memory (`source="voice"`) and enqueued for refinement, exactly as the legacy `/v1/memory` path.

## Response shape

```json
{
  "action": "created" | "completed" | "memory" | "ambiguous",
  "entity_id": "<uuid>" | null,
  "title": "the matched/created todo description" | null,
  "confidence": 0.0 - 1.0,
  "message": "Added todo: \"buy milk\""
}
```

Status codes:
- `200` — action in `{created, completed, ambiguous}`
- `202` — action `memory` (matches legacy `/v1/memory` contract)

The `message` field is **pre-baked server-side** so your Shortcut's notification action can display it verbatim without templating.

## Create the Shortcut

1. Open the **Shortcuts** app
2. Tap **+** to create a new shortcut
3. Name it **"Open Brain Voice"**

### Add actions in order

**Action 1 — Dictate Text**
- Search for "Dictate Text" and add it
- Set **Stop Listening** to "After Pause"
- Set **Language** to your preferred language

**Action 2 — If (guard against empty dictation)**
- Add an **If** action
- Condition: "Dictated Text" **has any value**
- Everything below goes inside the "If" block (before "Otherwise")

**Action 3 — Get Contents of URL**
- Search for "Get Contents of URL" and add it
- **URL:** `https://0xpai.com/v1/voice/command`
- Tap **Show More**, then:
  - **Method:** POST
  - **Headers:**
    - `X-API-Key`: `your-api-key-here`
    - `Content-Type`: `application/json`
  - **Request Body:** JSON
    - `text`: *Dictated Text* (select the variable from Action 1)
    - `source`: `voice`
    - `metadata`: Dictionary with key `transcription_method` = `siri_dictation`

**Action 4 — Get Dictionary Value**
- Add "Get Dictionary Value"
- Get: **Value** for key `message` in **Contents of URL** (the previous action's output)

**Action 5 — Show Notification**
- Add "Show Notification"
- Title: "Open Brain"
- Body: *Dictionary Value* (from Action 4) — this is the server-baked `message` so it reads "Added todo: …", "Completed: …", "Saved to memory.", or "No confident match for …".

**Action 6 — Otherwise (empty dictation)**
- Inside the "Otherwise" block, add "Show Notification"
- Title: "No speech detected"

Close the If block.

## Set Up Back Tap

1. Go to **Settings > Accessibility > Touch > Back Tap**
2. Choose **Double Tap** or **Triple Tap**
3. Select **"Open Brain Voice"** from the shortcut list

## Usage

Triple-tap (or double-tap) the back of your iPhone. Siri dictation starts immediately. Speak your thought, pause. The notification tells you exactly what happened:

- *"Added todo: buy milk"* — a new todo was created
- *"Completed: buy milk at the corner store"* — an open todo was closed
- *"Saved to memory."* — the dictation was filed as a raw memory
- *"No confident match for \"close the nonexistent thing\". Nothing was changed."* — the classifier thought you meant to complete a todo but no open todo matched confidently. Nothing was written.

If a completion ever closes the wrong todo, the `todo_history.reason` column on that row contains your original dictation plus the fuzzy-match score, so you can find and reopen it from the dashboard.

## Latency and cost

- End-to-end target: **under 2 seconds** (Siri attention span)
- Haiku field extraction is bounded by `VOICE_COMMAND_LLM_TIMEOUT_SECONDS` (default `1.5s`). On create-path timeout the dictation is stored verbatim as the todo description — the note is never lost. On complete-path timeout the response is `ambiguous` with no mutation — never a silent memory fallthrough.
- Model is pinned to Haiku via `ANTHROPIC_MODEL` — cost per call is negligible.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Could not connect" | Check that your API URL is correct and reachable from your phone's network |
| 401 Unauthorized | Verify the X-API-Key value matches your `API_KEY` env var |
| Dictation always becomes memory | You're missing the keyword trigger. Start with "remind me to …" for todos, or include "close …todo" / "mark done the …task" for completions |
| A completion returns `ambiguous` unexpectedly | Either the fuzzy score was below 0.70, or two open todos tied within 0.05. Be more specific in the dictation, or close it from the dashboard |
| Notification shows nothing | Make sure Action 4 (Get Dictionary Value) reads the `message` key from the previous action's output |
| Back Tap not working | Ensure Accessibility > Touch > Back Tap is configured; works best without a thick case |
| Dictation in wrong language | Change the language setting in the Dictate Text action |

## Legacy: memory-only shortcut (`/v1/memory`)

The original memory-only endpoint still works and is preserved byte-identical for any existing shortcuts. Use it only if you explicitly want every dictation to land as a raw memory with no todo routing.

- **URL:** `https://0xpai.com/v1/memory`
- **Method:** POST
- **Headers:** `X-API-Key`, `Content-Type: application/json`
- **Body:** `{ "text": <Dictated Text>, "source": "voice" }`
- **Response:** `202` with `{ "raw_id": "...", "status": "queued" | "duplicate" }`

For new setups, prefer `/v1/voice/command` — it's a strict superset.
