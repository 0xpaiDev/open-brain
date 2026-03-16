#!/usr/bin/env python3
"""
Import OpenAI ChatGPT conversation export into Open Brain.

Usage:
    python scripts/import_openai.py conversations.json
    python scripts/import_openai.py conversations.json --limit 500
    python scripts/import_openai.py conversations.json --offset 500 --limit 500
    python scripts/import_openai.py conversations.json --dry-run

Export your data: ChatGPT → Settings → Data controls → Export data
The export ZIP contains a 'conversations.json' file — use that.

Format: The export is a JSON array of conversation objects. Each conversation
has a 'mapping' dict where nodes contain message role + content parts.
"""

import argparse
import json
import sys
import time

import requests

API_URL = "http://34.118.15.81:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"
MIN_LENGTH = 300
MAX_CHUNK = 8000


def _extract_text_from_parts(parts: list) -> str:
    """Flatten a list of content parts (text or dicts) into a string."""
    texts = []
    for part in parts:
        if isinstance(part, str):
            texts.append(part.strip())
        elif isinstance(part, dict) and part.get("content_type") == "text":
            texts.extend(t for t in part.get("parts", []) if isinstance(t, str))
    return " ".join(t for t in texts if t)


def extract_text(conversation: dict) -> str:
    """Walk the message mapping tree and extract all non-system messages as text.

    OpenAI export format: conversation['mapping'] is a dict of node_id → node.
    Each node has a 'message' field with 'role' and 'content' → 'parts'.
    Nodes are linked by 'parent'/'children' — we read them in creation_time order.
    """
    mapping = conversation.get("mapping", {})
    if not mapping:
        return ""

    # Collect all message nodes with their timestamps
    messages = []
    for node in mapping.values():
        msg = node.get("message")
        if not msg:
            continue
        role = msg.get("author", {}).get("role", "")
        if role == "system":
            continue
        content = msg.get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        text = _extract_text_from_parts(parts).strip()
        if not text:
            continue
        create_time = msg.get("create_time") or 0
        messages.append((create_time, role, text))

    # Sort chronologically
    messages.sort(key=lambda x: x[0])

    parts = []
    for _, role, text in messages:
        label = "YOU" if role == "user" else role.upper()
        parts.append(f"{label}: {text}")

    return "\n\n".join(parts)


def chunk_text(text: str, max_chars: int = MAX_CHUNK) -> list:
    """Split long conversations into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""

    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars:
            if current:
                chunks.append(current.strip())
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para

    if current.strip():
        chunks.append(current.strip())

    return chunks


def post_memory(text: str, metadata: dict, dry_run: bool) -> int:
    """POST a single memory. Returns HTTP status code (0 if dry-run)."""
    if dry_run:
        preview = text[:120].replace("\n", " ")
        print(f"  [dry-run] would POST {len(text)} chars: {preview}...")
        return 0

    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={"text": text, "source": "openai_export", "metadata": metadata},
        timeout=15,
    )
    return response.status_code


def main() -> None:  # noqa: C901
    parser = argparse.ArgumentParser(description="Import OpenAI ChatGPT export into Open Brain")
    parser.add_argument("export_file", help="Path to conversations.json from ChatGPT export ZIP")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N conversations")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N conversations")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between requests (default 0.5)",
    )
    args = parser.parse_args()

    with open(args.export_file) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: Expected a JSON array in conversations.json. Got:", type(data))
        sys.exit(1)

    total = len(data)
    print(f"Found {total} conversations in export")

    conversations = data[args.offset :]
    if args.limit:
        conversations = conversations[: args.limit]

    print(
        f"Processing {len(conversations)} conversations (offset={args.offset}, limit={args.limit})"
    )
    if args.dry_run:
        print("DRY RUN — nothing will be posted\n")

    skipped = 0
    posted = 0
    errors = 0

    for i, conv in enumerate(conversations, start=1):
        title = conv.get("title") or "untitled"
        create_time = conv.get("create_time") or ""
        conv_id = conv.get("id") or conv.get("conversation_id") or ""

        text = extract_text(conv)

        if len(text) < MIN_LENGTH:
            print(f"[{i:>4}/{len(conversations)}] SKIP (too short, {len(text)} chars): {title}")
            skipped += 1
            continue

        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"[{i:>4}/{len(conversations)}] POST{chunk_label}: {title[:60]}")

        for chunk_index, chunk in enumerate(chunks):
            metadata = {
                "title": title,
                "created_at": str(create_time),
                "conversation_id": conv_id,
                "chunk_index": chunk_index,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, args.dry_run)

            if not args.dry_run:
                if status == 202:
                    posted += 1
                elif status == 200:
                    print("       duplicate (content already exists)")
                    posted += 1
                else:
                    print(f"       ERROR status={status}")
                    errors += 1

                if chunk_index < len(chunks) - 1:
                    time.sleep(args.delay)

        if not args.dry_run:
            time.sleep(args.delay)

    print(f"\nDone. posted={posted} skipped={skipped} errors={errors}")
    if errors:
        print("Re-run with --offset to retry from a specific point if needed.")


if __name__ == "__main__":
    main()
