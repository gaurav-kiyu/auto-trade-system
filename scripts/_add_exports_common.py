"""Shared library for auto-generating __all__ exports for Python modules.

Used by ``scripts/add_all_exports.py`` (core/) and
``scripts/add_index_app_exports.py`` (index_app/).

Provides:
  - get_public_symbols() — parse public top-level symbols from a file
  - file_has_all() — check if __all__ already exists
  - add_all_to_file() — insert __all__ after docstring/imports block
"""

import ast
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path


def get_public_symbols(
    filepath: str,
    *,
    filter_fn: Callable[[str], bool] | None = None,
) -> list[str]:
    """Parse a Python file and return sorted list of public symbol names.

    Args:
        filepath: Path to the Python file.
        filter_fn: Optional filter function that receives a symbol name and
            returns True if it should be included.  If None, all public
            (non-underscore-prefixed) symbols are included.

    Returns:
        Sorted list of public symbol names, or empty list on parse error.
    """
    with open(filepath, encoding="utf-8", errors="replace") as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return []

    symbols: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if not name.startswith("_"):
                if filter_fn is None or filter_fn(name):
                    symbols.append(name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    if filter_fn is None or filter_fn(target.id):
                        symbols.append(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                if filter_fn is None or filter_fn(node.target.id):
                    symbols.append(node.target.id)

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return sorted(unique)


def file_has_all(filepath: str) -> bool:
    """Check if file already has __all__ defined."""
    with open(filepath, encoding="utf-8", errors="replace") as f:
        content = f.read()
    return "__all__" in content


def add_all_to_file(filepath: str, symbols: list[str]) -> bool:
    """Add __all__ to a file after its docstring/imports block.

    Args:
        filepath: Path to the Python file.
        symbols: List of symbol names to include in __all__.

    Returns:
        True if the file was modified, False otherwise.
    """
    if not symbols:
        return False

    with open(filepath, encoding="utf-8", errors="replace") as f:
        content = f.read()

    all_lines = ["\n__all__ = ["]
    for sym in symbols:
        all_lines.append(f'    "{sym}",')
    all_lines.append("]\n")
    all_block = "\n".join(all_lines)

    lines = content.split("\n")
    insert_idx = 0
    in_docstring = False
    in_paren_import = False
    paren_depth = 0

    for i, line in enumerate(lines):
        stripped = line.strip()

        # Track opening parentheses for multi-line imports
        if in_paren_import or (
            stripped.startswith("from ")
            and "(" in stripped
            and ")" not in stripped.split("#")[0]
        ):
            in_paren_import = True
            for ch in stripped:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
            if paren_depth > 0:
                insert_idx = i + 1
                continue
            else:
                in_paren_import = False
                insert_idx = i + 1
                continue

        # Track multiline docstrings (ONLY at module level with 0 indentation)
        if not in_docstring and (
            stripped.startswith('"""') or stripped.startswith("'''")
        ):
            # CRITICAL: Only treat as docstring if at MODULE LEVEL (0 indentation)
            # Indented triple-quoted strings are SQL/JSON strings inside functions
            if line[: len(line) - len(line.lstrip())] != "":
                break
            actual_start = stripped.lstrip()
            if actual_start.startswith('"""') or actual_start.startswith("'''"):
                if (
                    actual_start[3:].strip().endswith('"""')
                    and len(actual_start[3:].strip()) >= 3
                ):
                    insert_idx = i + 1
                    continue
                else:
                    in_docstring = True
                    insert_idx = i + 1
                    continue

        if in_docstring:
            if stripped.endswith('"""') or stripped.endswith("'''"):
                in_docstring = False
                insert_idx = i + 1
                continue
            insert_idx = i + 1
            continue

        # Skip blank lines, comments, license lines
        if not stripped or stripped.startswith("#"):
            insert_idx = i + 1
            continue

        # Skip __future__ imports (must be at top)
        if stripped.startswith("from __future__"):
            insert_idx = i + 1
            continue

        # Skip regular imports
        if re.match(r"^(import |from )", stripped):
            insert_idx = i + 1
            continue

        # Skip leftover blank lines (MUST be before indentation check)
        if not stripped:
            continue

        # CRITICAL SAFETY CHECK: if this line has positive indentation,
        # we are inside a class/func/if/for block — STOP and insert BEFORE.
        if line[: len(line) - len(line.lstrip())] != "":
            break

        break

    prefix = "\n".join(lines[:insert_idx])
    if not prefix.endswith("\n"):
        prefix += "\n"
    if not prefix.endswith("\n\n"):
        prefix += "\n"

    suffix = "\n".join(lines[insert_idx:])
    new_content = prefix + all_block + "\n" + suffix

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_content)

    return True


def scan_and_add(
    target_dir: Path,
    *,
    skip_init: bool = True,
    skip_private: bool = False,
    symbol_filter: Callable[[str], bool] | None = None,
) -> int:
    """Scan *target_dir* and add __all__ to all modules missing it.

    Args:
        target_dir: Directory to scan recursively.
        skip_init: If True, skip ``__init__.py`` files.
        skip_private: If True, skip modules whose filename starts with ``_``.
        symbol_filter: Optional filter passed to ``get_public_symbols()``.

    Returns:
        Exit code (0 = success, 1 = errors).
    """
    count_checked = 0
    count_added = 0
    count_skipped_empty = 0
    count_errors = 0

    for root, dirs, files in os.walk(target_dir):
        if "__pycache__" in dirs:
            dirs.remove("__pycache__")

        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            if skip_init and fname == "__init__.py":
                continue
            if skip_private and fname.startswith("_"):
                continue

            filepath = os.path.join(root, fname)
            relpath = os.path.relpath(filepath, target_dir.parent)
            count_checked += 1

            if file_has_all(filepath):
                print(f"  SKIP (has __all__): {relpath}")
                continue

            symbols = get_public_symbols(filepath, filter_fn=symbol_filter)
            if not symbols:
                print(f"  SKIP (no public symbols): {relpath}")
                count_skipped_empty += 1
                continue

            try:
                if add_all_to_file(filepath, symbols):
                    print(f"  ADDED: {relpath} ({len(symbols)} symbols)")
                    count_added += 1
                else:
                    print(f"  SKIP (no change): {relpath}")
            except Exception as e:
                print(f"  ERROR: {relpath}: {e}", file=sys.stderr)
                count_errors += 1

    print(f"\n{'='*60}")
    print(f"Checked: {count_checked}")
    print(f"Added __all__: {count_added}")
    print(f"Skipped (no public symbols): {count_skipped_empty}")
    print(f"Errors: {count_errors}")
    return 1 if count_errors else 0
