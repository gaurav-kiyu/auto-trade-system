#!/usr/bin/env python3
"""
Validate JSON config files against generated schemas.

Consolidated v2: delegates validation logic to ``core.config_schema_validate``
to avoid duplicating schema loading / iteration logic. (DEBT-020)

Usage:
  python scripts/validate_config_schema.py
  python scripts/validate_config_schema.py --path config.json --flavour index
  python scripts/validate_config_schema.py --all

``--flavour`` is ``index`` (default) or ``stock``.

Regeneration: After changing any defaults file,
run ``python scripts/generate_config_schemas.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Ensure project root is on sys.path for editable-install-free environments
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object at the top level")
    return data


def main(argv: list[str] | None = None) -> int:
    # Early check: jsonschema must be installed (preserved from legacy behaviour)
    try:
        import jsonschema  # noqa: F401
    except ImportError:
        print("validate_config_schema: install jsonschema (requirements-dev.txt)", file=sys.stderr)
        return 1

    # Delegate the core validation logic to the module loaded by ConfigLoader
    try:
        from core.config_schema_validate import append_json_schema_errors
    except ImportError:
        print("validate_config_schema: core.config_schema_validate not available", file=sys.stderr)
        return 1

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--flavour",
        choices=("index", "stock"),
        default="index",
        help="Which schema to use (index_config.schema.json vs stock_config.schema.json)",
    )
    ap.add_argument(
        "--path",
        action="append",
        default=None,
        help="JSON file to validate (repeatable). Default: defaults + templates.",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Validate index + stock defaults and templates (CI bundle).",
    )
    args = ap.parse_args(argv)

    # Verify schema file exists before validation (preserved from legacy behaviour)
    SCHEMA_DIR = ROOT / "schemas"
    schema_name = "index_config.schema.json" if args.flavour == "index" else "stock_config.schema.json"
    schema_path = SCHEMA_DIR / schema_name
    if not schema_path.is_file() and not args.all:
        print(f"validate_config_schema: missing {schema_path} - run generate_config_schemas.py", file=sys.stderr)
        return 1

    def _run_one(flavour: str, paths: list[Path]) -> bool:
        ok = True
        for p in paths:
            try:
                inst = _load_json(p)
            except (json.JSONDecodeError, OSError, UnicodeDecodeError, ValueError) as e:
                print(f"{p.relative_to(ROOT)}: load error: {e}", file=sys.stderr)
                ok = False
                continue
            errs: list[str] = []
            append_json_schema_errors(errs, inst, flavour=flavour)  # type: ignore[arg-type]
            if errs:
                ok = False
                print(f"{p.relative_to(ROOT)} ({flavour}):", file=sys.stderr)
                for e in errs[:50]:
                    print(f"  {e}", file=sys.stderr)
                if len(errs) > 50:
                    print(f"  ... and {len(errs) - 50} more", file=sys.stderr)
        if ok:
            print(f"validate_config_schema: ok {flavour} ({len(paths)} file(s))")
        return ok

    if args.all:
        index_paths = [p for p in (ROOT / "index_config.defaults.json", ROOT / "config.template.json") if p.is_file()]
        stock_paths = [p for p in (ROOT / "stock_config.defaults.json", ROOT / "stock_config.template.json") if p.is_file()]
        if not index_paths or not stock_paths:
            print("validate_config_schema --all: expected defaults + template files", file=sys.stderr)
            return 1
        a = _run_one("index", index_paths)
        b = _run_one("stock", stock_paths)
        return 0 if (a and b) else 1

    paths: list[Path] = []
    if args.path:
        paths.extend(Path(p) for p in args.path)
    else:
        cand = (
            (ROOT / "index_config.defaults.json", ROOT / "config.template.json")
            if args.flavour == "index"
            else (ROOT / "stock_config.defaults.json", ROOT / "stock_config.template.json")
        )
        paths = [p for p in cand if p.is_file()]

    if not paths:
        print("validate_config_schema: no files to validate", file=sys.stderr)
        return 1

    return 0 if _run_one(args.flavour, paths) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
