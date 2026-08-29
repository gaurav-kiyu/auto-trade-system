#!/usr/bin/env python3
"""Full System Certification Runner — OPB v2.57.0

Chains ALL validation and certification tools into a single comprehensive
certification pass. Produces a unified executive summary with PASS/FAIL status.

Tools executed (in order):
  1. Database Integrity       (check_db_integrity.py)
  2. Config Drift             (check_config_drift.py)
  3. Code Quality             (run_code_quality_report.py)
  4. Hygiene/Security         (run_hygiene_scan.py)
  5. Thread Safety            (check_thread_safety.py)
  6. Docker Security          (check_docker_security.py)
  7. Print→Logging Migration  (migrate_print_to_logging.py)
  8. Benchmarks               (run_benchmarks.py)
  9. Quantitative Validation  (quantitative_validation_report.py)
  10. Flamegraph Profiler     (run_flamegraph_profiler.py)
  11. Production Preflight    (production_preflight_check.py)
  12. Historical Comparison   (historical_comparison.py)
  13. Mutation Tests          (run_mutation_tests.py)

Output:
  - Unified HTML executive dashboard
  - JSON aggregate report
  - Per-tool individual reports in reports/

Usage:
    python scripts/run_certify.py
    python scripts/run_certify.py --fast          # Skip slow tools (benchmarks, mutation)
    python scripts/run_certify.py --ci             # CI mode: exit non-zero on failures
    python scripts/run_certify.py --json           # JSON output to stdout
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Force UTF-8 stdout/stderr so emoji in certification output does not crash on
# Windows cp1252 consoles (UnicodeEncodeError). Child tools already run with
# PYTHONIOENCODING=utf-8; the parent process needs the same guard.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Tool Registry ─────────────────────────────────────────────────────────────

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "Database Integrity",
        "script": "scripts/check_db_integrity.py",
        "args": [],
        "critical": True,
        "phase": "Storage",
        "fast": True,
        "weight": 10,
    },
    {
        "name": "Configuration Drift",
        "script": "scripts/check_config_drift.py",
        "args": [],
        "critical": False,
        "phase": "Config",
        "fast": True,
        "weight": 8,
    },
    {
        "name": "Code Quality",
        "script": "scripts/run_code_quality_report.py",
        "args": ["core/", "scripts/"],
        "critical": False,
        "phase": "Code Quality",
        "fast": True,
        "weight": 12,
    },
    {
        "name": "Hygiene & Security",
        "script": "scripts/run_hygiene_scan.py",
        "args": [],
        "critical": True,
        "phase": "Security",
        "fast": True,
        "weight": 15,
    },
    {
        "name": "Thread Safety",
        "script": "scripts/check_thread_safety.py",
        "args": [],
        "critical": True,
        "phase": "Concurrency",
        "fast": True,
        "weight": 10,
    },
    {
        "name": "Docker Security",
        "script": "scripts/check_docker_security.py",
        "args": [],
        "critical": True,
        "phase": "Deployment",
        "fast": True,
        "weight": 8,
    },
    {
        "name": "Print→Logging Migration",
        "script": "scripts/migrate_print_to_logging.py",
        "args": ["--dir", "core/"],
        "critical": False,
        "phase": "Code Quality",
        "fast": True,
        "weight": 5,
    },
    {
        "name": "Quantitative Validation",
        "script": "scripts/quantitative_validation_report.py",
        "args": [],
        "critical": True,
        "phase": "Performance",
        "fast": True,
        "weight": 12,
    },
    {
        "name": "Production Preflight",
        "script": "scripts/production_preflight_check.py",
        "args": [],
        "critical": True,
        "phase": "Operations",
        "fast": True,
        "weight": 10,
    },
    {
        "name": "Benchmarks",
        "script": "scripts/run_benchmarks.py",
        "args": [],
        "critical": False,
        "phase": "Performance",
        "fast": False,
        "weight": 8,
    },
    {
        "name": "Flamegraph Profiler",
        "script": "scripts/run_flamegraph_profiler.py",
        "args": ["import"],  # import profiling mode (safe, no args needed)
        "critical": False,
        "phase": "Performance",
        "fast": True,
        "weight": 5,
    },
    {
        "name": "Historical Comparison",
        "script": "scripts/historical_comparison.py",
        "args": [],
        "critical": False,
        "phase": "Quality",
        "fast": True,
        "weight": 5,
    },
    {
        "name": "Mutation Tests",
        "script": "scripts/run_mutation_tests.py",
        "args": ["--target", "core/services/risk_service.py", "--timeout", "30"],
        "critical": False,
        "phase": "Testing",
        "fast": False,
        "weight": 10,
    },
]


# ── Tool Runner ───────────────────────────────────────────────────────────────


def _run_tool(tool: dict[str, Any], skip_slow: bool = False) -> dict[str, Any]:
    """Run a single certification tool and return its result."""
    if skip_slow and not tool.get("fast", True):
        return {
            "name": tool["name"],
            "status": "skipped",
            "exit_code": 0,
            "output": "Skipped (fast mode)",
            "duration_sec": 0,
            "phase": tool.get("phase", ""),
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 5),
        }

    script_path = _PROJECT_ROOT / tool["script"]
    if not script_path.exists():
        return {
            "name": tool["name"],
            "status": "not_found",
            "exit_code": -1,
            "output": f"Script not found: {tool['script']}",
            "duration_sec": 0,
            "phase": tool.get("phase", ""),
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 5),
        }

    cmd = [sys.executable, str(script_path)] + tool["args"]
    phase = tool.get("phase", "")
    print(f"  [{phase:<14}] {tool['name']:<30s}...", end=" ", flush=True)

    t0 = time.time()
    # Longer timeout for slow tools (benchmarks, mutation)
    timeout_sec = 600 if not tool.get("fast", True) else 180
    try:
        # Force UTF-8 encoding for Windows console (handles emoji in child processes)
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=timeout_sec,
            env=child_env,
        )
        elapsed = time.time() - t0
        status = "passed" if result.returncode == 0 else "failed"
        icon = "✅" if status == "passed" else "❌"
        print(f"{icon} ({elapsed:.1f}s)")
        return {
            "name": tool["name"],
            "status": status,
            "exit_code": result.returncode,
            "output": (result.stdout or "")[-1000:],
            "errors": (result.stderr or "")[-500:],
            "duration_sec": round(elapsed, 2),
            "phase": phase,
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 5),
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - t0
        print("⏰ (timeout)")
        return {
            "name": tool["name"],
            "status": "timed_out",
            "exit_code": -1,
            "output": f"Timed out after {timeout_sec}s",
            "duration_sec": timeout_sec,
            "phase": phase,
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 5),
        }
    except Exception as e:
        elapsed = time.time() - t0
        print("💥 (error)")
        return {
            "name": tool["name"],
            "status": "error",
            "exit_code": -1,
            "output": str(e)[:500],
            "duration_sec": round(elapsed, 2),
            "phase": phase,
            "critical": tool.get("critical", False),
            "weight": tool.get("weight", 5),
        }


# ── Scoring Engine ────────────────────────────────────────────────────────────


def _compute_certification_score(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the unified certification score from all tool results."""
    total_weight = 0
    weighted_score = 0
    passed_count = 0
    failed_count = 0
    skipped_count = 0
    critical_failures: list[str] = []
    phase_scores: dict[str, dict] = {}

    for r in results:
        weight = r.get("weight", 5)
        if r["status"] == "skipped":
            skipped_count += 1
            continue
        total_weight += weight
        if r["status"] == "passed":
            weighted_score += weight
            passed_count += 1
        else:
            failed_count += 1
            if r.get("critical", False):
                critical_failures.append(r["name"])

        # Per-phase scoring
        phase = r.get("phase", "Other")
        if phase not in phase_scores:
            phase_scores[phase] = {"weight": 0, "score": 0, "passed": 0, "failed": 0}
        ps = phase_scores[phase]
        ps["weight"] += weight
        if r["status"] == "passed":
            ps["score"] += weight
            ps["passed"] += 1
        else:
            ps["failed"] += 1

    overall_pct = (weighted_score / total_weight * 100) if total_weight > 0 else 0

    # Determine grade
    if overall_pct >= 95 and not critical_failures:
        grade = "A+"
        status_text = "CERTIFIED"
    elif overall_pct >= 90 and not critical_failures:
        grade = "A"
        status_text = "CERTIFIED"
    elif overall_pct >= 80 and not critical_failures:
        grade = "B"
        status_text = "CONDITIONAL"
    elif overall_pct >= 70:
        grade = "C"
        status_text = "NOT READY"
    elif overall_pct >= 60:
        grade = "D"
        status_text = "NOT READY"
    else:
        grade = "F"
        status_text = "FAILED"

    # Phase scores as percentages
    phase_summary = {}
    for phase, ps in phase_scores.items():
        phase_pct = (ps["score"] / ps["weight"] * 100) if ps["weight"] > 0 else 0
        phase_summary[phase] = {
            "score": round(phase_pct, 1),
            "passed": ps["passed"],
            "failed": ps["failed"],
        }

    return {
        "overall_score": round(overall_pct, 1),
        "grade": grade,
        "status": status_text,
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "critical_failures": critical_failures,
        "critical_failure_count": len(critical_failures),
        "total_weight": total_weight,
        "weighted_score": weighted_score,
        "phases": phase_summary,
    }


# ── HTML Dashboard Generator ──────────────────────────────────────────────────


def _generate_html_dashboard(
    results: list[dict[str, Any]],
    score: dict[str, Any],
    duration: float,
) -> str:
    """Generate a unified executive HTML dashboard."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    overall = score["overall_score"]
    status = score["status"]
    color = "#4CAF50" if status == "CERTIFIED" else "#FF9800" if status == "CONDITIONAL" else "#f44336"

    # Tool results table
    tool_rows = ""
    for r in results:
        icons = {"passed": "✅", "failed": "❌", "skipped": "⏭️", "not_found": "⚠️", "timed_out": "⏰", "error": "💥"}
        icon = icons.get(r["status"], "❓")
        sev = "🔴 CRITICAL" if r.get("critical") and r["status"] != "passed" else ""
        rcolor = "#4CAF50" if r["status"] == "passed" else "#f44336" if r["status"] == "failed" else "#888"
        tool_rows += f"""
        <tr style="border-left: 4px solid {rcolor};">
            <td>{icon}</td>
            <td><strong>{r['name']}</strong> {sev}</td>
            <td>{r['phase']}</td>
            <td>{r['status'].upper()}</td>
            <td>{r.get('duration_sec', 0):.1f}s</td>
            <td style="font-size:0.85em;color:#666">{r.get('output', '')[:150]}</td>
        </tr>"""

    # Phase scores
    phase_rows = ""
    for phase, ps in sorted(score.get("phases", {}).items()):
        pcolor = "#4CAF50" if ps["score"] >= 90 else "#FF9800" if ps["score"] >= 70 else "#f44336"
        phase_rows += f"""
        <tr>
            <td>{phase}</td>
            <td style="color:{pcolor};font-weight:bold">{ps['score']}%</td>
            <td>{ps['passed']} passed / {ps['failed']} failed</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Full System Certification — OPB v2.57.0</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #f5f7fa; color: #333; }}
  .header {{ background: linear-gradient(135deg, #1a237e 0%, #283593 100%); color: white; padding: 30px; border-radius: 8px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; font-size: 28px; }}
  .header .subtitle {{ opacity: 0.8; margin-top: 5px; }}
  .score-card {{ text-align: center; padding: 25px; border-radius: 8px; margin: 20px 0; }}
  .score-number {{ font-size: 64px; font-weight: 700; }}
  .score-label {{ font-size: 18px; opacity: 0.9; }}
  .grade {{ font-size: 36px; font-weight: 700; margin: 5px 0; }}
  .status {{ display: inline-block; padding: 6px 20px; border-radius: 20px; font-weight: 600; font-size: 16px; }}
  .certified {{ background: #4CAF50; color: white; }}
  .conditional {{ background: #FF9800; color: white; }}
  .failed {{ background: #f44336; color: white; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin: 15px 0; }}
  th {{ background: #1a237e; color: white; padding: 12px 16px; text-align: left; font-weight: 500; }}
  td {{ padding: 10px 16px; border-bottom: 1px solid #e8eaf6; }}
  tr:hover {{ background: #f5f5f5; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
  .summary-card {{ background: white; padding: 20px; border-radius: 8px; text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .summary-card .value {{ font-size: 32px; font-weight: 700; }}
  .summary-card .label {{ color: #666; font-size: 14px; margin-top: 4px; }}
  h2 {{ color: #1a237e; margin-top: 30px; }}
  footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #e0e0e0; color: #999; font-size: 0.85em; text-align: center; }}
</style>
</head>
<body>
<div class="header">
  <h1>🔬 Full System Certification — OPB v2.57.0</h1>
  <div class="subtitle">Comprehensive 13-tool validation pipeline</div>
</div>

<div class="score-card" style="background: linear-gradient(135deg, {color} 0%, {color}dd 100%); color: white;">
  <div class="score-number">{overall}%</div>
  <div class="grade">Grade: {score["grade"]}</div>
  <div class="score-label">{score["status"]}</div>
  <div style="margin-top:10px">
    <span class="status {status.lower().replace(' ', '-')}">{status}</span>
  </div>
</div>

<div class="summary-grid">
  <div class="summary-card">
    <div class="value" style="color:#4CAF50">{score["passed"]}</div>
    <div class="label">Tools Passed</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color:#f44336">{score["failed"]}</div>
    <div class="label">Tools Failed</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color:#FF9800">{score["skipped"]}</div>
    <div class="label">Skipped</div>
  </div>
  <div class="summary-card">
    <div class="value" style="color:#f44336">{score["critical_failure_count"]}</div>
    <div class="label">Critical Failures</div>
  </div>
  <div class="summary-card">
    <div class="value">{duration:.0f}s</div>
    <div class="label">Total Duration</div>
  </div>
  <div class="summary-card">
    <div class="value">{len(_TOOLS)}</div>
    <div class="label">Total Tools</div>
  </div>
</div>

<h2>📊 Phase Scores</h2>
<table>
  <tr><th>Phase</th><th>Score</th><th>Details</th></tr>
  {phase_rows}
</table>

<h2>🔍 Tool Results</h2>
<table>
  <tr><th>Status</th><th>Tool</th><th>Phase</th><th>Result</th><th>Duration</th><th>Summary</th></tr>
  {tool_rows}
</table>

<h2>📋 Executive Summary</h2>
<p>Certification run completed at {timestamp}.</p>
<ul>
  <li><strong>Overall Score:</strong> {overall}% (Grade: {score["grade"]})</li>
  <li><strong>Certification Status:</strong> {status}</li>
  <li><strong>Tools:</strong> {score["passed"]} passed, {score["failed"]} failed, {score["skipped"]} skipped</li>
  <li><strong>Critical Issues:</strong> {score["critical_failure_count"]}</li>
  <li><strong>Duration:</strong> {duration:.0f} seconds</li>
</ul>
{f'<div style="background:#ffebee;padding:15px;border-radius:8px;margin:10px 0"><strong>🚨 Critical Failures:</strong><ul>{"".join(f"<li>{f}</li>" for f in score["critical_failures"])}</ul></div>' if score["critical_failures"] else '<div style="background:#e8f5e9;padding:15px;border-radius:8px;margin:10px 0">✅ No critical failures.</div>'}

<footer>
  Generated by <code>scripts/run_certify.py</code> — OPB Full System Certification v2.57.0
</footer>
</body>
</html>"""
    return html


# ── CLI ────────────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Full System Certification Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fast", action="store_true",
                        help="Skip slow tools (benchmarks, mutation tests)")
    parser.add_argument("--ci", action="store_true",
                        help="CI mode: exit non-zero on any failure or critical failure")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON report to stdout")
    parser.add_argument("--html", default=None,
                        help="Path for HTML dashboard (default: reports/certification_report.html)")
    args = parser.parse_args()

    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    print("=" * 70)
    print("  🔬 FULL SYSTEM CERTIFICATION — OPB v2.57.0")
    print("=" * 70)
    print(f"  Mode: {'FAST (skipping slow tools)' if args.fast else 'FULL'}")
    print(f"  Tools: {len(_TOOLS)} total")
    print()

    # Run all tools
    results = []
    for tool in _TOOLS:
        result = _run_tool(tool, skip_slow=args.fast)
        results.append(result)

    total_duration = time.time() - t_start

    # Compute certification score
    score = _compute_certification_score(results)

    # Print summary
    print(f"\n{'='*70}")
    print("  CERTIFICATION RESULT")
    print(f"{'='*70}")
    print(f"  Score:  {score['overall_score']}%")
    print(f"  Grade:  {score['grade']}")
    print(f"  Status: {score['status']}")
    print(f"  Passed: {score['passed']} | Failed: {score['failed']} | Skipped: {score['skipped']}")
    print(f"  Critical: {score['critical_failure_count']}")
    print(f"  Duration: {total_duration:.0f}s")

    if score["critical_failures"]:
        print("\n  🚨 Critical Failures:")
        for f in score["critical_failures"]:
            print(f"    ❌ {f}")

    # Phase scores
    print("\n  Phase Scores:")
    for phase, ps in sorted(score.get("phases", {}).items()):
        pcolor = "✅" if ps["score"] >= 90 else "⚠️" if ps["score"] >= 70 else "❌"
        print(f"    {pcolor} {phase:<14s} {ps['score']:.0f}%  ({ps['passed']} passed / {ps['failed']} failed)")

    # Generate HTML dashboard
    html_path = args.html or str(_REPORTS_DIR / "certification_report.html")
    html = _generate_html_dashboard(results, score, total_duration)
    Path(html_path).parent.mkdir(parents=True, exist_ok=True)
    Path(html_path).write_text(html, encoding="utf-8")
    print(f"\n  📊 Dashboard: {html_path}")

    # JSON output
    report_json = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "version": "2.57.0",
        "mode": "fast" if args.fast else "full",
        "duration_sec": round(total_duration, 2),
        "score": score,
        "tools": results,
    }
    json_path = _REPORTS_DIR / "certification_report.json"
    json_path.write_text(json.dumps(report_json, indent=2, default=str), encoding="utf-8")
    print(f"  📋 JSON report: {json_path}")

    if args.json:
        print(json.dumps(report_json, indent=2, default=str))

    # CI check
    if args.ci:
        if score["status"] not in ("CERTIFIED", "CONDITIONAL"):
            print(f"\n❌ CI FAILED: Status='{score['status']}' | Score={score['overall_score']}%")
            return 1
        if score["critical_failure_count"] > 0:
            print(f"\n❌ CI FAILED: {score['critical_failure_count']} critical failure(s)")
            return 1
        print(f"\n✅ CI PASSED: Score={score['overall_score']}% | Status={score['status']}")

    print(f"\n{'='*70}")
    return 0 if score["critical_failure_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
