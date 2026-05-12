"""JSON Schema checks for merged bot config (same artifacts as CI / ``scripts/``)."""

from __future__ import annotations

import json
import os
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, Literal

_FLAVOUR = Literal["index", "stock"]
_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_NAMES = {"index": "index_config.schema.json", "stock": "stock_config.schema.json"}


def append_json_schema_errors(
    errors: list[str],
    cfg: MutableMapping[str, Any],
    *,
    flavour: _FLAVOUR,
) -> None:
    """
    Append schema violations to ``errors`` (no-op if ``jsonschema`` is unavailable).

    Uses committed ``schemas/{index|stock}_config.schema.json`` generated from bundled
    defaults — same single-source pattern as ``scripts/generate_config_schemas.py``.

    Set ``OPB_SKIP_JSON_SCHEMA=1`` to skip (emergency operator override only).
    """
    if os.environ.get("OPB_SKIP_JSON_SCHEMA", "").strip().lower() in ("1", "true", "yes"):
        return
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return

    name = _SCHEMA_NAMES[flavour]
    path = _REPO_ROOT / "schemas" / name
    if not path.is_file():
        errors.append(f"Bundled JSON Schema missing: {name} (run scripts/generate_config_schemas.py)")
        return

    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
    except Exception as e:
        errors.append(f"Invalid JSON Schema {name}: {e}")
        return

    if not isinstance(cfg, dict):
        errors.append("config root must be a dict for JSON Schema validation")
        return

    _max = 40
    all_errs = sorted(validator.iter_errors(cfg), key=lambda x: list(x.path))
    for i, e in enumerate(all_errs):
        if i >= _max:
            if len(all_errs) > _max:
                errors.append(f"JSON Schema: ({len(all_errs) - _max} more violations omitted)")
            break
        loc = "/".join(str(x) for x in e.path) or "(root)"
        errors.append(f"JSON Schema [{loc}]: {e.message}")
