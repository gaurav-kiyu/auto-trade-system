"""
Load ``INDEX_MAP`` from bundled ``index_config.defaults.json`` so dashboards and tools
stay aligned with the index bot without duplicating Yahoo/NSE symbols.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.defaults_loader import load_defaults_file


def normalize_index_map_entry(_name: str, meta: Any) -> dict[str, Any] | None:
    if not isinstance(meta, dict):
        return None
    for req in ("yf", "nse", "step", "lot"):
        if req not in meta:
            return None
    out = dict(meta)
    out.setdefault("sector", "INDEX")
    out.setdefault("category", "INDEX")
    out.setdefault("tags", ["INDEX"])
    return out


def load_index_map(project_root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = project_root or Path(__file__).resolve().parent.parent
    try:
        raw = load_defaults_file(root, "index_config.defaults.json")
    except (OSError, ValueError):
        return {}
    im = raw.get("INDEX_MAP")
    if not isinstance(im, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in im.items():
        ne = normalize_index_map_entry(str(k), v)
        if ne:
            out[str(k)] = ne
    return out
