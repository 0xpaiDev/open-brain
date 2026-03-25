#!/usr/bin/env python3
"""Validate consistency between .env.example, config.py, and actual env var usage.

Checks:
1. All variables in .env.example have a corresponding Settings field
2. All os.environ.get() calls in code are documented in .env.example
3. Variable naming is consistent (e.g., OPEN_BRAIN_API_URL matches open_brain_api_url)

Exit 0 if consistent, exit 1 if any mismatches found.
"""

import re
import subprocess
import sys
from pathlib import Path


def parse_env_example() -> set[str]:
    """Extract all KEY= entries from .env.example."""
    env_file = Path(__file__).parent.parent / ".env.example"

    if not env_file.exists():
        print(f"Error: {env_file} not found")
        sys.exit(1)

    content = env_file.read_text()

    # Match lines like: KEY=value or KEY= (commented or not)
    pattern = r"^[#]*\s*([A-Z_][A-Z0-9_]*)="

    matches = re.findall(pattern, content, re.MULTILINE)

    return set(matches)


def parse_config_fields() -> set[str]:
    """Extract all Settings field names from src/core/config.py."""
    config_file = Path(__file__).parent.parent / "src" / "core" / "config.py"

    if not config_file.exists():
        print(f"Error: {config_file} not found")
        sys.exit(1)

    content = config_file.read_text()

    # Match lines like: field_name: Type = default_value
    pattern = r"^\s+([a-z_][a-z0-9_]*)\s*:"

    matches = re.findall(pattern, content, re.MULTILINE)

    ignored = {"model_config", "model_validate"}
    fields = set(m for m in matches if m not in ignored)

    return fields


def env_var_from_field(field_name: str) -> str:
    """Convert Python field name to environment variable name."""
    return field_name.upper()


def find_env_var_accesses() -> set[str]:
    """Find all os.environ.get() and os.getenv() calls in src/."""
    src_dir = Path(__file__).parent.parent / "src"

    result = subprocess.run(
        [
            "grep",
            "-rh",
            r'os\.environ\.get\|os\.getenv',
            str(src_dir),
            "--include=*.py",
        ],
        capture_output=True,
        text=True,
    )

    # Extract variable names from patterns like:
    # os.environ.get("VAR_NAME", ...)
    # os.getenv("VAR_NAME", ...)
    pattern = r'(?:os\.environ\.get|os\.getenv)\s*\(\s*["\']([A-Z_][A-Z0-9_]*)["\']'

    matches = re.findall(pattern, result.stdout)

    return set(matches)


def main() -> int:
    """Main entry point."""
    env_vars = parse_env_example()
    config_fields = parse_config_fields()
    accessed_vars = find_env_var_accesses()

    errors = []

    # Check 1: All .env.example entries have corresponding Settings fields
    undocumented_in_config = set()
    # These variables are used in standalone scripts/integrations, not in Settings
    STANDALONE_VARS = {"OPENBRAIN_API_KEY", "DOMAIN"}

    for env_var in env_vars:
        field_name = env_var.lower()
        if field_name not in config_fields:
            # Special case: variables used in standalone scripts, not main config
            if env_var not in STANDALONE_VARS:
                undocumented_in_config.add(env_var)

    if undocumented_in_config:
        errors.append(
            f"Variables in .env.example but not in config.py:\n  - "
            + "\n  - ".join(sorted(undocumented_in_config))
        )

    # Check 2: All os.environ.get() calls are documented in .env.example
    undocumented_in_env = accessed_vars - env_vars
    if undocumented_in_env:
        errors.append(
            f"Variables accessed in code but not in .env.example:\n  - "
            + "\n  - ".join(sorted(undocumented_in_env))
        )

    if errors:
        print("Error: Environment variable inconsistencies found:")
        for error in errors:
            print(f"  {error}")
        return 1

    print(f"✓ Environment variables consistent")
    print(f"  - {len(env_vars)} variables in .env.example")
    print(f"  - {len(config_fields)} fields in config.py")
    print(f"  - {len(accessed_vars)} variables accessed in code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
