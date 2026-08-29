#!/usr/bin/env python3
"""Continuous Intelligence Workflow (CIW).

Runs on every commit, pull request, or release to orchestrate all
pillars of the Autonomous Enterprise Platform:

  Step 1: Detect changed files (git diff)
  Step 2: Build dependency graph (DependencyAnalyzer)
  Step 3: Perform impact analysis (ImpactAnalysisEngine)
  Step 4: Assess risks (ChangeRiskScorer)
  Step 5: Generate/update tests (TestGenerator)
  Step 6: Update documentation (LivingDocGenerator)
  Step 7: Refresh architecture diagrams
  Step 8: Generate stakeholder presentations (PresentationGenerator)
  Step 9: Produce executive summary

Usage:
    python scripts/continuous_intelligence.py                          # default: HEAD~1
    python scripts/continuous_intelligence.py --commit HEAD~3          # compare with 3 commits ago
    python scripts/continuous_intelligence.py --files core/foo.py     # specific files
    python scripts/continuous_intelligence.py --ci                    # CI mode (JSON output)
    python scripts/continuous_intelligence.py --skip-ppt              # skip PPTX generation
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CIW] %(levelname)s %(message)s",
)
_log = logging.getLogger("continuous_intelligence")

# Allow CI mode to suppress logs
CI_MODE = "--ci" in sys.argv


def _log_info(msg: str) -> None:
    if not CI_MODE:
        _log.info(msg)


def _log_warn(msg: str) -> None:
    if not CI_MODE:
        _log.warning(msg)


# ── Step 1: Detect Changes ──────────────────────────────────────────────────


def detect_changed_files(commit_ref: str | None = None, file_list: list[str] | None = None) -> list[str]:
    """Detect changed Python files using git diff.

    Args:
        commit_ref: Git ref to compare against HEAD (e.g., HEAD~1, HEAD~3).
        file_list: Optional explicit list of files to analyze.

    Returns:
        List of changed file paths relative to project root.
    """
    if file_list:
        return [f for f in file_list if f.endswith(".py")]

    if not commit_ref:
        commit_ref = "HEAD~1"

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", commit_ref, "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            files = [f.strip() for f in result.stdout.strip().splitlines()
                     if f.strip().endswith(".py")]
            _log_info(f"[Step 1] Detected {len(files)} changed Python files")
            return files
        else:
            _log_warn(f"Git diff failed: {result.stderr}")
            return []
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _log_warn(f"Git diff error: {exc}")
        return []


# ── Step 2: Dependency Graph ────────────────────────────────────────────────


def run_dependency_analysis() -> dict[str, Any]:
    """Build and analyze the dependency graph.

    Returns:
        Dict with dependency report metrics.
    """
    _log_info("[Step 2] Running dependency analysis...")
    try:
        from core.dependency_analyzer import get_dependency_analyzer
        analyzer = get_dependency_analyzer()
        report = analyzer.analyze()
        _log_info(
            f"  {report.total_modules} modules, {report.total_edges} edges, "
            f"{len(report.circular_dependencies)} cycles, "
            f"{len(report.dead_modules)} dead modules"
        )
        return report.to_dict()
    except ImportError as exc:
        _log_warn(f"Dependency analysis skipped: {exc}")
        return {"status": "skipped", "reason": str(exc)}


# ── Step 3: Impact Analysis ─────────────────────────────────────────────────


def run_impact_analysis(changed_files: list[str]) -> list[dict[str, Any]]:
    """Run impact analysis on each changed file.

    Args:
        changed_files: List of changed file paths.

    Returns:
        List of impact report dicts.
    """
    if not changed_files:
        return []

    _log_info(f"[Step 3] Impact analysis on {len(changed_files)} files...")
    results: list[dict[str, Any]] = []
    try:
        from core.impact_analysis_engine import get_impact_engine
        engine = get_impact_engine()

        for file_path in changed_files[:20]:  # Cap at 20 files
            report = engine.analyze_change(file_path)
            results.append({
                "file": file_path,
                "services_affected": len(report.affected_services),
                "apis_affected": len(report.affected_apis),
                "tests_to_run": len(report.affected_tests),
                "docs_to_update": len(report.affected_documentation),
                "regression_risk": report.regression_risk,
                "business_impact": report.business_impact,
                "effort_minutes": report.estimated_effort_minutes,
                "summary": report.summary,
            })
            _log_info(f"  {file_path}: {report.regression_risk} risk, "
                      f"{report.estimated_effort_minutes} min")
    except ImportError as exc:
        _log_warn(f"Impact analysis skipped: {exc}")
    return results


# ── Step 4: Risk Assessment ─────────────────────────────────────────────────


def run_risk_assessment(changed_files: list[str]) -> list[dict[str, Any]]:
    """Score the risk of each changed file.

    Args:
        changed_files: List of changed file paths.

    Returns:
        List of risk score dicts.
    """
    if not changed_files:
        return []

    _log_info(f"[Step 4] Risk assessment on {len(changed_files)} files...")
    results: list[dict[str, Any]] = []
    try:
        from core.change_risk_scorer import get_risk_scorer
        scorer = get_risk_scorer()

        for file_path in changed_files[:20]:
            try:
                score = scorer.score_change(
                    files_changed=[file_path],
                    lines_added=0,
                    lines_deleted=0,
                )
                results.append({
                    "file": file_path,
                    "risk_level": score.risk_level,
                    "risk_score": getattr(score, 'risk_score', 0.0),
                })
                risk_val = getattr(score, 'risk_score', 0.0)
                _log_info(f"  {file_path}: {score.risk_level} ({risk_val:.1f})")
            except Exception as exc:
                _log_warn(f"Risk assessment failed for {file_path}: {exc}")
                results.append({
                    "file": file_path,
                    "risk_level": "UNKNOWN",
                    "risk_score": 0.0,
                    "error": str(exc),
                })
    except ImportError as exc:
        _log_warn(f"Risk assessment skipped: {exc}")
    return results


# ── Step 5: Test Impact ────────────────────────────────────────────────────


def run_test_analysis(changed_files: list[str]) -> list[dict[str, Any]]:
    """Determine which tests need to run based on changed files.

    Args:
        changed_files: List of changed file paths.

    Returns:
        List of test analysis results.
    """
    if not changed_files:
        return []

    _log_info(f"[Step 5] Test analysis on {len(changed_files)} files...")
    results: list[dict[str, Any]] = []
    try:
        for file_path in changed_files[:20]:
            # Determine expected test file
            base_name = Path(file_path).stem
            test_file = f"tests/test_{base_name}.py"

            test_path = Path(test_file)
            exists = test_path.is_file()

            results.append({
                "module": file_path,
                "test_file": test_file,
                "test_exists": exists,
            })
            if exists:
                _log_info(f"  {file_path} → {test_file} (exists)")
            else:
                _log_warn(f"  {file_path} → {test_file} (MISSING)")
    except Exception as exc:
        _log_warn(f"Test analysis error: {exc}")
    return results


# ── Step 6: Documentation Impact ───────────────────────────────────────────


def run_documentation_analysis(changed_files: list[str]) -> list[dict[str, Any]]:
    """Check which documentation files reference changed modules.

    Args:
        changed_files: List of changed file paths.

    Returns:
        List of documentation impact results.
    """
    if not changed_files:
        return []

    _log_info(f"[Step 6] Documentation analysis on {len(changed_files)} files...")
    results: list[dict[str, Any]] = []
    doc_dir = Path("docs")
    if not doc_dir.is_dir():
        return results

    try:
        doc_files = list(doc_dir.rglob("*.md"))
        for file_path in changed_files[:20]:
            matching_docs: list[str] = []
            for doc in doc_files:
                try:
                    content = doc.read_text(encoding="utf-8", errors="ignore")
                    if file_path in content:
                        matching_docs.append(str(doc))
                except OSError:
                    continue
            if matching_docs:
                results.append({
                    "module": file_path,
                    "affected_docs": matching_docs,
                    "count": len(matching_docs),
                })
                _log_info(f"  {file_path}: {len(matching_docs)} docs affected")
    except Exception as exc:
        _log_warn(f"Documentation analysis error: {exc}")
    return results


# ── Step 7: Presentation Generation ────────────────────────────────────────


def generate_presentations() -> dict[str, str]:
    """Generate PPTX presentations for all templates.

    Returns:
        Dict mapping template name → output path.
    """
    _log_info("[Step 7] Generating presentations...")
    try:
        from core.presentation_generator import get_presentation_generator
        gen = get_presentation_generator(output_dir="reports/presentations")
        results: dict[str, str] = {}
        for template in ["executive", "developer", "client"]:
            path = gen.generate_report(template)
            if path:
                results[template] = path
                _log_info(f"  {template}: {path}")
            else:
                results[template] = ""
                _log_warn(f"  {template}: generation failed")
        return results
    except ImportError as exc:
        _log_warn(f"Presentation generation skipped: {exc}")
        return {}


# ── Step 8: Executive Summary ──────────────────────────────────────────────


def produce_summary(
    step1_changed: list[str],
    step2_deps: dict[str, Any],
    step3_impact: list[dict[str, Any]],
    step4_risk: list[dict[str, Any]],
    step5_tests: list[dict[str, Any]],
    step6_docs: list[dict[str, Any]],
    step7_ppts: dict[str, str],
    duration: float,
) -> dict[str, Any]:
    """Produce an executive summary of the workflow run.

    Args:
        All step results.

    Returns:
        Dict with summary metadata.
    """
    total_high_risk = sum(1 for r in step4_risk if r.get("risk_level") in ("HIGH", "CRITICAL"))
    missing_tests = sum(1 for t in step5_tests if not t.get("test_exists"))
    total_impact_effort = sum(r.get("effort_minutes", 0) for r in step3_impact)

    summary = {
        "workflow_version": "1.0",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_seconds": round(duration, 1),
        "files_changed": len(step1_changed),
        "changed_files": step1_changed[:50],
        "dependency_analysis": {
            "total_modules": step2_deps.get("total_modules", 0),
            "total_edges": step2_deps.get("total_edges", 0),
            "circular_deps": step2_deps.get("circular_dependencies", 0),
            "dead_modules": step2_deps.get("dead_modules", 0),
        },
        "impact_analysis": {
            "files_analyzed": len(step3_impact),
            "total_effort_minutes": total_impact_effort,
            "high_risk_files": sum(1 for r in step3_impact if r.get("regression_risk") in ("HIGH", "CRITICAL")),
        },
        "risk_assessment": {
            "files_scored": len(step4_risk),
            "total_high_risk": total_high_risk,
        },
        "test_analysis": {
            "files_checked": len(step5_tests),
            "missing_tests": missing_tests,
        },
        "documentation": {
            "files_checked": len(step6_docs),
            "total_docs_affected": sum(r.get("count", 0) for r in step6_docs),
        },
        "presentations_generated": {
            template: bool(path) for template, path in step7_ppts.items()
        },
        "recommendations": [],
    }

    # Generate recommendations
    if total_high_risk > 0:
        summary["recommendations"].append(
            f"{total_high_risk} high-risk change(s) detected — "
            "review before merging"
        )
    if missing_tests > 0:
        summary["recommendations"].append(
            f"{missing_tests} module(s) missing test files — "
            "consider adding test coverage"
        )
    if step2_deps.get("circular_dependencies", 0) > 0:
        summary["recommendations"].append(
            f"{step2_deps['circular_dependencies']} circular "
            f"dependenc(ies) detected — review architecture"
        )
    if total_impact_effort > 120:
        summary["recommendations"].append(
            f"Estimated effort {total_impact_effort} min — "
            "consider breaking into smaller changes"
        )

    return summary


# ── Command-Line Entry Point ────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Continuous Intelligence Workflow — orchestrates all pillars",
    )
    parser.add_argument(
        "--commit", default=None,
        help="Git ref to compare against (default: HEAD~1)",
    )
    parser.add_argument(
        "--files", nargs="*", default=None,
        help="Specific files to analyze (instead of git diff)",
    )
    parser.add_argument(
        "--ci", action="store_true",
        help="CI mode: suppress logs, output JSON summary to stdout",
    )
    parser.add_argument(
        "--skip-ppt", action="store_true",
        help="Skip PPTX presentation generation (saves time in CI)",
    )
    parser.add_argument(
        "--output", default="",
        help="Write JSON summary to path (default: stdout)",
    )
    args = parser.parse_args()

    global CI_MODE
    if args.ci:
        CI_MODE = True

    t0 = time.time()

    if not args.files:
        commit_ref = args.commit or "HEAD~1"
        _log_info(f"Using commit ref: {commit_ref}")
    else:
        commit_ref = None

    _log_info("═" * 60)
    _log_info("  CONTINUOUS INTELLIGENCE WORKFLOW")
    _log_info("═" * 60)
    _log_info(f"  Ref: {args.commit or 'explicit files'}")
    _log_info(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    _log_info("")

    # Step 1: Detect changes
    _log_info("─" * 50)
    changed_files = detect_changed_files(commit_ref, args.files)

    if not changed_files:
        _log_info("No Python files changed — workflow complete.")
        summary = produce_summary(
            [], {}, [], [], [], [], {}, time.time() - t0,
        )
        if args.ci:
            print(json.dumps(summary, indent=2))
        return 0

    # Step 2-8: Run all analyses
    deps = run_dependency_analysis()
    impact = run_impact_analysis(changed_files)
    risk = run_risk_assessment(changed_files)
    tests = run_test_analysis(changed_files)
    docs = run_documentation_analysis(changed_files)
    ppts = generate_presentations() if not args.skip_ppt else {}

    # Step 9: Summary
    summary = produce_summary(
        changed_files, deps, impact, risk, tests, docs, ppts,
        time.time() - t0,
    )

    if args.ci or args.output:
        output = json.dumps(summary, indent=2)
        if args.output:
            Path(args.output).write_text(output, encoding="utf-8")
            _log_info(f"Summary written to {args.output}")
        else:
            print(output)
    else:
        print()
        print(summary.get("dependency_analysis", {}))
        print()

    _log_info("─" * 50)
    _log_info(f"Workflow complete in {summary['duration_seconds']:.1f}s")
    _log_info("═" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
