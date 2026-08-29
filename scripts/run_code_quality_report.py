#!/usr/bin/env python3
"""Code Quality Report Generator — OPB v2.57.0

Generates comprehensive code quality reports including:
  - Cyclomatic complexity by function
  - Maintainability index
  - Function length distribution
  - Nesting depth analysis
  - File size distribution
  - Top-N most complex functions
  - HTML visualization

Usage:
    python scripts/run_code_quality_report.py
    python scripts/run_code_quality_report.py --json
    python scripts/run_code_quality_report.py --ci
"""

from __future__ import annotations

import ast
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "code_quality_report.html"
JSON_REPORT = REPORTS_DIR / "code_quality_report.json"
EXCLUDE_DIRS = {"__pycache__", ".git", "venv", ".venv", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
EXCLUDE_FILES = {"__init__.py"}
MAX_COMPLEXITY_WARN = 15  # Functions above this get flagged
MAX_COMPLEXITY_CRIT = 30  # Functions above this are critical
MAX_FUNCTION_LINES = 100   # Functions above this are flagged
MAX_FILE_LINES = 1000      # Files above this are flagged
MAX_NESTING_DEPTH = 6      # Nesting above this is flagged


# ── AST Analysis ──────────────────────────────────────────────────────────────


def _get_nesting_depth(node: ast.AST, current_depth: int = 0) -> int:
    """Calculate maximum nesting depth in an AST node."""
    max_depth = current_depth
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With,
                               ast.ExceptHandler, ast.AsyncFor, ast.AsyncWith)):
            child_depth = _get_nesting_depth(child, current_depth + 1)
            max_depth = max(max_depth, child_depth)
        else:
            child_depth = _get_nesting_depth(child, current_depth)
            max_depth = max(max_depth, child_depth)
    return max_depth


def _calculate_maintainability_index(
    loc: int,
    cyclomatic: int,
    halstead_volume: float = 0.0,
) -> float:
    """Calculate Maintainability Index (MI).

    MI = 171 - 5.2 * ln(Halstead Volume) - 0.23 * (Cyclomatic Complexity)
         - 16.2 * ln(Lines of Code)

    Scores: > 85 = highly maintainable
            65-85 = moderately maintainable
            < 65 = difficult to maintain
    """
    if loc <= 0:
        return 100.0
    try:
        mi = 171 - 5.2 * math.log(max(halstead_volume, 1)) \
             - 0.23 * cyclomatic \
             - 16.2 * math.log(max(loc, 1))
        return max(0, min(100, mi))
    except (ValueError, ArithmeticError):
        return 0.0


def _get_halstead_volume(node: ast.FunctionDef | ast.AsyncFunctionDef) -> float:
    """Calculate approximate Halstead volume for a function.

    Only counts arithmetic/comparison/logical operators (not call/attribute/subscript)
    to avoid inflated counts from non-trivial functions.
    """
    operators = set()
    operands = set()
    for child in ast.walk(node):
        if isinstance(child, (ast.Add, ast.Sub, ast.Mult, ast.Div,
                               ast.Mod, ast.Pow, ast.LShift, ast.RShift,
                               ast.BitOr, ast.BitXor, ast.BitAnd, ast.FloorDiv,
                               ast.And, ast.Or, ast.Not, ast.In, ast.NotIn,
                               ast.Is, ast.IsNot, ast.Eq, ast.NotEq,
                               ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            operators.add(type(child).__name__)
        if isinstance(child, (ast.Name, ast.Constant,)):
            if isinstance(child, ast.Name):
                operands.add(child.id)
            elif isinstance(child, ast.Constant):
                operands.add(str(getattr(child, 'value', '')))
    n1 = len(operators) or 1
    n2 = len(operands) or 1
    return n1 * math.log2(n1) + n2 * math.log2(n2)


def _analyze_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> dict[str, Any]:
    """Analyze a single function definition."""
    start_line = node.lineno
    end_line = max(
        getattr(node, 'end_lineno', start_line),
        start_line,
    )
    func_lines = end_line - start_line + 1

    # Cyclomatic complexity
    # Count branches: if, for, while, except, and/or/with, etc.
    cyclomatic = 1  # Base complexity
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.While, ast.For, ast.AsyncFor)):
            cyclomatic += 1
        elif isinstance(child, ast.ExceptHandler):
            cyclomatic += 1
        elif isinstance(child, ast.BoolOp):
            cyclomatic += len(child.values) - 1 if child.values else 0
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            cyclomatic += 1
        elif isinstance(child, ast.Assert):
            cyclomatic += 1

    # Nesting depth
    nesting = _get_nesting_depth(node)

    # Halstead volume (simplified)
    halstead = _get_halstead_volume(node)

    # Maintainability index
    mi = _calculate_maintainability_index(func_lines, cyclomatic, halstead)

    # Function source code (first 500 chars for report)
    source = "".join(source_lines[start_line - 1:end_line])
    source = source[:500]  # Truncate after join to avoid cutting mid-expression

    return {
        "name": node.name,
        "start_line": start_line,
        "end_line": end_line,
        "lines": func_lines,
        "cyclomatic_complexity": cyclomatic,
        "nesting_depth": nesting,
        "halstead_volume": round(halstead, 2),
        "maintainability_index": round(mi, 2),
        "source_preview": source,
    }


def _analyze_file(filepath: Path) -> dict[str, Any]:
    """Analyze a single Python file."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="ignore")
        source_lines = source.splitlines(keepends=True)
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as e:
        return {
            "file": str(filepath),
            "loc": 0,
            "error": str(e),
            "functions": [],
            "classes": [],
        }

    functions = []
    classes = []
    imports = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(_analyze_function(node, source_lines))
        elif isinstance(node, ast.ClassDef):
            cls_functions = []
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    cls_functions.append(_analyze_function(child, source_lines))
            classes.append({
                "name": node.name,
                "start_line": node.lineno,
                "methods": cls_functions,
                "method_count": len(cls_functions),
            })
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                imports.append(alias.name)

    loc = len(source_lines)
    max_complexity = max((f["cyclomatic_complexity"] for f in functions), default=0)
    avg_complexity = statistics.mean([f["cyclomatic_complexity"] for f in functions]) if functions else 0
    max_nesting = max((f["nesting_depth"] for f in functions), default=0)
    total_func_lines = sum(f["lines"] for f in functions)
    avg_mi = statistics.mean([f["maintainability_index"] for f in functions]) if functions else 100.0

    return {
        "file": str(filepath),
        "loc": loc,
        "import_count": len(set(imports)),
        "function_count": len(functions),
        "class_count": len(classes),
        "functions": functions,
        "classes": classes,
        "max_cyclomatic": max_complexity,
        "avg_cyclomatic": round(avg_complexity, 2),
        "max_nesting": max_nesting,
        "total_func_lines": total_func_lines,
        "avg_maintainability": round(avg_mi, 2),
        "complex_functions": [f for f in functions if f["cyclomatic_complexity"] > MAX_COMPLEXITY_WARN],
        "critical_functions": [f for f in functions if f["cyclomatic_complexity"] > MAX_COMPLEXITY_CRIT],
        "long_functions": [f for f in functions if f["lines"] > MAX_FUNCTION_LINES],
    }



def analyze_directory(directory: Path) -> dict[str, Any]:
    """Analyze all Python files in a directory tree."""
    results = {
        "directory": str(directory),
        "total_files": 0,
        "files_analyzed": 0,
        "files_with_errors": 0,
        "total_loc": 0,
        "total_functions": 0,
        "total_classes": 0,
        "file_reports": [],
        "summary": {},
    }

    py_files = sorted(directory.rglob("*.py"))
    for f in py_files:
        # Skip excluded dirs
        if any(excl in f.parts for excl in EXCLUDE_DIRS):
            continue
        if f.name in EXCLUDE_FILES:
            continue

        results["total_files"] += 1
        report = _analyze_file(f)
        results["file_reports"].append(report)

        if "error" in report and report["error"]:
            results["files_with_errors"] += 1
        else:
            results["files_analyzed"] += 1
            results["total_loc"] += report["loc"]
            results["total_functions"] += report["function_count"]
            results["total_classes"] += report["class_count"]

    # Compute summary
    all_complexities = []
    all_mis = []
    all_nestings = []
    all_func_lines = []
    all_file_locs = []
    all_critical = []
    all_long_funcs = []
    all_large_files = []

    for report in results["file_reports"]:
        if "error" in report:
            continue
        all_file_locs.append(report["loc"])
        if report["loc"] > MAX_FILE_LINES:
            all_large_files.append(report["file"])
        for fn in report.get("functions", []):
            all_complexities.append(fn["cyclomatic_complexity"])
            all_mis.append(fn["maintainability_index"])
            all_nestings.append(fn["nesting_depth"])
            all_func_lines.append(fn["lines"])
        for fn in report.get("critical_functions", []):
            all_critical.append(f"{report['file']}:{fn['name']} (CC={fn['cyclomatic_complexity']})")
        for fn in report.get("long_functions", []):
            all_long_funcs.append(f"{report['file']}:{fn['name']} ({fn['lines']} lines)")

    results["summary"] = {
        "total_files": results["total_files"],
        "files_analyzed": results["files_analyzed"],
        "files_with_errors": results["files_with_errors"],
        "total_loc": results["total_loc"],
        "total_functions": results["total_functions"],
        "total_classes": results["total_classes"],
        "avg_complexity": round(statistics.mean(all_complexities), 2) if all_complexities else 0,
        "max_complexity": max(all_complexities) if all_complexities else 0,
        "median_complexity": round(statistics.median(all_complexities), 2) if all_complexities else 0,
        "avg_maintainability": round(statistics.mean(all_mis), 2) if all_mis else 100.0,
        "min_maintainability": round(min(all_mis), 2) if all_mis else 100.0,
        "avg_nesting": round(statistics.mean(all_nestings), 2) if all_nestings else 0,
        "max_nesting": max(all_nestings) if all_nestings else 0,
        "avg_function_lines": round(statistics.mean(all_func_lines), 2) if all_func_lines else 0,
        "avg_file_loc": round(statistics.mean(all_file_locs), 2) if all_file_locs else 0,
        "max_file_loc": max(all_file_locs) if all_file_locs else 0,
        "critical_complexity_functions": all_critical,
        "long_functions": all_long_funcs,
        "large_files": all_large_files,
        "functions_above_warn_threshold": sum(1 for c in all_complexities if c > MAX_COMPLEXITY_WARN),
        "functions_above_critical_threshold": len(all_critical),
        "files_above_line_threshold": len(all_large_files),
        "thresh_complexity_warn": MAX_COMPLEXITY_WARN,
        "thresh_complexity_critical": MAX_COMPLEXITY_CRIT,
        "thresh_function_lines": MAX_FUNCTION_LINES,
        "thresh_file_lines": MAX_FILE_LINES,
        "thresh_nesting": MAX_NESTING_DEPTH,
    }

    return results


def _generate_html(results: dict[str, Any]) -> str:
    """Generate HTML visualization of code quality report."""
    s = results["summary"]
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S IST")

    # Top 10 most complex functions
    all_funcs = []
    for report in results["file_reports"]:
        if "error" in report:
            continue
        for fn in report.get("functions", []):
            all_funcs.append((fn["cyclomatic_complexity"], fn["name"], report["file"], fn["lines"]))

    top_complex = sorted(all_funcs, key=lambda x: -x[0])[:20]

    complex_rows = ""
    for cc, name, filepath, lines in top_complex:
        color = "red" if cc > MAX_COMPLEXITY_CRIT else "orange" if cc > MAX_COMPLEXITY_WARN else ""
        complex_rows += f'<tr style="color:{color};"><td>{cc}</td><td>{name}</td><td>{filepath}</td><td>{lines}</td></tr>'

    # Distribution
    complexity_buckets = {"1-5": 0, "6-10": 0, "11-15": 0, "16-20": 0, "21-30": 0, "31+": 0}
    for cc, _, _, _ in all_funcs:
        if cc <= 5:
            complexity_buckets["1-5"] += 1
        elif cc <= 10:
            complexity_buckets["6-10"] += 1
        elif cc <= 15:
            complexity_buckets["11-15"] += 1
        elif cc <= 20:
            complexity_buckets["16-20"] += 1
        elif cc <= 30:
            complexity_buckets["21-30"] += 1
        else:
            complexity_buckets["31+"] += 1

    dist_rows = ""
    for bucket, count in complexity_buckets.items():
        pct = (count / max(s["total_functions"], 1)) * 100
        bar_width = max(2, int(pct * 3))
        dist_rows += f'<tr><td>{bucket}</td><td>{count}</td><td>{pct:.1f}%</td><td><div style="background:#4A90D9;height:20px;width:{bar_width}px;border-radius:3px;"></div></td></tr>'

    # Large files
    large_file_rows = ""
    for f in s.get("large_files", []):
        large_file_rows += f"<tr><td>{f}</td></tr>"

    # Critical functions
    crit_func_rows = ""
    for f in s.get("critical_complexity_functions", []):
        crit_func_rows += f"<tr><td>{f}</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Code Quality Report — OPB v2.57.0</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2, h3 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0 20px; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.summary {{ background: #e8f5e9; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.warning {{ background: #fff3e0; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.critical {{ background: #ffebee; padding: 15px; border-radius: 5px; margin: 10px 0; }}
.good {{ background: #e8f5e9; }}
.moderate {{ background: #fff3e0; }}
.poor {{ background: #ffebee; }}
.score {{ font-size: 24px; font-weight: bold; }}
</style>
</head>
<body>
<h1>📊 Code Quality Report — OPB v2.57.0</h1>
<div class="summary">
<p><strong>Timestamp:</strong> {timestamp}</p>
<p><strong>Directory:</strong> {results['directory']}</p>
<p><strong>Files Analyzed:</strong> {s['files_analyzed']} / {s['total_files']}</p>
</div>

<h2>📈 Summary Metrics</h2>
<table>
<tr><th>Metric</th><th>Value</th><th>Rating</th></tr>
<tr><td>Total LOC</td><td>{s['total_loc']:,}</td><td></td></tr>
<tr><td>Total Functions</td><td>{s['total_functions']:,}</td><td></td></tr>
<tr><td>Total Classes</td><td>{s['total_classes']}</td><td></td></tr>
<tr><td>Avg Cyclomatic Complexity</td><td>{s['avg_complexity']}</td>
    <td class="{'good' if s['avg_complexity'] < 5 else 'moderate' if s['avg_complexity'] < 10 else 'poor'}">
        {'✅ GOOD' if s['avg_complexity'] < 5 else '⚠️ MODERATE' if s['avg_complexity'] < 10 else '❌ HIGH'}
    </td></tr>
<tr><td>Max Cyclomatic Complexity</td><td>{s['max_complexity']}</td>
    <td class="{'good' if s['max_complexity'] < 15 else 'moderate' if s['max_complexity'] < 30 else 'poor'}">
        {'✅ GOOD' if s['max_complexity'] < 15 else '⚠️ MODERATE' if s['max_complexity'] < 30 else '❌ HIGH'}
    </td></tr>
<tr><td>Avg Maintainability Index</td><td>{s['avg_maintainability']}</td>
    <td class="{'good' if s['avg_maintainability'] > 85 else 'moderate' if s['avg_maintainability'] > 65 else 'poor'}">
        {'✅ HIGH' if s['avg_maintainability'] > 85 else '⚠️ MODERATE' if s['avg_maintainability'] > 65 else '❌ LOW'}
    </td></tr>
<tr><td>Avg Function Lines</td><td>{s['avg_function_lines']}</td><td></td></tr>
<tr><td>Max Nesting Depth</td><td>{s['max_nesting']}</td>
    <td class="{'good' if s['max_nesting'] < 6 else 'moderate' if s['max_nesting'] < 10 else 'poor'}">
        {'✅ GOOD' if s['max_nesting'] < 6 else '⚠️ MODERATE' if s['max_nesting'] < 10 else '❌ HIGH'}
    </td></tr>
<tr><td>Functions > {MAX_COMPLEXITY_WARN} CC</td><td>{s['functions_above_warn_threshold']}</td><td></td></tr>
<tr><td>Functions > {MAX_COMPLEXITY_CRIT} CC</td><td>{s['functions_above_critical_threshold']}</td>
    <td class="{'good' if s['functions_above_critical_threshold'] == 0 else 'poor'}">
        {'✅ NONE' if s['functions_above_critical_threshold'] == 0 else '❌ NEEDS ATTENTION'}
    </td></tr>
<tr><td>Files > {MAX_FILE_LINES} lines</td><td>{len(s.get('large_files', []))}</td><td></td></tr>
</table>

<h2>📊 Complexity Distribution</h2>
<table>
<tr><th>Range</th><th>Count</th><th>%</th><th>Visual</th></tr>
{dist_rows}
</table>

<h2>🔥 Top 20 Most Complex Functions</h2>
<table>
<tr><th>Complexity</th><th>Function</th><th>File</th><th>Lines</th></tr>
{complex_rows}
</table>
"""
    if s.get("critical_complexity_functions"):
        html += f"""
<h2>🚨 Critical Complexity Functions (CC > {MAX_COMPLEXITY_CRIT})</h2>
<div class="critical">
<table>
<tr><th>Function</th></tr>
{crit_func_rows}
</table>
<p><strong>Recommendation:</strong> Decompose these functions into smaller units.</p>
</div>"""

    if s.get("large_files"):
        html += f"""
<h2>📁 Large Files (> {MAX_FILE_LINES} lines)</h2>
<div class="warning">
<table>
<tr><th>File</th></tr>
{large_file_rows}
</table>
<p><strong>Recommendation:</strong> Split these files into smaller modules.</p>
</div>"""

    html += """
<p style="color:#888; margin-top:30px;">Generated by OPB Code Quality Report v2.57.0</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Code Quality Report Generator")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero if critical functions exist")
    parser.add_argument("dirs", nargs="*", default=["core", "index_app", "scripts"],
                        help="Directories to analyze")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    for directory in args.dirs:
        path = Path(directory)
        if not path.is_dir():
            print(f"⚠️  Directory not found: {directory}", file=sys.stderr)
            continue

        print(f"\nAnalyzing {directory}/...")
        results = analyze_directory(path)

        if args.json:
            print(json.dumps(results, indent=2, default=str))

        if not args.no_html:
            html = _generate_html(results)
            HTML_REPORT.write_text(html, encoding="utf-8")
            print(f"  HTML report: {HTML_REPORT}")

        JSON_REPORT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        print(f"  JSON report: {JSON_REPORT}")

        s = results["summary"]
        print(f"\n  Summary for {directory}/:")
        print(f"    Files:         {s['files_analyzed']}")
        print(f"    LOC:           {s['total_loc']:,}")
        print(f"    Functions:     {s['total_functions']:,}")
        print(f"    Avg CC:        {s['avg_complexity']}")
        print(f"    Max CC:        {s['max_complexity']}")
        print(f"    Avg MI:        {s['avg_maintainability']}")
        print(f"    Critical CC:   {s['functions_above_critical_threshold']}")
        print(f"    Large Files:   {len(s.get('large_files', []))}")

        if s.get("critical_complexity_functions"):
            print("\n  ⚠️  Critical complexity functions:")
            for fn in s["critical_complexity_functions"]:
                print(f"    - {fn}")

    if args.ci:
        summary = results["summary"]
        if summary["functions_above_critical_threshold"] > 0:
            print(f"\n❌ CI FAILED: {summary['functions_above_critical_threshold']} function(s) exceed critical complexity")
            return 1
        if summary.get("large_files"):
            print(f"\n⚠️  CI WARNING: {len(summary['large_files'])} large file(s) found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
