#!/usr/bin/env python3
"""
Fail if common secrets / runtime artifacts are present in the working tree root.

Run from repo root before zipping or publishing:
  python scripts/verify_release_bundle.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

FORBIDDEN_ROOT_NAMES = {
    ".env",
    ".env.local",
    "trades.db",
    "trades.sqlite",
}

FORBIDDEN_DIR_PREFIXES = ("backup", "backups")

# With ``--ship-check`` (CI): fail if the tree cannot boot (missing defaults / core loaders).
REQUIRED_SHIP_FILES = (
    "index_config.defaults.json",
    "stock_config.defaults.json",
    "schemas/index_config.schema.json",
    "schemas/stock_config.schema.json",
    "scripts/generate_config_schemas.py",
    "scripts/validate_config_schema.py",
    "core/defaults_loader.py",
    "core/config_bootstrap.py",
    "core/datetime_ist.py",
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Directory to scan (default: repository root containing this script)",
    )
    p.add_argument(
        "--ship-check",
        action="store_true",
        help="Require shipping-critical paths (defaults JSON + core loaders); use in CI / before zips",
    )
    args = p.parse_args(argv)
    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    bad: list[str] = []
    if args.ship_check:
        for rel in REQUIRED_SHIP_FILES:
            ship_p = root / rel
            if not ship_p.is_file():
                bad.append(f"missing:{rel}")
    for name in FORBIDDEN_ROOT_NAMES:
        p = root / name
        if p.exists():
            bad.append(str(p.relative_to(root)))
    for child in root.iterdir():
        if not child.is_dir():
            continue
        low = child.name.lower()
        if any(low.startswith(pref) for pref in FORBIDDEN_DIR_PREFIXES):
            bad.append(str(child.relative_to(root)) + "/")
    if bad:
        print("verify_release_bundle: fix these issues before release/CI:", file=sys.stderr)
        for b in sorted(bad):
            print("  ", b, file=sys.stderr)
        return 1
    print("verify_release_bundle: ok (no forbidden root artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
