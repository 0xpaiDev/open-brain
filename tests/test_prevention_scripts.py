"""Tests for prevention scripts (check_config, check_env).

Validates that the validation scripts correctly identify dead code and
configuration inconsistencies.
"""

import subprocess
import sys
from pathlib import Path
import tempfile
import shutil


def test_check_config_passes_with_clean_code() -> None:
    """check_config.py should pass when config is clean."""
    result = subprocess.run(
        [sys.executable, "scripts/check_config.py"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}: {result.stderr}"
    assert "All" in result.stdout or "used" in result.stdout


def test_check_env_passes_with_clean_code() -> None:
    """check_env_consistency.py should pass when env vars are consistent."""
    result = subprocess.run(
        [sys.executable, "scripts/check_env_consistency.py"],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}: {result.stderr}"
    assert "consistent" in result.stdout.lower()


def test_check_config_detects_dead_variables() -> None:
    """check_config.py should fail when a dead variable is introduced.

    This test temporarily adds a dead config variable to a test copy of config.py,
    runs the script, verifies it fails with the dead var in output, then cleans up.
    """
    project_root = Path(__file__).parent.parent
    config_file = project_root / "src" / "core" / "config.py"

    # Create a temporary backup
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        backup_file = tmpdir_path / "config.py.backup"
        test_config = tmpdir_path / "config.py"

        # Read original
        original_content = config_file.read_text()

        try:
            # Add a dead variable
            test_content = original_content.replace(
                "pulse_timezone: str = \"UTC\"",
                "pulse_timezone: str = \"UTC\"\n    dead_test_var: str = \"test\"  # This should trigger detection"
            )

            # Write test version
            test_config.write_text(test_content)

            # Temporarily replace the file
            shutil.copy2(config_file, backup_file)
            shutil.copy2(test_config, config_file)

            # Run check - should fail
            result = subprocess.run(
                [sys.executable, "scripts/check_config.py"],
                cwd=project_root,
                capture_output=True,
                text=True,
            )

            # Verify it detected the dead var
            assert result.returncode != 0, "Expected script to fail with dead variable"
            assert "dead_test_var" in result.stdout or "dead" in result.stdout.lower()

        finally:
            # Restore original file
            if backup_file.exists():
                shutil.copy2(backup_file, config_file)


def test_makefile_targets_exist() -> None:
    """Verify Makefile has check-config and check-env targets."""
    makefile = Path(__file__).parent.parent / "Makefile"
    content = makefile.read_text()

    assert "check-config:" in content, "Makefile missing check-config target"
    assert "check-env:" in content, "Makefile missing check-env target"
    assert "check-config" in content.split("help:")[1], "check-config not in help text"
    assert "check-env" in content.split("help:")[1], "check-env not in help text"
