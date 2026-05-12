#!/usr/bin/env python3
"""
Create runtime JSON from bundled defaults when missing:

  - Index bot: ``index_config.defaults.json`` → ``config.json``
  - Stock bot: ``stock_config.defaults.json`` → ``stock_config.json``

  python scripts/bootstrap_config.py           # both, if missing
  python scripts/bootstrap_config.py --index-only
  python scripts/bootstrap_config.py --stock-only

Secrets: edit the new file or use ``config.local.json`` (gitignored) for BOT_TOKEN / CHAT_ID.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _copy_if_missing(src: Path, dest: Path, *, label: str) -> bool:
    if dest.exists():
        print(f"bootstrap_config: skip {label} (exists): {dest}")
        return False
    shutil.copy2(src, dest)
    print(f"bootstrap_config: created {label} from {src.name} → {dest}")
    return True


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index-only", action="store_true")
    p.add_argument("--stock-only", action="store_true")
    args = p.parse_args(argv)

    index = not args.stock_only
    stock = not args.index_only
    n = 0
    if index:
        if _copy_if_missing(ROOT / "index_config.defaults.json", ROOT / "config.json", label="index"):
            n += 1
    if stock:
        if _copy_if_missing(ROOT / "stock_config.defaults.json", ROOT / "stock_config.json", label="stock"):
            n += 1
    if n == 0 and not (ROOT / "config.json").exists() and not (ROOT / "stock_config.json").exists():
        print("bootstrap_config: nothing to do (or both targets already exist)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
