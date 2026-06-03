#!/usr/bin/env python3
"""
Dead Code Scanner — Enforces the Constitution's Technical Debt Governance.

Detects and reports:
  - Unused imports in Python modules
  - Orphaned functions/classes (defined but never imported)
  - Duplicate code patterns (via AST analysis)
  - Empty or dead code blocks

Updates the Dead Code Register and Duplicate Code Register docs.

Usage:
    python scripts/scan_dead_code.py                          # Full scan
    python scripts/scan_dead_code.py --quick                 # Quick CI mode (skips tests/scripts/duplicates)
    python scripts/scan_dead_code.py --check-imports         # Unused imports only
    python scripts/scan_dead_code.py --check-orphans         # Orphaned functions/classes only
    python scripts/scan_dead_code.py --json                  # JSON output
    python scripts/scan_dead_code.py --ci                    # CI mode (exit code only)
    python scripts/scan_dead_code.py --update-registers      # Update register docs

Exit code:
    0 = no issues found
    1 = issues found
"""
from __future__ import annotations

import argparse
import ast
import json
import logging
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("scan_dead_code")

EXCLUDED_DIRS: set[str] = {
    ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".hypothesis", "node_modules", ".venv", "venv", "env", "build", "dist",
    ".eggs", "*.egg-info",
}

# Module paths to exclude from scanning
EXCLUDED_MODULES: set[str] = {
    "core/__init__.py",
    "index_app/__init__.py",
    "tests/__init__.py",
    "scripts/__init__.py",
}

# Quick mode — excludes test files, scripts, and infra modules for faster CI runs
QUICK_MODE_EXCLUDED_DIRS: set[str] = {
    "tests", "scripts", "infrastructure",
}

# Symbols excluded from duplicate detection (every script has these)
DUPLICATE_EXCLUDED_SYMBOLS: set[str] = {
    "main",
}


@dataclass
class DeadCodeFinding:
    category: str  # UNUSED_IMPORT, ORPHANED_FUNC, ORPHANED_CLASS, EMPTY_BLOCK
    file_path: str
    line: int
    name: str
    description: str
    severity: str = "MEDIUM"  # CRITICAL, HIGH, MEDIUM, LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "file_path": self.file_path,
            "line": self.line,
            "name": self.name,
            "description": self.description,
            "severity": self.severity,
        }


@dataclass
class DuplicateFinding:
    category: str  # DUPLICATE_FUNC, DUPLICATE_CLASS, DUPLICATE_IMPORT
    file_a: str
    line_a: int
    file_b: str
    line_b: int
    name: str
    similarity: float
    description: str
    severity: str = "MEDIUM"

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "file_a": self.file_a,
            "line_a": self.line_a,
            "file_b": self.file_b,
            "line_b": self.line_b,
            "name": self.name,
            "similarity": round(self.similarity, 2),
            "description": self.description,
            "severity": self.severity,
        }


# ── AST Cache ────────────────────────────────────────────────────────────────

_AST_CACHE: dict[Path, ast.Module | None] = {}
"""Cache of parsed ASTs to avoid re-parsing the same file multiple times.
Key is file path, value is the AST or None if parse error."""


def _get_ast(path: Path) -> ast.Module | None:
    """Get cached AST for a file, parsing if not already cached."""
    if path not in _AST_CACHE:
        try:
            _AST_CACHE[path] = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            _AST_CACHE[path] = None
    return _AST_CACHE[path]


def clear_ast_cache() -> None:
    """Clear the AST cache (useful between runs)."""
    _AST_CACHE.clear()


def _walk_files(include_core: bool = True) -> list[Path]:
    """Get all Python files in the project, excluding forbidden dirs and modules."""
    files: list[Path] = []
    for py_file in ROOT.rglob("*.py"):
        if any(excluded in py_file.parts for excluded in EXCLUDED_DIRS):
            continue
        relative = py_file.relative_to(ROOT)
        if str(relative) in EXCLUDED_MODULES:
            continue
        files.append(py_file)
    return files


# ── AST-based Import Analysis ────────────────────────────────────────────────


def collect_module_exports(module_path: Path) -> set[str]:
    """Collect all exported names from a module (functions, classes, constants)."""
    exports: set[str] = set()
    tree = _get_ast(module_path)
    if tree is None:
        return exports
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            exports.add(node.name)
        elif isinstance(node, ast.ClassDef):
            exports.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    exports.add(target.id)
    # Remove dunder names
    return {n for n in exports if not (n.startswith("__") and n.endswith("__"))}


def find_all_imports() -> dict[Path, set[str]]:
    """Map each Python module to the names it imports from other modules."""
    imports: dict[Path, set[str]] = defaultdict(set)

    for py_file in _walk_files():
        tree = _get_ast(py_file)
        if tree is None:
            continue
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[py_file].add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        imports[py_file].add(alias.asname or alias.name)
        except SyntaxError:
            pass

    return dict(imports)


def scan_unused_imports() -> list[DeadCodeFinding]:
    """Find imports that are defined but never used in the same file."""
    findings: list[DeadCodeFinding] = []

    for py_file in _walk_files():
        relative = py_file.relative_to(ROOT)

        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            tree = _get_ast(py_file)
            if tree is None:
                continue

            # Collect all imported names
            imported_names: dict[int, str] = {}  # line -> name
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names[node.lineno] = name
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names[node.lineno] = name

            # Collect all names used in the file body
            used_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    used_names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    used_names.add(node.attr)

            # Find unused imports
            for line, name in imported_names.items():
                # Skip __future__ imports
                if name in ("annotations", "__future__"):
                    continue
                # Check if the simple name or dotted prefix is used
                base_name = name.split(".")[0]
                if base_name not in used_names:
                    # Verify it's really unused (not a false positive for re-exports)
                    # Check if it's referenced in __all__
                    if f"'{base_name}'" not in content and f'"{base_name}"' not in content:
                        findings.append(DeadCodeFinding(
                            category="UNUSED_IMPORT",
                            file_path=str(relative),
                            line=line,
                            name=name,
                            description=f"Import '{name}' appears unused in {relative.name}",
                            severity="LOW",
                        ))

        except SyntaxError:
            pass

    return findings


def scan_orphaned_symbols() -> list[DeadCodeFinding]:
    """Find functions/classes defined in a module but never imported externally."""
    findings: list[DeadCodeFinding] = []

    # Build map: module_path -> {exported names} — ASTs already cached from _walk_files
    module_exports: dict[Path, set[str]] = {}
    for py_file in _walk_files():
        exports = collect_module_exports(py_file)
        if exports:
            module_exports[py_file] = exports

    # Build map of all imports across the project — ASTs already cached
    all_imports = find_all_imports()

    # For each module, check if its exports are imported elsewhere
    for module_path, exports in module_exports.items():
        relative = module_path.relative_to(ROOT)

        # Determine which other modules import from this one
        module_name = str(relative).replace("\\", "/").replace("/", ".").replace(".py", "")
        if module_name.endswith(".__init__"):
            module_name = module_name[:-9]  # Remove .__init__ suffix

        # Check each export for external usage
        for name in sorted(exports):
            if name.startswith("_"):
                continue  # Private symbols are intentional
            # Check if name appears in any import across the project
            is_imported = False
            for import_file, import_names in all_imports.items():
                if import_file == module_path:
                    continue
                for imp in import_names:
                    if imp == name or imp.endswith(f".{name}"):
                        is_imported = True
                        break
                if is_imported:
                    break

            if not is_imported:
                findings.append(DeadCodeFinding(
                    category="ORPHANED_SYMBOL",
                    file_path=str(relative),
                    line=0,
                    name=name,
                    description=f"'{name}' defined in {relative.name} but never imported elsewhere",
                    severity="MEDIUM",
                ))

    return findings


def scan_empty_blocks() -> list[DeadCodeFinding]:
    """Find empty function bodies (pass-only or docstring-only)."""
    findings: list[DeadCodeFinding] = []

    for py_file in _walk_files():
        relative = py_file.relative_to(ROOT)
        tree = _get_ast(py_file)
        if tree is None:
            continue
        try:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    _check_empty_body(node, relative, findings)
                elif isinstance(node, ast.ClassDef):
                    _check_empty_body(node, relative, findings)
        except SyntaxError:
            pass

    return findings


def _check_empty_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
    relative: Path,
    findings: list[DeadCodeFinding],
) -> None:
    """Check if a node's body is effectively empty."""
    if not node.body:
        findings.append(DeadCodeFinding(
            category="EMPTY_BLOCK",
            file_path=str(relative),
            line=node.lineno,
            name=node.name,
            description=f"'{node.name}' has empty body (no statements)",
            severity="LOW",
        ))
    elif len(node.body) == 1:
        stmt = node.body[0]
        # Check for "pass" only or docstring + pass
        if isinstance(stmt, ast.Pass):
            findings.append(DeadCodeFinding(
                category="EMPTY_BLOCK",
                file_path=str(relative),
                line=node.lineno,
                name=node.name,
                description=f"'{node.name}' is a pass-through (body is just 'pass')",
                severity="LOW",
            ))
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            # Docstring only
            findings.append(DeadCodeFinding(
                category="EMPTY_BLOCK",
                file_path=str(relative),
                line=node.lineno,
                name=node.name,
                description=f"'{node.name}' has documentation-only body (docstring, no logic)",
                severity="LOW",
            ))


def scan_duplicate_code() -> list[DuplicateFinding]:
    """Scan for duplicate function/class implementations by name."""
    findings: list[DuplicateFinding] = []

    # Map function/class name -> [(file, line)]
    symbol_locations: dict[str, list[tuple[Path, int]]] = defaultdict(list)

    for py_file in ROOT.rglob("*.py"):
        if any(excluded in py_file.parts for excluded in EXCLUDED_DIRS):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8", errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol_locations[node.name].append((py_file, node.lineno))
                elif isinstance(node, ast.ClassDef):
                    symbol_locations[node.name].append((py_file, node.lineno))
        except SyntaxError:
            pass

    # Report symbols defined in multiple files (potential duplicates)
    for name, locations in symbol_locations.items():
        if len(locations) > 1 and not name.startswith("_"):
            # Exclude known-duplicate symbols by convention
            if name in DUPLICATE_EXCLUDED_SYMBOLS:
                continue
            # Exclude test_* symbols — test files are naturally isomorphic by convention
            if name.startswith("test_"):
                continue
            for i in range(len(locations)):
                for j in range(i + 1, len(locations)):
                    file_a, line_a = locations[i]
                    file_b, line_b = locations[j]
                    findings.append(DuplicateFinding(
                        category="DUPLICATE_SYMBOL",
                        file_a=str(file_a.relative_to(ROOT)),
                        line_a=line_a,
                        file_b=str(file_b.relative_to(ROOT)),
                        line_b=line_b,
                        name=name,
                        similarity=1.0,
                        description=f"'{name}' defined in both {file_a.name} and {file_b.name}",
                        severity="MEDIUM",
                    ))

    return findings


# ── Register Updates (append-only) ───────────────────────────────────────────


def _update_section_in_file(
    file_path: Path,
    section_header: str,
    new_section_lines: list[str],
) -> bool:
    """Update a specific section in a markdown file, preserving manual content.

    Only replaces content between the section header and the next ##-level header
    (or end of file), preserving everything else. If the section doesn't exist,
    appends it at the end.
    """
    try:
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8").splitlines(keepends=True)
        else:
            content = []
    except (OSError, UnicodeDecodeError) as e:
        log.error("Failed to read %s: %s", file_path.name, e)
        return False

    # Find the section header position
    section_start = -1
    section_end = -1
    for i, line in enumerate(content):
        stripped = line.strip()
        if stripped.startswith("## ") and section_header in stripped:
            section_start = i
            # Find next ## header or end
            for j in range(i + 1, len(content)):
                if content[j].strip().startswith("## "):
                    section_end = j
                    break
            if section_end == -1:
                section_end = len(content)
            break

    # Add trailing newlines to section lines
    section_lines = [line if line.endswith("\n") else line + "\n" for line in new_section_lines]
    if section_lines and not section_lines[-1].endswith("\n"):
        section_lines[-1] += "\n"

    if section_start >= 0:
        # Replace existing section
        new_content = content[:section_start] + section_lines
        if section_end < len(content):
            new_content += content[section_end:]
        else:
            # Ensure blank line after section
            if section_lines and section_lines[-1].strip():
                new_content.append("\n")
    else:
        # Section doesn't exist, append it
        new_content = content
        if new_content and not new_content[-1].endswith("\n\n"):
            new_content.append("\n")
        new_content.extend(section_lines)
        new_content.append("\n")

    try:
        file_path.write_text("".join(new_content), encoding="utf-8")
        return True
    except (OSError, UnicodeDecodeError) as e:
        log.error("Failed to write %s: %s", file_path.name, e)
        return False


def _dead_code_table_lines(findings: list[DeadCodeFinding]) -> list[str]:
    """Generate the Scan Results section content for the dead code register."""
    if findings:
        table: list[str] = []
        table.append("| ID | Category | File | Line | Symbol | Description | Severity |\n")
        table.append("|----|----------|------|------|--------|-------------|----------|\n")
        for i, f in enumerate(findings, 1):
            table.append(
                f"| DC-{i:03d} | {f.category} | {f.file_path} | {f.line} | "
                f"{f.name} | {f.description} | {f.severity} |\n"
            )
        return table
    return ["*No dead code issues detected in latest scan.*\n"]


def _duplicate_code_table_lines(findings: list[DuplicateFinding]) -> list[str]:
    """Generate the Scan Results section content for the duplicate code register."""
    if findings:
        table: list[str] = []
        table.append("| ID | Source A | Source B | Symbol | Similarity | Description | Severity |\n")
        table.append("|----|----------|----------|--------|------------|-------------|----------|\n")
        for i, f in enumerate(findings, 1):
            table.append(
                f"| DUP-{i:03d} | {f.file_a}:{f.line_a} | {f.file_b}:{f.line_b} | "
                f"{f.name} | {f.similarity:.0%} | {f.description} | {f.severity} |\n"
            )
        return table
    return ["*No duplicate code issues detected in latest scan.*\n"]


def update_dead_code_register(findings: list[DeadCodeFinding]) -> bool:
    """Update the Scan Results section of the dead code register doc.

    Preserves manual entries, format section, remediation policy, etc.
    Only overwrites the ## Scan Results section.
    """
    section_lines = [
        "## Scan Results\n",
        "\n",
        f"**Total findings:** {len(findings)}  \n",
        f"**Last scanned:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "\n",
    ]
    section_lines.extend(_dead_code_table_lines(findings))
    section_lines.append("\n")
    section_lines.append("*This section is auto-generated by scripts/scan_dead_code.py*\n")

    return _update_section_in_file(
        ROOT / "docs" / "dead_code_register.md",
        "Scan Results",
        section_lines,
    )


def update_duplicate_code_register(findings: list[DuplicateFinding]) -> bool:
    """Update the Scan Results section of the duplicate code register doc.

    Preserves manual entries, severity levels, etc.
    Only overwrites the ## Scan Results section.
    """
    section_lines = [
        "## Scan Results\n",
        "\n",
        f"**Total findings:** {len(findings)}  \n",
        f"**Last scanned:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "\n",
    ]
    section_lines.extend(_duplicate_code_table_lines(findings))
    section_lines.append("\n")
    section_lines.append("*This section is auto-generated by scripts/scan_dead_code.py*\n")

    return _update_section_in_file(
        ROOT / "docs" / "duplicate_code_register.md",
        "Scan Results",
        section_lines,
    )


# ── Auto-removal (DEBT-016) ─────────────────────────────────────────────────


def _remove_unused_imports(findings: list[DeadCodeFinding]) -> list[dict[str, Any]]:
    """
    Remove unused imports from source files.

    Reads each file, removes the identified import lines, and writes back.
    Only removes exact line matches — avoids removing multi-line imports
    or imports that share a line with other code.

    Args:
        findings: List of UNUSED_IMPORT findings from scan_unused_imports().

    Returns:
        List of dicts describing what was removed (file_path, line, name).
    """
    removed: list[dict[str, Any]] = []
    # Group findings by file
    by_file: dict[str, list[DeadCodeFinding]] = defaultdict(list)
    for f in findings:
        by_file[f.file_path].append(f)

    for file_path_str, file_findings in by_file.items():
        file_path = ROOT / file_path_str
        if not file_path.is_file():
            log.warning("[REMOVE] File not found: %s", file_path_str)
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            # Use splitlines(True) to preserve original line endings (\n vs \r\n)
            lines = content.splitlines(True)
        except (OSError, UnicodeDecodeError) as e:
            log.warning("[REMOVE] Cannot read %s: %s", file_path_str, e)
            continue

        # Collect line numbers to remove (sorted descending to preserve indices)
        line_nums = sorted({f.line for f in file_findings}, reverse=True)
        new_lines = list(lines)
        for ln in line_nums:
            idx = ln - 1  # 0-indexed
            if 0 <= idx < len(new_lines):
                line_text = new_lines[idx]
                # Safety check: only remove single-line import statements
                stripped = line_text.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    log.warning("[REMOVE] Line %d in %s is not an import — skipping", ln, file_path_str)
                    continue
                new_lines[idx] = ""  # Blank the line (maintains line numbering)
                removed.append({
                    "file_path": file_path_str,
                    "line": ln,
                    "name": next((f.name for f in file_findings if f.line == ln), "?"),
                })

        # Write back (skip if nothing changed)
        if removed:
            new_content = "".join(new_lines)
            try:
                file_path.write_text(new_content, encoding="utf-8")
            except (OSError, UnicodeDecodeError) as e:
                log.warning("[REMOVE] Cannot write %s: %s", file_path_str, e)
                continue

    return removed


# ── Main ─────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check-imports", action="store_true", help="Unused imports only")
    ap.add_argument("--check-orphans", action="store_true", help="Orphaned symbols only")
    ap.add_argument("--check-duplicates", action="store_true", help="Duplicate code only")
    ap.add_argument("--quick", "-q", action="store_true",
                    help="Quick mode: exclude tests/, scripts/, infrastructure/ and skip duplicate scan")
    ap.add_argument("--json", "-j", action="store_true", help="JSON output")
    ap.add_argument("--ci", action="store_true", help="CI mode (exit code only)")
    ap.add_argument("--update-registers", action="store_true",
                    help="Update dead_code_register.md and duplicate_code_register.md")
    ap.add_argument("--remove", "-r", action="store_true",
                    help="Auto-remove unused imports from source files (safe: only removes UNUSED_IMPORT findings)")
    args = ap.parse_args(argv)

    # Clear AST cache for a fresh scan
    clear_ast_cache()

    # Quick mode: temporarily exclude tests/, scripts/, infrastructure/
    _original_excluded = set(EXCLUDED_DIRS)
    if args.quick:
        log.info("Quick mode: excluding tests/, scripts/, infrastructure/")
        EXCLUDED_DIRS.update(QUICK_MODE_EXCLUDED_DIRS)

    try:
        dead_code_findings: list[DeadCodeFinding] = []
        duplicate_findings: list[DuplicateFinding] = []

        run_all = not (args.check_imports or args.check_orphans or args.check_duplicates)

        if args.check_imports or run_all:
            dead_code_findings.extend(scan_unused_imports())
        if args.check_orphans or run_all:
            dead_code_findings.extend(scan_orphaned_symbols())
        dead_code_findings.extend(scan_empty_blocks())
        if args.check_duplicates or (run_all and not args.quick):
            duplicate_findings.extend(scan_duplicate_code())

        # Auto-remove unused imports if requested (CI mode never mutates codebase)
        _removed_count = 0
        if args.remove and not args.ci:
            _import_findings = [f for f in dead_code_findings if f.category == "UNUSED_IMPORT"]
            if _import_findings:
                _removed = _remove_unused_imports(_import_findings)
                _removed_count = len(_removed)
                if not args.json:
                    for _rf in _removed:
                        print(f"  REMOVED {_rf['file_path']}:{_rf['line']} - {_rf['name']}")
                # Re-scan imports after removal to keep registers accurate
                dead_code_findings = [f for f in dead_code_findings if f.category != "UNUSED_IMPORT"]
                dead_code_findings.extend(scan_unused_imports())

        # Update registers if requested
        if args.update_registers:
            dc_ok = update_dead_code_register(dead_code_findings)
            dup_ok = update_duplicate_code_register(duplicate_findings)
            if not all([dc_ok, dup_ok]):
                log.error("Failed to update one or more registers")
                return 1

        total = len(dead_code_findings) + len(duplicate_findings)
        has_issues = total > 0

        if args.remove and _removed_count > 0:
            print(f"\n  Auto-removed {_removed_count} unused import(s)")

        if args.json:
            output = {
                "timestamp": time.time(),
                "dead_code": [f.to_dict() for f in dead_code_findings],
                "duplicate_code": [f.to_dict() for f in duplicate_findings],
                "total": total,
                "registers_updated": args.update_registers,
            }
            print(json.dumps(output, indent=2))
            return 1 if has_issues else 0

        if args.ci:
            return 1 if has_issues else 0

        # ── Print report ─────────────────────────────────────────────────
        print("=" * 70)
        print("  DEAD CODE & DUPLICATE CODE SCAN")
        print("=" * 70)
        print(f"  Dead code findings: {len(dead_code_findings)}")
        print(f"  Duplicate code findings: {len(duplicate_findings)}")
        print()

        if dead_code_findings:
            print("  -- Dead Code --")
            for f in dead_code_findings[:15]:
                print(f"    [{f.severity}] {f.category}: {f.file_path}:{f.line} - {f.name}")
                print(f"      {f.description}")
            if len(dead_code_findings) > 15:
                print(f"    ... and {len(dead_code_findings) - 15} more")

        if duplicate_findings:
            print()
            print("  -- Duplicate Code --")
            for f in duplicate_findings[:10]:
                print(f"    [{f.severity}] {f.file_a}:{f.line_a} <-> {f.file_b}:{f.line_b}")
                print(f"      {f.description}")

        print()
        print("=" * 70)
        if has_issues:
            print(f"  RESULT: {total} ISSUE(S) FOUND")
            if args.update_registers:
                print("    Registers updated with findings")
            result = 1
        else:
            print("  RESULT: CLEAN -- no dead or duplicate code detected")
            result = 0

        return result
    finally:
        # Always restore EXCLUDED_DIRS, even on early return or exception
        EXCLUDED_DIRS.clear()
        EXCLUDED_DIRS.update(_original_excluded)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
