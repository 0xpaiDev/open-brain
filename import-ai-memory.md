# Import AI Conversation History into Open Brain

## Goal

Export conversation history from Claude, ChatGPT, and Gemini and import into Open Brain
so all past knowledge, decisions, and insights are searchable in one place.

---

## Step 1 — Export from each platform

### Claude (Anthropic)
1. Go to `claude.ai` → Settings → **Export data**
2. Download the JSON export
3. File contains all conversations with timestamps

### ChatGPT (OpenAI)
1. Go to `chat.openai.com` → Settings → **Data Controls** → **Export data**
2. You receive an email with a ZIP file
3. Inside: `conversations.json` with full history

### Gemini (Google)
1. Go to `takeout.google.com`
2. Select only **Gemini Apps Activity**
3. Download and extract — conversation history is in HTML or JSON format

---

## Step 2 — Filter before importing

These exports can contain thousands of conversations. Not all are worth importing.

**Keep:**
- Conversations about projects, decisions, architecture, planning
- Technical knowledge you want to recall later
- Personal reflections, goals, ideas
- Anything with named entities (people, projects, tools, places)

**Skip:**
- One-liner help requests ("fix this syntax error")
- Generic coding assistance with no personal context
- Repeated/duplicate topics
- Conversations shorter than ~5 messages

---

## Step 3 — Write import scripts

### Claude export parser

```python
import json
import time
import requests

API_URL = "http://34.118.15.81:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"

with open("claude_export.json") as f:
    data = json.load(f)

for conversation in data["conversations"]:
    # Concatenate all messages into one text block
    text = "\n\n".join(
        f"{msg['role'].upper()}: {msg['content']}"
        for msg in conversation["messages"]
        if msg.get("content")
    )

    if len(text) < 200:  # skip trivial conversations
        continue

    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={
            "raw_text": text[:8000],  # chunk if needed
            "source": "claude_export",
            "metadata": {
                "created_at": conversation.get("created_at"),
                "title": conversation.get("title", ""),
            }
        }
    )
    print(f"Stored: {conversation.get('title', 'untitled')} — {response.status_code}")
    time.sleep(0.5)  # avoid hammering the worker queue
```

### ChatGPT export parser

```python
import json
import time
import requests

API_URL = "http://34.118.15.81:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"

with open("conversations.json") as f:
    data = json.load(f)

for conversation in data:
    messages = conversation.get("mapping", {}).values()
    text_parts = []

    for node in messages:
        msg = node.get("message")
        if not msg:
            continue
        role = msg.get("author", {}).get("role", "")
        content = msg.get("content", {}).get("parts", [])
        if role in ("user", "assistant") and content:
            text_parts.append(f"{role.upper()}: {content[0]}")

    text = "\n\n".join(text_parts)

    if len(text) < 200:
        continue

    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={
            "raw_text": text[:8000],
            "source": "chatgpt_export",
            "metadata": {
                "title": conversation.get("title", ""),
                "created_at": str(conversation.get("create_time", "")),
            }
        }
    )
    print(f"Stored: {conversation.get('title', 'untitled')} — {response.status_code}")
    time.sleep(0.5)
```

### Gemini export parser

```python
# Gemini Takeout exports as HTML files in a folder
# Run: python import_gemini.py path/to/takeout/Gemini/

import os
import sys
import time
import requests
from bs4 import BeautifulSoup

API_URL = "http://34.118.15.81:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"

folder = sys.argv[1]

for filename in os.listdir(folder):
    if not filename.endswith(".html"):
        continue

    with open(os.path.join(folder, filename)) as f:
        soup = BeautifulSoup(f.read(), "html.parser")

    text = soup.get_text(separator="\n").strip()

    if len(text) < 200:
        continue

    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={
            "raw_text": text[:8000],
            "source": "gemini_export",
        }
    )
    print(f"Stored: {filename} — {response.status_code}")
    time.sleep(0.5)
```

---

## Step 4 — Run overnight

Large exports (1000+ conversations) take time because:
- Each memory is queued and processed by the worker
- Worker calls Claude for extraction + Voyage AI for embeddings
- `time.sleep(0.5)` = ~2 conversations/second = ~500 conversations in 4 minutes

For very large exports, run in batches:
```bash
# Process first 500
python import_claude.py --limit 500

# Process next 500
python import_claude.py --offset 500 --limit 500
```

---

## Step 5 — Verify import

After running, search for something you know was in your history:

```bash
curl -H "X-API-Key: openbrain-demo-secret-key-2026" \
  "http://34.118.15.81:8000/v1/search?q=YOUR+TOPIC"
```

---

## Things to watch out for

**Chunking** — conversations longer than ~8000 chars should be split into chunks.
Each chunk POSTed separately so the worker can extract properly. Claude's context
window handles long text but extraction quality drops on very long inputs.

**Duplicates** — if you run the import twice, `content_hash` deduplication prevents
duplicate raw_memory rows. Safe to re-run.

**Rate limits** — the API rate limit is 50 requests/minute for `/v1/memory`.
Keep `time.sleep(0.5)` or higher to stay under this.

**Sensitive content** — review exports before importing. AI conversations may contain
passwords, keys, or personal info you don't want in the DB.

**Gemini format** — Takeout format changes occasionally. If the HTML parser doesn't
work, inspect the raw file structure and adjust the parser.

---

## Dependencies for import scripts

```bash
pip install requests beautifulsoup4
```

---

## Files to create when ready

| File | Purpose |
|---|---|
| `scripts/import_claude.py` | Parse and import Claude export |
| `scripts/import_chatgpt.py` | Parse and import ChatGPT export |
| `scripts/import_gemini.py` | Parse and import Gemini Takeout |
