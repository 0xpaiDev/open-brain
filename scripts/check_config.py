#!/usr/bin/env python3
"""Validate that all Settings fields are used in the codebase.

Extracts all field names from src/core/config.py Settings class,
then greps the entire src/ directory (excluding config.py) to verify
each field is referenced at least once.

Exit 0 if all fields are used, exit 1 if any are found to be dead.
"""

import re
import subprocess
import sys
from pathlib import Path


def extract_settings_fields() -> list[str]:
    """Extract all Settings class field names from src/core/config.py."""
    config_file = Path(__file__).parent.parent / "src" / "core" / "config.py"

    if not config_file.exists():
        print(f"Error: {config_file} not found")
        sys.exit(1)

    content = config_file.read_text()

    # Match lines like: field_name: Type = default_value
    # or: field_name: Type  (with comments)
    pattern = r"^\s+([a-z_][a-z0-9_]*)\s*:"

    matches = re.findall(pattern, content, re.MULTILINE)

    # Filter out methods and internal fields
    ignored = {"model_config", "model_validate"}
    fields = [m for m in matches if m not in ignored]

    return sorted(set(fields))


def check_field_usage(field_name: str) -> bool:
    """Check if a field is referenced anywhere in src/ (excluding config.py)."""
    src_dir = Path(__file__).parent.parent / "src"

    # Use grep to search for the field name in Python files
    # Exclude config.py itself
    result = subprocess.run(
        [
            "grep",
            "-r",
            f"\\b{field_name}\\b",
            str(src_dir),
            "--include=*.py",
            "--exclude=config.py",
        ],
        capture_output=True,
        text=True,
    )

    # Return True if grep found matches (exit code 0)
    return result.returncode == 0


def main() -> int:
    """Main entry point."""
    fields = extract_settings_fields()

    if not fields:
        print("Warning: No Settings fields found")
        return 0

    # Variables that are intentionally unused (placeholders, legacy config, etc.)
    # These are documented in CLAUDE.md under "Deferred" section
    INTENTIONAL_UNUSED = {
        "api_host",  # Uvicorn host is set via CLI args, not config
        "api_port",  # Uvicorn port is set via CLI args, not config
        "embedding_dimensions",  # Used only for DDL in Alembic, not at runtime
        "importance_base_default",  # Placeholder for importance scoring (not yet used)
        "search_default_limit",  # Placeholder for search limits (not yet used)
        "strava_client_id",  # Strava OAuth (manual token refresh for MVP)
        "strava_client_secret",  # Strava OAuth (manual token refresh for MVP)
        "strava_refresh_token",  # Strava OAuth (manual token refresh for MVP)
        "module_training_enabled",  # Feature flag for training module (wired post-MVP)
    }

    dead_fields = []

    for field in fields:
        if not check_field_usage(field) and field not in INTENTIONAL_UNUSED:
            dead_fields.append(field)

    if dead_fields:
        print(f"Error: Found {len(dead_fields)} unused config variable(s):")
        for field in dead_fields:
            print(f"  - {field}")
        return 1

    print(f"✓ All {len(fields)} config variables are used")
    return 0


if __name__ == "__main__":
    sys.exit(main())
