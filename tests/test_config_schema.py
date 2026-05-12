"""JSON Schema drift + validation (defaults / templates)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run_script(rel: str, *args: str) -> subprocess.CompletedProcess[str]:
    script = ROOT / rel
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


def test_generate_config_schemas_check_passes():
    r = _run_script("scripts/generate_config_schemas.py", "--check")
    assert r.returncode == 0, r.stderr + r.stdout


def test_validate_config_schema_all_passes():
    r = _run_script("scripts/validate_config_schema.py", "--all")
    assert r.returncode == 0, r.stderr + r.stdout


def test_schema_files_exist():
    assert (ROOT / "schemas/index_config.schema.json").is_file()
    assert (ROOT / "schemas/stock_config.schema.json").is_file()
