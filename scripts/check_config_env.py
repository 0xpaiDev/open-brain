#!/usr/bin/env python3
"""Check that all Settings fields are documented in .env.example.

This script ensures that new config fields don't get added to config.py without
updating .env.example, preventing operator confusion and incomplete documentation.

Usage:
    python scripts/check_config_env.py [--fix]

Exit codes:
    0: All Settings fields found in .env.example
    1: Missing fields or other errors
"""

import os
import re
import sys
from pathlib import Path


def get_settings_fields() -> set[str]:
    """Extract all field names from Settings class in config.py."""
    config_path = Path(__file__).parent.parent / "src" / "core" / "config.py"
    with open(config_path) as f:
        content = f.read()

    # Find the Settings class and extract field definitions
    # Pattern: `field_name: type = default` or `field_name: type`
    pattern = r"^\s{4}(\w+):\s+\w+"
    fields = set()

    for line in content.split("\n"):
        match = re.match(pattern, line)
        if match:
            field_name = match.group(1)
            # Skip comments, model_config, validators
            if not field_name.startswith("_") and field_name != "model_config":
                fields.add(field_name)

    return fields


def get_env_example_keys() -> set[str]:
    """Extract all variable names from .env.example."""
    env_path = Path(__file__).parent.parent / ".env.example"
    with open(env_path) as f:
        content = f.read()

    # Pattern: VAR_NAME=value (skip comment lines)
    pattern = r"^([A-Z_][A-Z0-9_]*)="
    keys = set()

    for line in content.split("\n"):
        # Skip empty lines and comments
        if not line.strip() or line.strip().startswith("#"):
            continue
        match = re.match(pattern, line)
        if match:
            var_name = match.group(1)
            keys.add(var_name.lower())

    return keys


def main() -> int:
    """Check config consistency."""
    fix = "--fix" in sys.argv

    settings_fields = get_settings_fields()
    env_example_keys = get_env_example_keys()

    # Convert setting field names to env var names (snake_case → lowercase for comparison)
    expected_env_vars = {field.lower() for field in settings_fields}

    # Find missing env vars (both are lowercase)
    missing = expected_env_vars - env_example_keys

    if missing:
        print(f"❌ Missing from .env.example ({len(missing)} field{'s' if len(missing) > 1 else ''}):")
        for var in sorted(missing):
            print(f"  - {var}")
        return 1

    print(f"✅ All {len(settings_fields)} Settings fields are documented in .env.example")
    return 0


if __name__ == "__main__":
    sys.exit(main())
