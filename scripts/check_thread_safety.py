#!/usr/bin/env python3
"""Thread Safety Analyzer — OPB v2.57.1

Scans Python source code for concurrency safety patterns:
  - Detects use of threading.RLock (recommended) vs threading.Lock (non-reentrant)
  - Identifies shared mutable state not protected by locks
  - Flags bare attribute access on shared objects outside lock context
  - Checks for known thread safety anti-patterns

Usage:
    python scripts/check_thread_safety.py
    python scripts/check_thread_safety.py --json
    python scripts/check_thread_safety.py --ci
"""

from __future__ import annotations

import ast
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "thread_safety_report.html"
JSON_REPORT = REPORTS_DIR / "thread_safety_report.json"

EXCLUDE_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis",
                "logs", "models", "dist", "build"}

# Thread-safe patterns we expect to see in well-guarded code
GOOD_LOCK_PATTERNS = {"threading.RLock(", "threading.Lock(", "self._lock", "with self._lock:"}
BAD_PATTERNS = {
    "threading.Lock(": "Non-reentrant Lock — use RLock for reentrant locks",
    "global ": "Global mutable state — verify lock coverage",
    "threading.Thread(": "Thread spawn — verify proper lifecycle management",
}
SHARED_STATE_INDICATORS = {"self._", "self.config", "self.state", "self._positions",
                           "self._history", "self._cache", "self._connections"}


def _should_exclude(filepath: Path) -> bool:
    for part in filepath.parts:
        if part in EXCLUDE_DIRS:
            return True
    return False


def analyze_file_for_thread_safety(filepath: Path) -> dict[str, Any]:
    """Analyze a single Python file for thread safety patterns."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, OSError) as e:
        return {"file": str(filepath), "error": str(e)}

    findings: list[dict[str, Any]] = []
    has_lock = False
    has_rlock = False
    has_dedicated_lock = False  # self._lock = threading.RLock()
    mutex_variable = ""

    # Scan for lock patterns
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Attribute):
                func_name = node.func.attr
            elif isinstance(node.func, ast.Name):
                func_name = node.func.id

            if "RLock" in func_name:
                has_rlock = True
                has_dedicated_lock = True
            elif "Lock" in func_name and "RLock" not in func_name:
                has_lock = True
                has_dedicated_lock = True

    # Scan for with self._lock patterns
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                expr = item.context_expr
                if isinstance(expr, ast.Attribute) and "_lock" in expr.attr:
                    has_dedicated_lock = True

    # Scan for shared state access outside lock context
    # Look for class methods that modify self._* without a lock context
    classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    for cls in classes:
        cls_name = cls.name
        for method in [n for n in ast.walk(cls) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            method_name = method.name
            if method_name.startswith("__"):  # Skip dunder methods
                continue
            if method_name in ("__init__", "__post_init__", "__new__"):  # Constructor typically doesn't need lock
                continue

            # Check if method body has a lock context
            has_lock_context = False
            for node in ast.walk(method):
                if isinstance(node, ast.With):
                    for item in node.items:
                        expr = item.context_expr
                        if isinstance(expr, ast.Attribute) and "_lock" in expr.attr:
                            has_lock_context = True
                            break

            # Check if method modifies shared state
            modifies_shared = False
            shared_attrs = []
            for node in ast.walk(method):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                            attr = target.attr
                            if attr.startswith("_") and not attr.startswith("__"):
                                modifies_shared = True
                                shared_attrs.append(attr)

            # Skip property setters and @property methods — they're expected to have fine-grained access
            is_property = any(
                isinstance(d, ast.Name) and d.id == "property"
                for d in method.decorator_list
            ) or any(
                isinstance(d, ast.Attribute) and d.attr == "setter"
                for d in method.decorator_list
            )

            if modifies_shared and not has_lock_context and not is_property and not method_name.startswith("_"):
                findings.append({
                    "line": method.lineno,
                    "type": "missing_lock",
                    "severity": "medium",
                    "class": cls_name,
                    "method": method_name,
                    "shared_attrs": shared_attrs,
                    "message": f"{cls_name}.{method_name} modifies {shared_attrs} but has no lock context",
                })

    # Check for threading.Lock vs threading.RLock usage
    if has_lock and not has_rlock:
        findings.append({
            "line": 0,
            "type": "non_reentrant_lock",
            "severity": "info",
            "message": "Uses threading.Lock — consider RLock for reentrant safety",
        })

    # Check for global variables modified outside lock
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            findings.append({
                "line": node.lineno,
                "type": "global_var",
                "severity": "info",
                "message": "Global variable usage — verify lock coverage",
            })

    return {
        "file": str(filepath),
        "has_lock": has_dedicated_lock,
        "has_rlock": has_rlock,
        "mutex_variable": mutex_variable,
        "findings": findings,
        "finding_count": len(findings),
    }


def scan_directory(directory: Path) -> dict[str, Any]:
    """Scan all Python files in a directory for thread safety patterns."""
    all_results = []
    total_files = 0
    files_with_lock = 0
    files_with_rlock = 0
    total_findings = 0

    for filepath in sorted(directory.rglob("*.py")):
        if _should_exclude(filepath):
            continue
        total_files += 1
        result = analyze_file_for_thread_safety(filepath)
        all_results.append(result)
        if result.get("has_lock"):
            files_with_lock += 1
        if result.get("has_rlock"):
            files_with_rlock += 1
        total_findings += result.get("finding_count", 0)

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "directory": str(directory),
        "total_files": total_files,
        "files_with_lock": files_with_lock,
        "files_with_rlock": files_with_rlock,
        "files_with_recommended_lock": files_with_rlock,
        "file_reports": all_results,
        "total_findings": total_findings,
        "findings": [f for r in all_results for f in r.get("findings", [])],
    }


def _generate_html(results: dict[str, Any]) -> str:
    """Generate HTML report."""
    findings = results.get("findings", [])

    # Group by severity
    by_severity = defaultdict(list)
    for f in findings:
        by_severity[f.get("severity", "info")].append(f)

    finding_rows = ""
    for f in findings:
        color = {"high": "red", "medium": "orange", "info": "#2196F3"}.get(f.get("severity", "info"), "")
        type_icon = {"missing_lock": "🔓", "non_reentrant_lock": "🔐", "global_var": "🌐"}.get(f.get("type", ""), "🔍")
        finding_rows += f"""
        <tr style="color:{color};">
            <td>{type_icon}</td>
            <td>{f.get('severity', '').upper()}</td>
            <td>{f.get('message', '')[:120]}</td>
            <td>Line {f.get('line', '?')}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Thread Safety Report — OPB v2.57.1</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.good {{ background: #e8f5e9; }}
.moderate {{ background: #fff3e0; }}
</style>
</head>
<body>
<h1>🔒 Thread Safety Analysis Report</h1>
<div class="summary">
<p><strong>Files Scanned:</strong> {results['total_files']}</p>
<p><strong>Files with Lock:</strong> {results['files_with_lock']}</p>
<p><strong>Files with RLock:</strong> {results['files_with_rlock']}</p>
<p><strong>Total Findings:</strong> {results['total_findings']}</p>
</div>
<h2>🔍 Thread Safety Findings</h2>
{'<table><tr><th></th><th>Severity</th><th>Finding</th><th>Location</th></tr>' + finding_rows + '</table>' if finding_rows else '<p>✅ No thread safety issues detected.</p>'}
<p style="color:#888; margin-top:30px;">Generated by OPB Thread Safety Analyzer v2.57.1</p>
</body>
</html>"""
    return html


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Thread Safety Analyzer")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--ci", action="store_true", help="CI mode")
    parser.add_argument("--dir", default="core", help="Directory to scan")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)
    directory = Path(args.dir)
    if not directory.is_dir():
        print(f"❌ Directory not found: {directory}")
        return 1

    print("=" * 60)
    print("  THREAD SAFETY ANALYZER v2.57.1")
    print("=" * 60)

    results = scan_directory(directory)

    print(f"\n  Files scanned:      {results['total_files']}")
    print(f"  Files with lock:    {results['files_with_lock']}")
    print(f"  Files with RLock:   {results['files_with_rlock']}")
    print(f"  Total findings:     {results['total_findings']}")

    if results["total_findings"] > 0:
        print("\n  Findings:")
        for f in results["findings"][:20]:
            print(f"    [{f.get('severity','?').upper()}] {f.get('message','')[:100]}")

    if args.json:
        print(json.dumps(results, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(results)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    if args.ci and results["total_findings"] > 0:
        medium_plus = sum(1 for f in results["findings"] if f.get("severity") in ("high", "medium"))
        if medium_plus > 0:
            print(f"\n❌ CI FAILED: {medium_plus} medium+ severity finding(s)")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
