#!/usr/bin/env python3
"""
Import Claude conversation export into Open Brain.

Usage:
    python scripts/import_claude.py claude_export.json
    python scripts/import_claude.py claude_export.json --limit 500
    python scripts/import_claude.py claude_export.json --offset 500 --limit 500
    python scripts/import_claude.py claude_export.json --dry-run

Export your data: claude.ai → Settings → Export data
"""

import argparse
import json
import sys
import time

import requests

API_URL = "http://34.118.55.10:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"
MIN_LENGTH = 300  # skip conversations shorter than this (trivial one-liners)
MAX_CHUNK = 8000  # max characters per POST (worker extracts best from focused chunks)


def extract_text(conversation: dict) -> str:
    """Concatenate all human+assistant messages into a single text block."""
    parts = []
    for msg in conversation.get("chat_messages", []):
        role = msg.get("sender", "")
        # content can be a string or a list of content blocks
        content = msg.get("text", "") or ""
        if isinstance(content, list):
            content = " ".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        content = content.strip()
        if role and content:
            label = "YOU" if role == "human" else "CLAUDE"
            parts.append(f"{label}: {content}")
    return "\n\n".join(parts)


def chunk_text(text: str, max_chars: int = MAX_CHUNK) -> list[str]:
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
        json={"text": text, "source": "claude_export", "metadata": metadata},
        timeout=15,
    )
    return response.status_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Claude export into Open Brain")
    parser.add_argument("export_file", help="Path to Claude export JSON file")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N conversations")
    parser.add_argument("--limit", type=int, default=None, help="Process at most N conversations")
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (default 0.5)")
    args = parser.parse_args()

    with open(args.export_file) as f:
        data = json.load(f)

    # Claude export is either a list or {"conversations": [...]}
    if isinstance(data, list):
        conversations = data
    elif isinstance(data, dict) and "conversations" in data:
        conversations = data["conversations"]
    else:
        print("ERROR: Unrecognised Claude export format. Expected a list or {conversations: [...]}")
        sys.exit(1)

    total = len(conversations)
    print(f"Found {total} conversations in export")

    # Apply offset + limit
    conversations = conversations[args.offset :]
    if args.limit:
        conversations = conversations[: args.limit]

    print(f"Processing {len(conversations)} conversations (offset={args.offset}, limit={args.limit})")
    if args.dry_run:
        print("DRY RUN — nothing will be posted\n")

    skipped = 0
    posted = 0
    errors = 0

    for i, conv in enumerate(conversations, start=1):
        title = conv.get("name") or conv.get("title") or "untitled"
        created_at = conv.get("created_at") or conv.get("updated_at") or ""
        uuid = conv.get("uuid") or conv.get("id") or ""

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
                "created_at": created_at,
                "conversation_id": uuid,
                "chunk_index": chunk_index,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, args.dry_run)

            if not args.dry_run:
                if status == 202:
                    posted += 1
                elif status == 200:
                    print(f"       duplicate (content already exists)")
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
