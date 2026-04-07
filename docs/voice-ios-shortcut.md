# iOS Voice Note Shortcut

Capture voice notes into Open Brain from anywhere on your iPhone using Back Tap + Siri Dictation.

## Prerequisites

- iPhone with iOS 16+ (Back Tap requires iPhone 8 or later)
- Open Brain API key
- Open Brain API accessible from the internet (e.g. `https://your-domain.com/v1/memory`)

## Create the Shortcut

1. Open the **Shortcuts** app
2. Tap **+** to create a new shortcut
3. Name it **"Open Brain Voice Note"**

### Add actions in order:

**Action 1 — Dictate Text**
- Search for "Dictate Text" and add it
- Set **Stop Listening** to "After Pause" (auto-stops when you stop talking)
- Set **Language** to your preferred language

**Action 2 — If (guard against empty dictation)**
- Add an **If** action
- Set condition: "Dictated Text" **has any value**
- Everything below goes inside the "If" block (before "Otherwise")

**Action 3 — Get Contents of URL**
- Search for "Get Contents of URL" and add it
- **URL:** `https://your-domain.com/v1/memory`
- Tap **Show More**, then:
  - **Method:** POST
  - **Headers:**
    - `X-API-Key`: `your-api-key-here`
    - `Content-Type`: `application/json`
  - **Request Body:** JSON
    - `text`: *Dictated Text* (select the variable from Action 1)
    - `source`: `voice`
    - `metadata`: Dictionary with key `transcription_method` = `siri_dictation`

**Action 4 — Show Notification**
- Add "Show Notification"
- Title: "Memory saved"
- Body: *Dictated Text*

**Action 5 — Otherwise (empty dictation)**
- Inside the "Otherwise" block, add "Show Notification"
- Title: "No speech detected"

Close the If block.

## Set Up Back Tap

1. Go to **Settings > Accessibility > Touch > Back Tap**
2. Choose **Double Tap** or **Triple Tap**
3. Select **"Open Brain Voice Note"** from the shortcut list

## Usage

Triple-tap (or double-tap) the back of your iPhone. Siri dictation starts immediately. Speak your thought, pause, and the note is automatically sent to Open Brain.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Could not connect" | Check that your API URL is correct and accessible from your phone's network |
| 401 Unauthorized | Verify the X-API-Key value matches your `API_KEY` env var |
| No notification | Make sure notification permissions are enabled for Shortcuts |
| Back Tap not working | Ensure Accessibility > Touch > Back Tap is configured; works best without a thick case |
| Dictation in wrong language | Change the language setting in the Dictate Text action |
