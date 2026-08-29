#!/usr/bin/env python3
"""Pre-commit hook: detect stale documentation references to missing core modules.

Scans staged Markdown files for backtick-wrapped references like `core/foo.py`
and verifies the referenced module file exists on disk. Reports any stale
references (modules that were renamed, removed, or refactored) and exits
non-zero to block the commit.

Usage (via pre-commit):
    python scripts/check_stale_doc_refs.py path/to/doc.md

Usage (bulk check):
    python scripts/check_stale_doc_refs.py docs/*.md

Excluded paths (never flagged):
  - docs/archive/  (historical snapshots intentionally reference old modules)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# ── Patterns ─────────────────────────────────────────────────────────────────

# Match backtick-wrapped references like `core/foo.py` or `core/foo_bar.py`
_MODULE_REF_RE = re.compile(r"`(core/[a-z_]+\.py)`")

# Paths to always exclude from scanning (historical snapshots, etc.)
_EXCLUDED_PREFIXES = frozenset([
    "docs/archive/",
])


# ── Core check ───────────────────────────────────────────────────────────────

def check_file(doc_path: str) -> list[str]:
    """Scan a single Markdown file for stale module references.

    Returns a list of human-readable error messages (empty = clean).
    """
    # Normalize Windows-style backslash separators so backslash paths work on
    # POSIX runners too (there a literal backslash is not a path separator, so
    # Path.is_file() would silently return False and the scan would be skipped).
    path = Path(doc_path.replace("\\", "/"))
    if not path.is_file():
        return []

    # Skip excluded paths (e.g. docs/archive/ — historical snapshots)
    path_str = path.as_posix()
    for prefix in _EXCLUDED_PREFIXES:
        if path_str.startswith(prefix):
            return []

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"[WARN] Cannot read {doc_path}: {exc}"]

    errors: list[str] = []
    for match in _MODULE_REF_RE.finditer(content):
        ref = match.group(1)  # e.g. "core/foo.py"
        module_path = Path(ref)

        if not module_path.exists():
            errors.append(
                f"{doc_path}:{_line_number(content, match.start())}: "
                f"stale reference `{ref}` -- module file does not exist"
            )

    return errors


def _line_number(content: str, pos: int) -> int:
    """Return 1-based line number for a character position in content."""
    return content[:pos].count("\n") + 1


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> int:
    files = sys.argv[1:]
    if not files:
        print("No files provided - nothing to check.")
        return 0

    all_errors: list[str] = []
    for f in files:
        all_errors.extend(check_file(f))

    if all_errors:
        print("[FAIL] Stale documentation references detected:")
        for err in all_errors:
            print(f"   {err}")
        print(
            "\nFix these by either:\n"
            "  1. Updating the reference to the replacement module path\n"
            "  2. Removing the backticks and marking as [removed] if the module was truly deleted\n"
            "To bypass this check (non-risk changes only), commit with --no-verify.\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
