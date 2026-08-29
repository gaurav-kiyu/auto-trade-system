#!/usr/bin/env python3
"""Constitution v4.0 Weekly Health Report Generator.

Produces a comprehensive health report including:
  - Overall constitution health score and trending
  - Top 10 and bottom 10 categories by score
  - Per-domain breakdown (engineering principles, architecture, etc.)
  - Open regressions and evidence gaps
  - Recommendations for improvement

Usage:
    python scripts/generate_constitution_report.py              # Text report
    python scripts/generate_constitution_report.py --json       # JSON output
    python scripts/generate_constitution_report.py --pptx      # PPTX presentation
    python scripts/generate_constitution_report.py --days 30   # 30-day history
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add project root to path
_script_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_script_dir, ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
_log = logging.getLogger("constitution_report")

REPORTS_DIR = Path(_project_root) / "reports"


def get_constitution_health() -> dict[str, Any]:
    """Get the current constitution health check."""
    from core.constitution import get_validator
    validator = get_validator()
    return validator.comprehensive_health_check()


def get_historical_scores(days: int = 30) -> list[dict[str, Any]]:
    """Get historical constitution scores from continuous intelligence history.

    Args:
        days: Number of days of history to retrieve.

    Returns:
        List of historical score snapshots.
    """
    history_path = Path(_project_root) / "json/continuous_intelligence_history.jsonl"
    if not history_path.exists():
        return []

    cutoff = time.time() - (days * 86400)
    scores: list[dict[str, Any]] = []

    try:
        with open(history_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    ts = entry.get("timestamp", "")
                    if isinstance(ts, str):
                        try:
                            dt = datetime.fromisoformat(ts)
                            if dt.timestamp() < cutoff:
                                continue
                        except (ValueError, TypeError, OverflowError):
                            pass
                    v4_score = entry.get("v4_overall_score", None)
                    if v4_score is not None and v4_score >= 0:
                        scores.append({
                            "timestamp": ts,
                            "v4_overall_score": v4_score,
                            "scorecard_pct": entry.get("scorecard_pct", 0),
                            "modules_passed": entry.get("modules_passed", 0),
                            "modules_failed": entry.get("modules_failed", 0),
                        })
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
    except (OSError, ValueError) as exc:
        _log.warning("Failed to read history: %s", exc)

    return scores[-100:]  # Cap at most recent 100 entries


def generate_health_report(days: int = 30) -> dict[str, Any]:
    """Generate a comprehensive constitution health report.

    Args:
        days: Number of days of historical data to include.

    Returns:
        Dict with full report data.
    """
    health = get_constitution_health()
    history = get_historical_scores(days)

    # Compute trending
    trending: dict[str, Any] = {"direction": "stable", "delta_7d": 0.0, "delta_30d": 0.0, "scores": history}
    if len(history) >= 2:
        recent = history[-1]["v4_overall_score"]
        earliest = history[0]["v4_overall_score"]
        trending["delta_overall"] = round(recent - earliest, 2)
        if trending["delta_overall"] > 0.5:
            trending["direction"] = "improving"
        elif trending["delta_overall"] < -0.5:
            trending["direction"] = "declining"
        else:
            trending["direction"] = "stable"

        # 7-day delta if enough data
        seven_days_ago = history[-(min(7, len(history)))]
        trending["delta_7d"] = round(recent - seven_days_ago["v4_overall_score"], 2)
        thirty_days_ago = history[0]
        trending["delta_30d"] = round(recent - thirty_days_ago["v4_overall_score"], 2)

    # Build category analysis from validator's generate_report
    from core.constitution import get_validator
    validator = get_validator()
    score_report = validator.generate_report()
    report_dict = score_report.to_dict()
    categories = report_dict.get("categories", {})

    sorted_categories = sorted(
        categories.items(),
        key=lambda x: x[1].get("score", 0) if isinstance(x[1], dict) else 0,
        reverse=True,
    )
    top_categories = sorted_categories[:10]
    bottom_categories = sorted_categories[-10:] if len(sorted_categories) >= 10 else sorted_categories

    # Domain breakdown
    domain_breakdown: dict[str, dict[str, Any]] = {}
    for prefix, label in [
        ("LAY", "Enterprise Layers"),
        ("QGT", "Quality Gates"),
        ("PRN", "Engineering Principles"),
        ("AST", "Architecture Standards"),
        ("SGS", "Security & Governance"),
        ("PLS", "Platform Engineering"),
        ("SRE", "SRE/Reliability"),
        ("ARCH", "Architecture (Classic)"),
        ("SEC", "Security (Classic)"),
        ("RSK", "Risk (Classic)"),
        ("EXE", "Execution (Classic)"),
        ("TST", "Testing (Classic)"),
        ("OBS", "Observability (Classic)"),
        ("GOV", "Governance (Classic)"),
        ("DR", "Disaster Recovery (Classic)"),
    ]:
        domain_cats = {
            cid: cat for cid, cat in categories.items()
            if isinstance(cat, dict) and cid.startswith(prefix)
        }
        if domain_cats:
            scores_list = [c.get("score", 0) for c in domain_cats.values()]
            max_list = [c.get("max_score", 10) for c in domain_cats.values()]
            avg_score = sum(scores_list) / max(len(scores_list), 1)
            avg_max = sum(max_list) / max(len(max_list), 1)
            pct = (avg_score / avg_max * 100) if avg_max > 0 else 0
            domain_breakdown[label] = {
                "count": len(domain_cats),
                "avg_score": round(avg_score, 2),
                "max_score": round(avg_max, 2),
                "pct": round(pct, 1),
            }

    # Generate recommendations
    recommendations: list[str] = []
    for cid, cat in bottom_categories:
        if isinstance(cat, dict):
            score = cat.get("score", 0)
            max_score = cat.get("max_score", 10)
            pct = (score / max_score * 100) if max_score > 0 else 0
            if pct < 50:
                recommendations.append(
                    f"IMPROVE {cid} ({cat.get('name', '')}): score {score:.1f}/{max_score:.1f} "
                    f"({pct:.0f}%) — add more evidence"
                )
            elif pct < 70:
                recommendations.append(
                    f"MONITOR {cid} ({cat.get('name', '')}): score {score:.1f}/{max_score:.1f} "
                    f"({pct:.0f}%) — consider additional coverage"
                )

    if health.get("open_regressions", 0) > 0:
        recommendations.append(
            f"CLEAR regressions: {health['open_regressions']} open regression(s) "
            f"affecting constitution score"
        )

    if not recommendations:
        recommendations.append("All categories healthy — no improvements needed")

    report_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "version": health.get("version", "unknown"),
        "overall_score": health.get("overall_score", 0.0),
        "total_categories": health.get("total_categories", 0),
        "total_evidence": health.get("total_evidence", 0),
        "open_regressions": health.get("open_regressions", 0),
        "max_possible": health.get("max_possible", 10.0),
        "trending": trending,
        "top_categories": [
            {"id": cid, "name": cat.get("name", ""), "score": round(cat.get("score", 0), 2),
             "max_score": cat.get("max_score", 10), "evidence": len(cat.get("evidence", []))}
            for cid, cat in top_categories if isinstance(cat, dict)
        ],
        "bottom_categories": [
            {"id": cid, "name": cat.get("name", ""), "score": round(cat.get("score", 0), 2),
             "max_score": cat.get("max_score", 10), "evidence": len(cat.get("evidence", [])),
             "regressions": cat.get("regressions", [])}
            for cid, cat in bottom_categories if isinstance(cat, dict)
        ],
        "domain_breakdown": domain_breakdown,
        "recommendations": recommendations,
    }

    return report_data


def format_text_report(report: dict[str, Any]) -> str:
    """Format the report as human-readable text."""
    lines = []
    lines.append("=" * 70)
    lines.append("  CONSTITUTION v4.0 — WEEKLY HEALTH REPORT")
    lines.append("=" * 70)
    lines.append(f"  Generated: {report['generated_at'][:19]}")
    lines.append(f"  Version  : {report['version']}")
    lines.append("")
    lines.append(f"  Overall Score : {report['overall_score']:.2f} / {report['max_possible']:.1f}")
    lines.append(f"  Total Categories : {report['total_categories']}")
    lines.append(f"  Total Evidence   : {report['total_evidence']}")
    lines.append(f"  Open Regressions : {report['open_regressions']}")
    lines.append("")

    # Trending
    t = report["trending"]
    lines.append(f"  Trending : {t['direction'].upper()} (Δ7d: {t['delta_7d']:+.2f}, Δ30d: {t['delta_30d']:+.2f})")
    lines.append("")

    # Domain breakdown
    lines.append("── Domain Breakdown ─────────────────────────────────────────")
    for domain, data in sorted(report["domain_breakdown"].items()):
        bar_len = int(data["pct"] / 5)
        bar = "#" * bar_len + "." * (20 - bar_len)
        lines.append(f"  {domain:30s}  {bar}  {data['pct']:5.1f}%  ({data['avg_score']:.1f}/{data['max_score']:.1f})")
    lines.append("")

    # Top categories
    lines.append("── Top 10 Categories ───────────────────────────────────────")
    for i, cat in enumerate(report.get("top_categories", []), 1):
        pct = (cat["score"] / cat["max_score"] * 100) if cat["max_score"] > 0 else 0
        lines.append(f"  {i:2d}. {cat['id']:8s}  {cat['name']:30s}  {cat['score']:5.2f}/{cat['max_score']:.1f}  ({pct:.0f}%)  [{cat['evidence']} evidence]")
    lines.append("")

    # Bottom categories
    lines.append("── Bottom 10 Categories ────────────────────────────────────")
    for i, cat in enumerate(report.get("bottom_categories", []), 1):
        pct = (cat["score"] / cat["max_score"] * 100) if cat["max_score"] > 0 else 0
        reg_str = f"  REGRESSIONS: {len(cat['regressions'])}" if cat.get("regressions") else ""
        lines.append(f"  {i:2d}. {cat['id']:8s}  {cat['name']:30s}  {cat['score']:5.2f}/{cat['max_score']:.1f}  ({pct:.0f}%){reg_str}")
    lines.append("")

    # Recommendations
    lines.append("── Recommendations ─────────────────────────────────────────")
    for i, rec in enumerate(report.get("recommendations", []), 1):
        lines.append(f"  {i}. {rec}")
    lines.append("")
    lines.append("=" * 70)
    return "\n".join(lines)


def generate_pptx_report(report: dict[str, Any]) -> str:
    """Generate a PPTX presentation from the health report data.

    Returns:
        Path to the generated PPTX file, or empty string on failure.
    """
    try:
        from core.presentation_generator import get_presentation_generator
        gen = get_presentation_generator()
        data = {
            "version": f"v{report['version']}",
            "date": report["generated_at"][:10],
            "score": f"{report['overall_score']:.2f}/{report['max_possible']:.1f}",
            "title": "Constitution v4.0 Weekly Health Report",
            "kpis": {
                "Overall Score": report["overall_score"],
                "Total Categories": report["total_categories"],
                "Evidence Items": report["total_evidence"],
                "Open Regressions": report["open_regressions"],
            },
            "strengths": [
                f"Score: {report['overall_score']:.2f}/10 — Trending: {report['trending']['direction'].upper()}",
                f"Categories: {report['total_categories']} total across 15 v4.0 domains",
                f"Evidence: {report['total_evidence']} items registered",
            ],
            "risk_items": [
                rec for rec in report.get("recommendations", [])
            ],
        }
        path = gen.generate("executive", data)
        return str(path) if path else ""
    except ImportError:
        _log.warning("PresentationGenerator not available — skipping PPTX")
        return ""
    except Exception as exc:
        _log.warning("PPPTX generation failed: %s", exc)
        return ""


def save_report(report: dict[str, Any], fmt: str = "json") -> str:
    """Save report to disk.

    Args:
        report: Report data dict.
        fmt: Output format ("json", "txt", "pptx").

    Returns:
        Path to saved file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if fmt == "json":
        path = REPORTS_DIR / f"constitution_health_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
    elif fmt == "txt":
        path = REPORTS_DIR / f"constitution_health_{timestamp}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(format_text_report(report))
    elif fmt == "pptx":
        path_str = generate_pptx_report(report)
        path = path_str if path_str else ""
    else:
        return ""

    return str(path) if path else ""


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Constitution v4.0 Weekly Health Report Generator",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--pptx", action="store_true", help="Generate PPTX presentation")
    parser.add_argument("--days", type=int, default=30, help="Days of history (default: 30)")
    parser.add_argument("--save", action="store_true", help="Save report to disk")
    parser.add_argument("--quiet", action="store_true", help="Suppress output")
    args = parser.parse_args()

    report = generate_health_report(days=args.days)

    if args.save:
        saved_paths = []
        if args.json or args.pptx:
            if args.json:
                p = save_report(report, "json")
                if p:
                    saved_paths.append(p)
            if args.pptx:
                p = save_report(report, "pptx")
                if p:
                    saved_paths.append(p)
        else:
            # Default: save as text
            p = save_report(report, "txt")
            if p:
                saved_paths.append(p)
        if saved_paths:
            print(f"Report saved: {', '.join(saved_paths)}")

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    elif not args.quiet:
        print(format_text_report(report))


if __name__ == "__main__":
    _cli()
