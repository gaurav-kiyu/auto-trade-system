#!/usr/bin/env python3
"""
Validate JSON config files against generated schemas (see ``generate_config_schemas.py``).

  python scripts/validate_config_schema.py
  python scripts/validate_config_schema.py --path config.json --flavour index

``--flavour`` is ``index`` (default) or ``stock`` and selects which ``schemas/*.schema.json`` to use.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object at the top level")
    return data


def main(argv: list[str] | None = None) -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("validate_config_schema: install jsonschema (requirements-dev.txt)", file=sys.stderr)
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
        help="JSON file to validate (repeatable). Default: defaults + templates only (not operator config.json).",
    )
    ap.add_argument(
        "--all",
        action="store_true",
        help="Validate index + stock defaults and templates (CI default bundle).",
    )
    args = ap.parse_args(argv)

    def _run_one(flavour: str, paths: list[Path]) -> bool:
        schema_name = "index_config.schema.json" if flavour == "index" else "stock_config.schema.json"
        schema_path = SCHEMA_DIR / schema_name
        if not schema_path.is_file():
            print(f"validate_config_schema: missing {schema_path} — run generate_config_schemas.py", file=sys.stderr)
            return False
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        ok = True
        for p in paths:
            try:
                inst = _load_json(p)
            except Exception as e:
                print(f"{p.relative_to(ROOT)}: load error: {e}", file=sys.stderr)
                ok = False
                continue
            errs = sorted(validator.iter_errors(inst), key=lambda e: e.path)
            if errs:
                ok = False
                print(f"{p.relative_to(ROOT)} ({schema_name}):", file=sys.stderr)
                for e in errs[:50]:
                    loc = "/".join(str(x) for x in e.path) or "(root)"
                    print(f"  {loc}: {e.message}", file=sys.stderr)
                if len(errs) > 50:
                    print(f"  ... and {len(errs) - 50} more", file=sys.stderr)
        if ok:
            print(f"validate_config_schema: ok {flavour} ({len(paths)} file(s))")
        return ok

    if args.all:
        index_paths = [p for p in (ROOT / "index_config.defaults.json", ROOT / "config.template.json") if p.is_file()]
        stock_paths = [p for p in (ROOT / "stock_config.defaults.json", ROOT / "stock_config.template.json") if p.is_file()]
        if not index_paths or not stock_paths:
            print("validate_config_schema --all: expected defaults + template files present", file=sys.stderr)
            return 1
        a = _run_one("index", index_paths)
        b = _run_one("stock", stock_paths)
        return 0 if (a and b) else 1

    paths: list[Path] = []
    if args.path:
        paths.extend(Path(p) for p in args.path)
    else:
        if args.flavour == "index":
            cand = (ROOT / "index_config.defaults.json", ROOT / "config.template.json")
        else:
            cand = (ROOT / "stock_config.defaults.json", ROOT / "stock_config.template.json")
        paths = [p for p in cand if p.is_file()]

    if not paths:
        print("validate_config_schema: no files to validate", file=sys.stderr)
        return 1

    return 0 if _run_one(args.flavour, paths) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
