"""Load bundled JSON defaults (single source of truth for built-in config keys)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


__all__ = [
    "load_defaults_file",
]

def load_defaults_file(project_root: Path, filename: str) -> dict[str, Any]:
    """
    Load ``filename`` from ``project_root`` (typically the repository root).

    Raises if the file is missing so mis-packaged installs fail fast instead of
    running with an empty implicit default tree.
    """
    path = (project_root / filename).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Bundled defaults missing: {path}")
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{filename} must contain a JSON object at the top level")
    return data
