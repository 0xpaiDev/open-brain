#!/usr/bin/env python3
"""
Import Gemini MyActivity.json export into Open Brain.

Usage:
    python scripts/import_gemini.py history-memory/Gemini/MyActivity.json
    python scripts/import_gemini.py history-memory/Gemini/MyActivity.json --dry-run
    python scripts/import_gemini.py history-memory/Gemini/MyActivity.json --limit 100
"""

import argparse
import json
import re
import sys
import time

import requests

API_URL = "http://34.118.55.10:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"
MIN_LENGTH = 300
MAX_CHUNK = 8000


def strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def chunk_text(text: str, max_chars: int = MAX_CHUNK) -> list[str]:
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
    if dry_run:
        preview = text[:120].replace("\n", " ")
        print(f"  [dry-run] would POST {len(text)} chars: {preview}...")
        return 0
    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={"text": text, "source": "gemini_export", "metadata": metadata},
        timeout=15,
    )
    return response.status_code


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Gemini MyActivity.json into Open Brain")
    parser.add_argument("export_file", help="Path to MyActivity.json")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.5)
    args = parser.parse_args()

    with open(args.export_file) as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("ERROR: Expected a JSON list")
        sys.exit(1)

    # Filter to Gemini Apps only
    items = [d for d in data if d.get("header") == "Gemini Apps"]
    print(f"Found {len(items)} Gemini activity items (from {len(data)} total)")

    items = items[args.offset:]
    if args.limit:
        items = items[:args.limit]

    print(f"Processing {len(items)} items (offset={args.offset}, limit={args.limit})")
    if args.dry_run:
        print("DRY RUN — nothing will be posted\n")

    skipped = posted = errors = 0

    for i, item in enumerate(items, start=1):
        title = item.get("title", "")
        created_at = item.get("time", "")

        # Extract prompt: title starts with "Prompted "
        prompt = title.removeprefix("Prompted ").strip()

        # Extract Gemini response from HTML
        html_items = item.get("safeHtmlItem", [])
        response_html = html_items[0].get("html", "") if html_items else ""
        response_text = strip_html(response_html)

        # Build combined text
        parts = []
        if prompt:
            parts.append(f"YOU: {prompt}")
        if response_text:
            parts.append(f"GEMINI: {response_text}")
        text = "\n\n".join(parts)

        if len(text) < MIN_LENGTH:
            print(f"[{i:>4}/{len(items)}] SKIP (too short, {len(text)} chars): {prompt[:60]}")
            skipped += 1
            continue

        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"[{i:>4}/{len(items)}] POST{chunk_label}: {prompt[:60]}")

        for chunk_index, chunk in enumerate(chunks):
            metadata = {
                "title": prompt[:200],
                "created_at": created_at,
                "chunk_index": chunk_index,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, args.dry_run)

            if not args.dry_run:
                if status in (200, 202):
                    if status == 200:
                        print(f"       duplicate")
                    posted += 1
                else:
                    print(f"       ERROR status={status}")
                    errors += 1

                if chunk_index < len(chunks) - 1:
                    time.sleep(args.delay)

        if not args.dry_run:
            time.sleep(args.delay)

    print(f"\nDone. posted={posted} skipped={skipped} errors={errors}")


if __name__ == "__main__":
    main()
