#!/usr/bin/env python3
"""Unified Compliance Report Aggregator — OPB v2.57.0

Runs all validation tools and aggregates results into a single compliance report.

Tools executed (if available):
  1. Database integrity check (check_db_integrity.py)
  2. Config drift detection (check_config_drift.py)
  3. Code quality report (run_code_quality_report.py)
  4. Hygiene security scan (run_hygiene_scan.py)
  5. Print→logging migration analysis (migrate_print_to_logging.py)
  6. Benchmark suite (run_benchmarks.py) — optional, skip with --skip-benchmark

Output:
  - Single HTML dashboard with all results
  - JSON aggregate report
  - Overall PASS/FAIL status

Usage:
    python scripts/run_compliance_report.py
    python scripts/run_compliance_report.py --json
    python scripts/run_compliance_report.py --skip-benchmark
    python scripts/run_compliance_report.py --ci
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ── Configuration ─────────────────────────────────────────────────────────────

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
HTML_REPORT = REPORTS_DIR / "compliance_report.html"
JSON_REPORT = REPORTS_DIR / "compliance_report.json"

# Tools to run (name: module_path)
TOOLS: list[dict[str, Any]] = [
    {
        "name": "Database Integrity",
        "script": "scripts/check_db_integrity.py",
        "args": ["--no-html", "--json"],
        "critical": True,
        "weight": 20,
    },
    {
        "name": "Config Drift",
        "script": "scripts/check_config_drift.py",
        "args": ["--no-html", "--json"],
        "critical": False,
        "weight": 15,
    },
    {
        "name": "Code Quality",
        "script": "scripts/run_code_quality_report.py",
        "args": ["--no-html", "core/", "scripts/"],
        "critical": False,
        "weight": 20,
    },
    {
        "name": "Hygiene Security",
        "script": "scripts/run_hygiene_scan.py",
        "args": ["--no-html", "--json"],
        "critical": True,
        "weight": 25,
    },
    {
        "name": "Print→Logging Migration",
        "script": "scripts/migrate_print_to_logging.py",
        "args": ["--no-html", "--json", "--dir", "core/"],
        "critical": False,
        "weight": 10,
    },
    {
        "name": "Benchmarks",
        "script": "scripts/run_benchmarks.py",
        "args": ["--no-html"],
        "critical": False,
        "weight": 10,
        "skip_flag": "--skip-benchmark",
    },
]


def _run_tool(tool: dict[str, Any], skip_benchmarks: bool = False) -> dict[str, Any]:
    """Run a single validation tool and capture its output."""
    if skip_benchmarks and tool.get("skip_flag") == "--skip-benchmark":
        return {
            "name": tool["name"],
            "status": "skipped",
            "exit_code": 0,
            "output": "Skipped (--skip-benchmark)",
            "duration_sec": 0,
        }

    script_path = Path(tool["script"])
    if not script_path.exists():
        return {
            "name": tool["name"],
            "status": "not_found",
            "exit_code": -1,
            "output": f"Script not found: {tool['script']}",
            "duration_sec": 0,
        }

    cmd = [sys.executable, str(script_path)] + tool["args"]
    print(f"\n  [{tool['name']}] Running: {' '.join(cmd)}")

    t0 = time.time()
    try:
        # Benchmarks need longer timeout (6 benchmarks × 100+ iterations)
        timeout_sec = 600 if "benchmark" in tool["script"].lower() else 120
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        elapsed = time.time() - t0

        return {
            "name": tool["name"],
            "status": "passed" if result.returncode == 0 else "failed",
            "exit_code": result.returncode,
            "output": result.stdout.strip()[-2000:] if result.stdout else "",
            "errors": result.stderr.strip()[-500:] if result.stderr else "",
            "duration_sec": round(elapsed, 2),
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 10),
        }
    except subprocess.TimeoutExpired:
        return {
            "name": tool["name"],
            "status": "timed_out",
            "exit_code": -1,
            "output": "Timed out after 120s",
            "duration_sec": 120,
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 10),
        }
    except FileNotFoundError as e:
        return {
            "name": tool["name"],
            "status": "error",
            "exit_code": -1,
            "output": str(e),
            "duration_sec": round(time.time() - t0, 2),
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 10),
        }


def _compute_score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall compliance score from tool results."""
    total_weight = 0
    weighted_score = 0
    passed = 0
    failed = 0
    critical_failures = 0

    for r in results:
        if r["status"] == "skipped":
            continue
        weight = r.get("weight", 10)
        total_weight += weight
        if r["status"] == "passed":
            weighted_score += weight
            passed += 1
        else:
            failed += 1
            if r.get("critical", False):
                critical_failures += 1

    overall_pct = (weighted_score / total_weight * 100) if total_weight > 0 else 0

    # Grade
    if overall_pct >= 95 and critical_failures == 0:
        grade = "A+"
    elif overall_pct >= 90 and critical_failures == 0:
        grade = "A"
    elif overall_pct >= 80:
        grade = "B"
    elif overall_pct >= 70:
        grade = "C"
    elif overall_pct >= 60:
        grade = "D"
    else:
        grade = "F"

    status = "PASS" if (overall_pct >= 80 and critical_failures == 0) else "FAIL"

    return {
        "overall_score_pct": round(overall_pct, 1),
        "grade": grade,
        "status": status,
        "passed": passed,
        "failed": failed,
        "critical_failures": critical_failures,
        "total_weight": total_weight,
        "weighted_score": weighted_score,
    }


def _generate_html(results: list[dict[str, Any]], score: dict[str, Any]) -> str:
    """Generate comprehensive HTML compliance report."""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S IST")

    overall_color = "#4CAF50" if score["status"] == "PASS" else "#f44336"

    rows = ""
    for r in results:
        icon = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "not_found": "⚠️",
                 "timed_out": "⏰", "error": "❌"}.get(r["status"], "❓")
        color = {"passed": "#4CAF50", "failed": "#f44336", "skipped": "#888"}.get(r["status"], "#FF9800")
        critical_badge = " 🔴 CRITICAL" if r.get("critical") and r["status"] != "passed" else ""
        rows += f"""
        <tr style="border-left: 4px solid {color};">
            <td>{icon}</td>
            <td><strong>{r['name']}</strong>{critical_badge}</td>
            <td>{r['status'].upper()}</td>
            <td>{r.get('exit_code', 'N/A')}</td>
            <td>{r.get('duration_sec', 'N/A')}s</td>
            <td>{r.get('output', '')[:200]}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Compliance Report — OPB v2.57.0</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f5f5f5; }}
h1, h2 {{ color: #333; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; background: #fff; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 14px; }}
th {{ background: #4A90D9; color: white; }}
tr:nth-child(even) {{ background: #f9f9f9; }}
.score {{ font-size: 64px; font-weight: bold; text-align: center; padding: 20px; }}
.grade {{ font-size: 36px; font-weight: bold; text-align: center; }}
.summary {{ padding: 15px; border-radius: 5px; margin: 10px 0; }}
.pass {{ background: #e8f5e9; }}
.fail {{ background: #ffebee; }}
</style>
</head>
<body>
<h1>📋 Unified Compliance Report</h1>
<div class="summary {'pass' if score['status'] == 'PASS' else 'fail'}" style="text-align: center;">
    <div class="score" style="color: {overall_color};">{score['overall_score_pct']}%</div>
    <div class="grade" style="color: {overall_color};">Grade: {score['grade']} — {score['status']}</div>
    <p><strong>Timestamp:</strong> {timestamp}</p>
    <p><strong>Passed:</strong> {score['passed']} | <strong>Failed:</strong> {score['failed']} | <strong>Critical Failures:</strong> {score['critical_failures']}</p>
</div>
<h2>🔍 Tool Results</h2>
<table>
<tr><th>Status</th><th>Tool</th><th>Result</th><th>Exit</th><th>Duration</th><th>Output Summary</th></tr>
{rows}
</table>
<p style="color:#888; margin-top:30px;">Generated by OPB Unified Compliance Report v2.57.0</p>
</body>
</html>"""
    return html


def main() -> int:
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Unified Compliance Report Aggregator")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit non-zero on critical failures")
    parser.add_argument("--skip-benchmark", action="store_true", help="Skip benchmark suite (slow)")
    args = parser.parse_args()

    os.makedirs(REPORTS_DIR, exist_ok=True)

    print("=" * 60)
    print("  UNIFIED COMPLIANCE REPORT v2.57.0")
    print("=" * 60)
    print(f"\n  Running {len(TOOLS)} validation tools...")

    # Run all tools
    results = []
    for tool in TOOLS:
        result = _run_tool(tool, skip_benchmarks=args.skip_benchmark)
        results.append(result)

        status_icon = "✅" if result["status"] == "passed" else "❌" if result["status"] == "failed" else "⏭️"
        print(f"    {status_icon} {result['name']:<30s} ({result['status']})")

    # Compute score
    score = _compute_score(results)

    print(f"\n  ── Compliance Score: {score['overall_score_pct']}% (Grade: {score['grade']}) ──")
    print(f"  Status: {score['status']}")
    print(f"  Passed: {score['passed']} | Failed: {score['failed']} | Critical: {score['critical_failures']}")

    # Build final output
    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "version": "2.57.0",
        "score": score,
        "tools": results,
    }

    if args.json:
        print(json.dumps(output, indent=2, default=str))

    if not args.no_html:
        html = _generate_html(results, score)
        HTML_REPORT.write_text(html, encoding="utf-8")
        print(f"\n  HTML report: {HTML_REPORT}")

    JSON_REPORT.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(f"  JSON report: {JSON_REPORT}")

    if args.ci and score["status"] == "FAIL":
        print(f"\n❌ COMPLIANCE FAILED: {score['overall_score_pct']}% (minimum 80%)")
        return 1

    print("\n" + "=" * 60)
    print("  COMPLIANCE REPORT COMPLETE")
    print("=" * 60)
    return 0 if score["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
