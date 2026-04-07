#!/usr/bin/env python3
"""
Import Claude Code local knowledge into Open Brain.

Three sources (all enabled by default):
  memory    — ~/.claude/projects/*/memory/*.md (structured auto-memory files)
  history   — ~/.claude/history.jsonl (user prompts grouped by project)
  claude_md — CLAUDE.md files discovered from history + ~/.claude/projects/

Usage:
    python scripts/import_claude_code.py --dry-run
    python scripts/import_claude_code.py --sources memory
    python scripts/import_claude_code.py --sources memory,history,claude_md
    python scripts/import_claude_code.py
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

API_URL = "http://34.118.55.10:8000/v1/memory"
API_KEY = "openbrain-demo-secret-key-2026"
MAX_CHUNK = 8000
CLAUDE_DIR = Path.home() / ".claude"


# ---------------------------------------------------------------------------
# Shared helpers (mirrors import_claude.py)
# ---------------------------------------------------------------------------


def chunk_text(text: str, max_chars: int = MAX_CHUNK) -> list[str]:
    """Split long text into chunks at paragraph boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
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


def chunk_text_by_heading(text: str, max_chars: int = MAX_CHUNK) -> list[str]:
    """Split text at `## ` headings first, then fall back to paragraph chunking."""
    sections = []
    current: list[str] = []

    for line in text.splitlines(keepends=True):
        if line.startswith("## ") and current:
            sections.append("".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        sections.append("".join(current))

    # Further split sections that are still too long
    chunks: list[str] = []
    for section in sections:
        chunks.extend(chunk_text(section, max_chars))

    return chunks


def post_memory(text: str, metadata: dict, source: str, dry_run: bool) -> int:
    """POST a single memory. Returns HTTP status code (0 if dry-run)."""
    if dry_run:
        preview = text[:100].replace("\n", " ")
        print(f"    [dry-run] {len(text)} chars: {preview}...")
        return 0

    response = requests.post(
        API_URL,
        headers={"X-API-Key": API_KEY},
        json={"text": text, "source": source, "metadata": metadata},
        timeout=15,
    )
    return response.status_code


# ---------------------------------------------------------------------------
# Source 1: Auto-memory files
# ---------------------------------------------------------------------------


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML-like frontmatter from a markdown file. Returns (meta, body)."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, content

    meta: dict = {}
    i = 1
    while i < len(lines) and lines[i].strip() != "---":
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
        i += 1

    body = "\n".join(lines[i + 1 :]).strip()
    return meta, body


def import_memory_files(
    projects_dir: Path, dry_run: bool, delay: float
) -> tuple[int, int, int]:
    posted = skipped = errors = 0

    memory_files = sorted(projects_dir.glob("*/memory/*.md"))
    # Exclude index files
    memory_files = [f for f in memory_files if f.name != "MEMORY.md"]

    print(f"\n=== SOURCE: auto-memory files ({len(memory_files)} files) ===")

    for path in memory_files:
        content = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(content)

        name = meta.get("name", path.stem)
        mem_type = meta.get("type", "unknown")
        project_dir = path.parent.parent.name  # e.g. "-home-shu-projects-open-brain"

        text = f"[{mem_type}] {name}\n\n{body}"

        if len(text) < 100:
            print(f"  SKIP (too short, {len(text)} chars): {path.name}")
            skipped += 1
            continue

        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"  POST{chunk_label}: [{mem_type}] {name} ({path.parent.parent.name}/{path.name})")

        for idx, chunk in enumerate(chunks):
            metadata = {
                "project_dir": project_dir,
                "file_name": path.name,
                "memory_type": mem_type,
                "memory_name": name,
                "chunk_index": idx,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, "claude_code_memory", dry_run)
            if not dry_run:
                if status in (200, 202):
                    posted += 1
                else:
                    print(f"      ERROR status={status}")
                    errors += 1
                if idx < len(chunks) - 1:
                    time.sleep(delay)

        if not dry_run:
            time.sleep(delay)

    return posted, skipped, errors


# ---------------------------------------------------------------------------
# Source 2: history.jsonl
# ---------------------------------------------------------------------------


def import_history(history_file: Path, dry_run: bool, delay: float) -> tuple[int, int, int]:
    posted = skipped = errors = 0

    if not history_file.exists():
        print(f"\n=== SOURCE: history.jsonl — NOT FOUND at {history_file} ===")
        return 0, 0, 0

    entries: list[dict] = []
    for line in history_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    # Group by project
    by_project: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        project = entry.get("project", "unknown")
        display = entry.get("display", "").strip()
        # Skip slash commands and trivial entries
        if not display or display.startswith("/") or len(display) < 20:
            continue
        by_project[project].append(entry)

    print(f"\n=== SOURCE: history.jsonl ({len(by_project)} projects, {len(entries)} total entries) ===")

    for project, items in sorted(by_project.items()):
        project_name = Path(project).name
        sessions = {item.get("sessionId", "") for item in items}
        prompts = [item["display"] for item in items]

        lines = [f"PROJECT: {project}", ""]
        lines += [f"- {p}" for p in prompts]
        text = "\n".join(lines)

        if len(text) < 100:
            skipped += 1
            continue

        chunks = chunk_text(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"  POST{chunk_label}: {project_name} ({len(prompts)} prompts, {len(sessions)} sessions)")

        for idx, chunk in enumerate(chunks):
            metadata = {
                "project": project,
                "project_name": project_name,
                "session_count": len(sessions),
                "entry_count": len(prompts),
                "chunk_index": idx,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, "claude_code_history", dry_run)
            if not dry_run:
                if status in (200, 202):
                    posted += 1
                else:
                    print(f"      ERROR status={status}")
                    errors += 1
                if idx < len(chunks) - 1:
                    time.sleep(delay)

        if not dry_run:
            time.sleep(delay)

    return posted, skipped, errors


# ---------------------------------------------------------------------------
# Source 3: CLAUDE.md files
# ---------------------------------------------------------------------------


def decode_project_path(dir_name: str) -> str:
    """Convert ~/.claude/projects dir name back to filesystem path.

    Example: '-home-shu-projects-open-brain' → '/home/shu/projects/open-brain'
    The dir name replaces '/' with '-', leading '-' represents root '/'.
    """
    # Strip leading '-', then replace remaining '-' with '/'... but hyphens in
    # actual dir names are also '-', so we can't naively replace all '-'.
    # Best approach: the dir name starts with '-' because path starts with '/'.
    # We reconstruct by replacing '-' with '/' then fixing double-slashes.
    # This works for standard Linux paths (/home/user/projects/foo-bar).
    # For paths with hyphens in component names we'd get ambiguity, but that's
    # acceptable — we validate existence below.
    if dir_name.startswith("-"):
        return dir_name.replace("-", "/")
    return dir_name


def discover_project_dirs(projects_dir: Path, history_file: Path) -> list[Path]:
    """Collect unique project dirs from history.jsonl + ~/.claude/projects/ dir names."""
    dirs: set[Path] = set()

    # From history.jsonl
    if history_file.exists():
        for line in history_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                project = entry.get("project", "")
                if project:
                    dirs.add(Path(project))
            except json.JSONDecodeError:
                continue

    # From ~/.claude/projects/ dir names
    if projects_dir.exists():
        for subdir in projects_dir.iterdir():
            if subdir.is_dir():
                decoded = decode_project_path(subdir.name)
                dirs.add(Path(decoded))

    return sorted(dirs)


def import_claude_md(projects_dir: Path, history_file: Path, dry_run: bool, delay: float) -> tuple[int, int, int]:
    posted = skipped = errors = 0

    candidate_dirs = discover_project_dirs(projects_dir, history_file)
    found = [(d, d / "CLAUDE.md") for d in candidate_dirs if (d / "CLAUDE.md").exists()]

    print(f"\n=== SOURCE: CLAUDE.md files ({len(found)} found of {len(candidate_dirs)} candidate dirs) ===")

    for project_dir, claude_md_path in found:
        project_name = project_dir.name
        content = claude_md_path.read_text(encoding="utf-8")
        text = f"CLAUDE.md for {project_name}\n\n{content}"

        if len(text) < 300:
            print(f"  SKIP (too short): {project_name}")
            skipped += 1
            continue

        chunks = chunk_text_by_heading(text)
        chunk_label = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
        print(f"  POST{chunk_label}: {project_name} ({len(content)} chars)")

        for idx, chunk in enumerate(chunks):
            metadata = {
                "project_dir": str(project_dir),
                "project_name": project_name,
                "file_size": len(content),
                "chunk_index": idx,
                "chunk_total": len(chunks),
            }
            status = post_memory(chunk, metadata, "claude_code_project", dry_run)
            if not dry_run:
                if status in (200, 202):
                    posted += 1
                else:
                    print(f"      ERROR status={status}")
                    errors += 1
                if idx < len(chunks) - 1:
                    time.sleep(delay)

        if not dry_run:
            time.sleep(delay)

    return posted, skipped, errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Import Claude Code local knowledge into Open Brain")
    parser.add_argument(
        "--sources",
        default="memory,history,claude_md",
        help="Comma-separated list of sources: memory,history,claude_md (default: all)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without posting")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between requests (default: 0.5)")
    parser.add_argument(
        "--claude-dir",
        type=Path,
        default=CLAUDE_DIR,
        help=f"Override ~/.claude directory (default: {CLAUDE_DIR})",
    )
    args = parser.parse_args()

    sources = {s.strip() for s in args.sources.split(",")}
    valid = {"memory", "history", "claude_md"}
    unknown = sources - valid
    if unknown:
        print(f"ERROR: Unknown source(s): {unknown}. Valid: {valid}")
        sys.exit(1)

    claude_dir: Path = args.claude_dir
    projects_dir = claude_dir / "projects"
    history_file = claude_dir / "history.jsonl"

    if args.dry_run:
        print("DRY RUN — nothing will be posted\n")

    total_posted = total_skipped = total_errors = 0

    if "memory" in sources:
        p, s, e = import_memory_files(projects_dir, args.dry_run, args.delay)
        total_posted += p
        total_skipped += s
        total_errors += e

    if "history" in sources:
        p, s, e = import_history(history_file, args.dry_run, args.delay)
        total_posted += p
        total_skipped += s
        total_errors += e

    if "claude_md" in sources:
        p, s, e = import_claude_md(projects_dir, history_file, args.dry_run, args.delay)
        total_posted += p
        total_skipped += s
        total_errors += e

    print(f"\nDone. posted={total_posted} skipped={total_skipped} errors={total_errors}")
    if total_errors:
        print("Check errors above and re-run the affected --sources if needed.")


if __name__ == "__main__":
    main()
