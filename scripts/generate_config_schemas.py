#!/usr/bin/env python3
"""
Generate JSON Schema files from bundled defaults (single source of truth).

  python scripts/generate_config_schemas.py              # write schemas/*.schema.json
  python scripts/generate_config_schemas.py --check      # CI: fail if committed schemas drift

Index vs stock stay split: ``index_config.defaults.json`` → ``schemas/index_config.schema.json``,
``stock_config.defaults.json`` → ``schemas/stock_config.schema.json``.

Schemas use ``additionalProperties: true`` so future keys in ``config.json`` / ``stock_config.json``
do not break validation; known keys get types from defaults plus tightened bounds where safe.

Runtime: ``validate_config`` in both bots calls ``core.config_schema_validate.append_json_schema_errors``
against the same committed schema files (set ``OPB_SKIP_JSON_SCHEMA=1`` only for emergencies).

Validation: After generating schemas, use ``python scripts/validate_config_schema.py --all``
to verify that actual config files conform to the generated schemas.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "schemas"

META = "https://json-schema.org/draft/2020-12/schema"

# Tighten selected keys beyond “type from sample value”.
EXECUTION_MODE_ENUM = ("PAPER", "MANUAL", "AUTO", "SIGNALS", "SIGNAL_ONLY")
RISK_MODE_ENUM = ("FIXED", "PERCENT")
STOCK_ALERT_MODE_ENUM = ("OPTIONS", "EQUITY")


def _json_type_for_value(v: Any) -> dict[str, Any]:
    if v is None:
        return {"type": ["string", "number", "integer", "boolean", "object", "array", "null"]}
    if isinstance(v, bool):
        return {"type": "boolean"}
    if isinstance(v, int) and not isinstance(v, bool):
        return {"type": "integer"}
    if isinstance(v, float):
        return {"type": "number"}
    if isinstance(v, str):
        return {"type": "string"}
    if isinstance(v, list):
        if not v:
            return {"type": "array"}
        first = v[0]
        item = _json_type_for_value(first)
        # Homogeneous primitive lists
        if all(type(x) is type(first) for x in v) and isinstance(first, (str, int, float, bool)):
            return {"type": "array", "items": item}
        return {"type": "array", "items": {}}
    if isinstance(v, dict):
        return {"type": "object", "additionalProperties": True}
    return {}


def _refine_property(key: str, schema: dict[str, Any]) -> dict[str, Any]:
    t = schema.get("type")
    if key == "EXECUTION_MODE" and t == "string":
        return {"type": "string", "enum": list(EXECUTION_MODE_ENUM)}
    if key == "RISK_MODE" and t == "string":
        return {"type": "string", "enum": list(RISK_MODE_ENUM)}
    if key == "STOCK_ALERT_MODE" and t == "string":
        return {"type": "string", "enum": list(STOCK_ALERT_MODE_ENUM)}
    if key.startswith("NSE_") and key.endswith("_HOUR") and t == "integer":
        return {"type": "integer", "minimum": 0, "maximum": 23}
    if key.startswith("NSE_") and key.endswith("_MINUTE") and t == "integer":
        return {"type": "integer", "minimum": 0, "maximum": 59}
    if key == "NSE_POST_OPEN_NO_TRADE_MINUTES" and t == "integer":
        return {"type": "integer", "minimum": 0, "maximum": 240}
    return schema


def build_schema(*, defaults: dict[str, Any], schema_id: str, title: str) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for k, v in sorted(defaults.items()):
        props[k] = _refine_property(k, _json_type_for_value(v))
    return {
        "$schema": META,
        "$id": schema_id,
        "title": title,
        "type": "object",
        "additionalProperties": True,
        "properties": props,
    }


def _canonical_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if generated schemas differ from files on disk (CI drift guard)",
    )
    args = ap.parse_args(argv)

    pairs = [
        (
            ROOT / "index_config.defaults.json",
            SCHEMA_DIR / "index_config.schema.json",
            "https://opbuying.local/schemas/index_config",
            "Index bot merged config (config.json over index_config.defaults.json)",
        ),
        (
            ROOT / "stock_config.defaults.json",
            SCHEMA_DIR / "stock_config.schema.json",
            "https://opbuying.local/schemas/stock_config",
            "Stock bot merged config (stock_config.json over stock_config.defaults.json)",
        ),
    ]

    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    for def_path, out_path, sid, title in pairs:
        if not def_path.is_file():
            print(f"generate_config_schemas: missing defaults {def_path}", file=sys.stderr)
            return 1
        defaults = json.loads(def_path.read_text(encoding="utf-8"))
        if not isinstance(defaults, dict):
            print(f"generate_config_schemas: {def_path} must be a JSON object", file=sys.stderr)
            return 1
        schema = build_schema(defaults=defaults, schema_id=sid, title=title)
        text = _canonical_json(schema)
        if args.check:
            if not out_path.is_file():
                print(f"generate_config_schemas --check: missing {out_path}", file=sys.stderr)
                return 1
            existing = out_path.read_text(encoding="utf-8")
            if existing != text:
                print(
                    f"generate_config_schemas --check: {out_path.name} out of sync with {def_path.name}\n"
                    f"  Run: python scripts/generate_config_schemas.py",
                    file=sys.stderr,
                )
                return 1
        else:
            out_path.write_text(text, encoding="utf-8")
            print(f"wrote {out_path.relative_to(ROOT)}")

    if args.check:
        print("generate_config_schemas --check: ok (schemas match defaults)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
