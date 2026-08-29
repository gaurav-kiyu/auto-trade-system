#!/usr/bin/env python3
"""Print → Logging Migration Tool — OPB v2.57.1

Scans Python files for `print()` calls and provides actionable migration
guidance to replace them with proper logging via `core.logging`.

Features:
  - Detects print() calls and categorizes them (CLI output vs debug logging)
  - Suggests the appropriate log level and logger pattern
  - Can auto-generate the fix patches for non-CLI print() calls
  - Generates a migration report with effort estimates
  - CI mode: fails if production-code print() calls remain

Usage:
    python scripts/migrate_print_to_logging.py
    python scripts/migrate_print_to_logging.py --fix          # Apply auto-fixes
    python scripts/migrate_print_to_logging.py --ci           # CI gate
    python scripts/migrate_print_to_logging.py --json         # JSON output
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "logging_migration_report.html"
JSON_REPORT = REPORTS_DIR / "logging_migration_report.json"

EXCLUDE_DIRS = {
    "__pycache__", ".git", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
    "logs", "models", "dist", "build", "backups",
}

CLI_MARKERS = [
    "if __name__", "def main(", "def cli(", "argparse", "parser.parse_args",
    "print(json.dumps", "print(f\"  ", "print(\"═\"", "print(\"=\"",
    "print(report.summary", "print(result.summary",
    "print(status.summary", "print(state.summary",
    "summary_text()", "print(briefing.summary",
    "print(score.confidence", "print(corr.summary",
    "print(report.lead_time", "print(report.feature_completion",
    "--demo", "--stats", "--report",
]

# NOTE on --fix: The auto-replacement only handles single-line print(...) calls
# ending with ')'. Multi-line calls, nested parentheses like print(foo(bar)),
# or file=/end= keyword arguments will produce broken code.
# Always review --fix output before committing.


def _should_exclude(filepath: Path) -> bool:
    """Check if a file or directory should be excluded."""
    for part in filepath.parts:
        if part in EXCLUDE_DIRS:
            return True
    return False


def _has_logger_import(source: str) -> bool:
    """Check if the source already imports a logger."""
    patterns = [
        r"import logging",
        r"from core\.logging import",
        r"logger\s*=\s*logging\.getLogger",
        r"_logger\s*=\s*logging\.getLogger",
        r"_log\s*=\s*logging\.getLogger",
        r"log\s*=\s*logging\.getLogger",
        r"from core\.logging import get_logger",
        r"from core\.logging import StructuredLogger",
        r"from core\.logging import LoggingService",
    ]
    return any(re.search(p, source) for p in patterns)


def _suggest_log_level(line: str, context_before: list[str]) -> str:
    """Suggest the appropriate log level for a print() call."""
    lower = line.lower()

    # Error indicators
    if any(w in lower for w in ["error", "fail", "exception", "crash", "timeout", "rejected"]):
        return "error"
    if any(w in lower for w in ["warn", "caution", "deprecated"]):
        return "warning"

    # Debug indicators
    if any(w in lower for w in ["debug", "trace", "verbose", "inspector"]):
        return "debug"

    # Critical indicators
    if any(w in lower for w in ["critical", "fatal", "halt", "emergency"]):
        return "critical"

    # Info by default for status messages
    if any(w in lower for w in ["started", "complete", "ready", "initialized", "listening"]):
        return "info"

    # Check context for CLI markers
    for ctx_line in context_before:
        if any(m in ctx_line for m in CLI_MARKERS):
            return "cli_info"

    return "info"


def _is_cli_context(source_lines: list[str], line_idx: int) -> bool:
    """Check if a print() call is in a CLI/diagnostic context."""
    # Look backwards up to 10 lines for CLI markers
    start = max(0, line_idx - 10)
    for i in range(start, line_idx):
        line = source_lines[i] if i < len(source_lines) else ""
        if any(m in line for m in CLI_MARKERS):
            return True

    # Look at surrounding lines
    for offset in range(-1, 3):
        idx = line_idx + offset
        if 0 <= idx < len(source_lines):
            line = source_lines[idx]
            if "if __name__" in line or "def main" in line or "CLI" in line:
                return True

    return False


def _generate_logger_snippet(logger_name: str) -> str:
    """Generate the logger import snippet."""
    return 'import logging\n_log = logging.getLogger(__name__)\n'


def analyze_file(filepath: Path) -> dict[str, Any]:
    """Analyze a single file for print() calls and suggest migration."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
        source_lines = source.splitlines(keepends=True)
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError) as e:
        return {"file": str(filepath), "error": str(e), "print_calls": [], "print_count": 0}

    has_logger = _has_logger_import(source)
    print_calls: list[dict[str, Any]] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not isinstance(func, ast.Name) or func.id != "print":
            continue

        line_num = node.lineno
        line = source_lines[line_num - 1] if line_num <= len(source_lines) else ""
        stripped = line.strip()

        is_cli = _is_cli_context(source_lines, line_num - 1)
        log_level = _suggest_log_level(stripped, source_lines[max(0, line_num - 5):line_num])

        # Generate fix suggestion
        if is_cli:
            suggestion = "LEAVE AS PRINT (CLI context)"
        elif not has_logger:
            suggestion = f"REPLACE WITH: _log.{log_level}(...)"
        else:
            suggestion = f"REPLACE WITH: _log.{log_level}(...) (logger already imported)"

        print_calls.append({
            "line": line_num,
            "code": stripped[:100],
            "is_cli": is_cli,
            "suggested_level": log_level,
            "suggestion": suggestion,
            "needs_logger_import": not has_logger and not is_cli,
        })

    return {
        "file": str(filepath),
        "loc": len(source_lines),
        "has_logger": has_logger,
        "print_count": len(print_calls),
        "print_calls": print_calls,
        "error": None,
    }


def scan_directory(directory: Path) -> dict[str, Any]:
    """Scan all Python files in a directory for print() calls."""
    results: dict[str, Any] = {
        "directory": str(directory),
        "total_files": 0,
        "files_with_prints": 0,
        "total_print_calls": 0,
        "cli_print_calls": 0,
        "production_print_calls": 0,
        "files_needing_logger": 0,
        "file_reports": [],
        "time_estimate_minutes": 0,
    }

    py_files = sorted(directory.rglob("*.py"))

    for filepath in py_files:
        if _should_exclude(filepath):
            continue

        results["total_files"] += 1
        report = analyze_file(filepath)
        results["file_reports"].append(report)

        if report["print_count"] > 0:
            results["files_with_prints"] += 1
            results["total_print_calls"] += report["print_count"]

            for pc in report["print_calls"]:
                if pc["is_cli"]:
                    results["cli_print_calls"] += 1
                else:
                    results["production_print_calls"] += 1

            if report["print_count"] > 0 and not report["has_logger"]:
                # Check if any production prints need logger
                has_production = any(
                    not pc["is_cli"] for pc in report["print_calls"]
                )
                if has_production:
                    results["files_needing_logger"] += 1

    # Time estimate: ~2 min per file with production prints + ~1 min per file with only CLI prints
    production_files = sum(
        1 for r in results["file_reports"]
        if any(not pc["is_cli"] for pc in r.get("print_calls", []))
    )
    cli_only_files = results["files_with_prints"] - production_files
    results["time_estimate_minutes"] = production_files * 2 + cli_only_files * 1

    return results


def _generate_auto_fix(report: dict[str, Any], dry_run: bool = True) -> list[dict[str, Any]]:
    """Generate auto-fix patches for production print() calls.

    Args:
        report: File analysis report.
        dry_run: If True, only report what would be changed.

    Returns:
        List of fix descriptions.
    """
    fixes = []
    filepath = Path(report["file"])
    if not filepath.exists():
        return fixes

    production_calls = [pc for pc in report.get("print_calls", []) if not pc["is_cli"]]
    if not production_calls:
        return fixes

    try:
        source = filepath.read_text(encoding="utf-8")
        source_lines = source.splitlines(keepends=True)

        needs_logger = report["print_count"] > 0 and not report["has_logger"]
        modified_lines = list(source_lines)

        # Add logger import if needed (right after existing imports)
        if needs_logger:
            # Find the last import line
            last_import_idx = -1
            for i, line in enumerate(source_lines):
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    last_import_idx = i

            insert_idx = last_import_idx + 1 if last_import_idx >= 0 else 0
            logger_import = "import logging\n_log = logging.getLogger(__name__)\n"
            modified_lines.insert(insert_idx, logger_import)
            fixes.append(f"  + Added logging import at line {insert_idx + 1}")

        # Apply fixes for each production print call (reverse order to preserve line numbers)
        for pc in reversed(production_calls):
            idx = pc["line"] - 1
            if idx >= len(modified_lines):
                continue

            original_line = modified_lines[idx]
            # Simple replacement: print(...) → _log.info(...)
            # This won't handle multi-line print() calls, but handles the common case
            stripped = original_line.strip()
            if stripped.startswith("print(") and stripped.endswith(")"):
                # Extract the content inside print()
                content = stripped[6:-1]  # Remove 'print(' and ')'
                new_line = f"_log.{pc['suggested_level']}({content})\n"
                # Preserve indentation
                indent = original_line[:len(original_line) - len(original_line.lstrip())]
                modified_lines[idx] = f"{indent}{new_line}"
                fixes.append(f"  → Line {pc['line']}: print() → _log.{pc['suggested_level']}()")

        if not dry_run:
            filepath.write_text("".join(modified_lines), encoding="utf-8")
            fixes.append(f"  ✅ Written to {report['file']}")

    except OSError as e:
        fixes.append(f"  ❌ Error: {e}")

    return fixes


def _generate_html(results: list[dict[str, Any]], total: dict[str, Any]) -> str:
    """Generate HTML report."""
    timestamp = total["timestamp"]
    total_prints = total["total_print_calls"]
    production_prints = total["production_print_calls"]
    cli_prints = total["cli_print_calls"]
    files_with = total["files_with_prints"]

    file_rows = ""
    for result in results:
        count = result.get("print_count", 0)
        if count == 0:
            continue
        prod = sum(1 for pc in result.get("print_calls", []) if not pc["is_cli"])
        cli = sum(1 for pc in result.get("print_calls", []) if pc["is_cli"])
        has_log = "✅" if result.get("has_logger") else "❌"
        file_rows += f"""
        <tr>
            <td><code>{result['file']}</code></td>
            <td>{count}</td>
            <td>{prod}</td>
            <td>{cli}</td>
            <td>{has_log}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Logging Migration Report — OPB v2.57.1</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.warning {{ background: #fff3e0; padding: 15px; border-radius: 5px; margin: 10px 0; }}
</style>
</head>
<body>
<h1>📝 Print → Logging Migration Report</h1>
<div class="summary">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Total print() calls:</strong> {total_prints}</p>
<p><strong>Production prints (migrate):</strong> {production_prints}</p>
<p><strong>CLI/diagnostic prints (keep):</strong> {cli_prints}</p>
<p><strong>Files with prints:</strong> {files_with}</p>
</div>
<div class="warning">
<p><strong>📋 Migration Plan:</strong></p>
<p>To migrate <strong>{production_prints}</strong> production print() calls to logging:</p>
<ol>
    <li>Run with <code>--fix</code> to auto-migrate simple cases: <code>python scripts/migrate_print_to_logging.py --fix</code></li>
    <li>Review remaining complex cases (multi-line print(), f-string formatting)</li>
    <li>Estimated effort: <strong>{total.get('time_estimate_minutes', 'N/A')}</strong> minutes</li>
</ol>
</div>
<h2>📁 Files with print() calls</h2>
<table>
<tr><th>File</th><th>Total</th><th>Production</th><th>CLI</th><th>Has Logger</th></tr>
{file_rows}
</table>
<p style="color:#888; margin-top:30px;">Generated by OPB Print→Logging Migration Tool v2.57.1</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(
        description="Print -> Logging Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/migrate_print_to_logging.py
  python scripts/migrate_print_to_logging.py --ci
  python scripts/migrate_print_to_logging.py --fix
  python scripts/migrate_print_to_logging.py --dir core/ --json
        """,
    )
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: fail if production print() calls exist")
    parser.add_argument("--fix", action="store_true",
                        help="Auto-fix simple production print() -> logging replacements")
    parser.add_argument("--dir", default="core", help="Directory to scan (default: core/)")
    # Handle --help explicitly via binary stdout to avoid UnicodeEncodeError
    # on Windows when stdout is piped through cp1252 encoding
    if "-h" in sys.argv or "--help" in sys.argv:
        sys.stdout.buffer.write(parser.format_help().encode("utf-8"))
        sys.stdout.buffer.flush()
        return 0

    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    directory = Path(args.dir)

    if not directory.is_dir():
        print(f"❌ Directory not found: {directory}")
        return 1

    print("=" * 60)
    print("  PRINT → LOGGING MIGRATION TOOL v2.57.1")
    print("=" * 60)
    print(f"\n  Scanning {directory}/...")

    # Scan all files
    all_results = scan_directory(directory)
    file_reports = all_results["file_reports"]

    # Print summary
    print(f"\n  Total files scanned:    {all_results['total_files']}")
    print(f"  Files with print():     {all_results['files_with_prints']}")
    print(f"  Total print() calls:    {all_results['total_print_calls']}")
    print(f"  Production (migrate):   {all_results['production_print_calls']}")
    print(f"  CLI/diagnostic (keep):  {all_results['cli_print_calls']}")
    print(f"  Files needing logger:   {all_results['files_needing_logger']}")
    print(f"  Estimated effort:       {all_results['time_estimate_minutes']} min")

    # Print per-file breakdown
    for report in file_reports:
        if report.get("print_count", 0) == 0:
            continue
        prod = sum(1 for pc in report.get("print_calls", []) if not pc["is_cli"])
        if prod > 0:
            print(f"\n  📄 {Path(report['file']).name}:")
            for pc in report["print_calls"]:
                if not pc["is_cli"]:
                    print(f"     {pc['suggestion']:<55s} Line {pc['line']:>4d}: {pc['code'][:50]}")

    # Auto-fix if requested
    if args.fix and all_results["production_print_calls"] > 0:
        print("\n  🔧 Auto-fixing production print() calls...")
        total_fixes = 0
        for report in file_reports:
            if report.get("print_count", 0) == 0:
                continue
            fixes = _generate_auto_fix(report, dry_run=False)
            if fixes:
                print(f"\n    {Path(report['file']).name}:")
                for fix in fixes:
                    print(f"      {fix}")
                total_fixes += len([f for f in fixes if f.startswith("  →")])
        print(f"\n  ✅ Applied {total_fixes} fix(es)")

    # Generate reports
    if args.json:
        print(json.dumps(all_results, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(file_reports, {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
            "total_print_calls": all_results["total_print_calls"],
            "production_print_calls": all_results["production_print_calls"],
            "cli_print_calls": all_results["cli_print_calls"],
            "files_with_prints": all_results["files_with_prints"],
            "time_estimate_minutes": all_results["time_estimate_minutes"],
        })
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {JSON_REPORT}")

    # CI mode
    if args.ci and all_results["production_print_calls"] > 0:
        print(f"\n❌ CI FAILED: {all_results['production_print_calls']} production print() calls remain")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
