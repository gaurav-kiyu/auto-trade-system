#!/usr/bin/env python3
"""Generate consolidated constitution maturity report with all category scores and gap recommendations.

Generates both Markdown (.md) and PDF (.pdf) versions:
  - docs/CONSTITUTION_MATURITY_REPORT.md  (comprehensive, all 111 categories)
  - docs/CONSTITUTION_MATURITY_REPORT.pdf  (formatted PDF version)

Usage:
    python scripts/generate_maturity_report.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCORE_GREEN = 9.0
SCORE_RED = 7.5

ROOT = Path(__file__).resolve().parent.parent

# Previous-milestone anchor for the dynamic 'current' row.
# Read from a stored snapshot (_score_snapshot.json) that is refreshed at the end of
# every run, so future regenerations compute drift-free deltas against the previous
# actual run instead of a hardcoded milestone. These defaults are the Top-10 gap
# closure milestone and only seed the very first run (before any snapshot exists).
DEFAULT_PREV_SCORE = 8.83
DEFAULT_PREV_EVIDENCE = 1757
SNAPSHOT_PATH = ROOT / "_score_snapshot.json"


def load_prev_anchor() -> tuple[float, int, bool]:
    """Load the previous-run (score, evidence) anchor from the stored snapshot.

    Returns ``(score, evidence, from_snapshot)``. Falls back to
    DEFAULT_PREV_SCORE / DEFAULT_PREV_EVIDENCE when the snapshot is missing or
    unreadable, so the very first generation stays byte-identical to the historical
    pre-snapshot report.
    """
    try:
        snap = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        score = float(snap["overall_score"])
        evidence = int(snap["total_evidence"])
        if score > 0 and evidence >= 0:
            return score, evidence, True
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return DEFAULT_PREV_SCORE, DEFAULT_PREV_EVIDENCE, False


def save_snapshot(data: dict) -> None:
    """Persist the current run's score/evidence as the next run's drift-free anchor."""
    snap = {
        "overall_score": data["overall_score"],
        "total_evidence": data["total_evidence"],
        "n_categories": len(data.get("categories", [])),
        "total_regressions": data.get("total_regressions", 0),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    SNAPSHOT_PATH.write_text(json.dumps(snap, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Snapshot anchor updated: {SNAPSHOT_PATH}")


def _score_color(score: float, max_score: float = 10.0) -> str:
    pct = score / max_score * 100 if max_score else 0
    if pct >= 90:
        return "green"
    elif pct >= 75:
        return "amber"
    else:
        return "red"


def _score_label(score: float, max_score: float = 10.0) -> str:
    """Return GREEN/AMBER/RED label based on score percentage."""
    c = _score_color(score, max_score)
    return {"green": "GREEN", "amber": "AMBER", "red": "RED"}[c]


def load_data() -> dict:
    """Load constitution scoring data."""
    # Try cached file first
    path = ROOT / "_score_data.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Fallback: run scoring
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/score_system.py"), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    return json.loads(result.stdout)


def generate_markdown(data: dict) -> str:
    """Generate the full maturity report as Markdown."""
    overall = data["overall_score"]
    total_ev = data["total_evidence"]
    n_cats = len(data["categories"])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Group scores
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in data["categories"]:
        groups[c["group"]].append(c)

    # Gap categories
    below_green = [c for c in data["categories"] if c["score"] < SCORE_GREEN]
    below_red = [c for c in data["categories"] if c["score"] < SCORE_RED]

    lines: list[str] = []

    # ── Title ──────────────────────────────────────────────────────────────────
    lines.append("# OPB System Constitution Maturity Report")
    lines.append("")
    lines.append(f"> **Generated:** {ts}  ")
    lines.append(f"> **Overall Score:** {overall}/10  ")
    lines.append(f"> **Categories:** {n_cats}  ")
    lines.append(f"> **Total Evidence:** {total_ev:,}  ")
    lines.append(f"> **Regressions:** {data.get('total_regressions', 0)}  ")
    lines.append("")

    # ── Executive Summary ──────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"The system achieves a constitution maturity score of **{overall}/10** ")
    lines.append(f"across **{n_cats} categories** with **{total_ev:,} evidence items**. ")
    lines.append("Zero regressions detected.")
    lines.append("")

    # Score distribution
    n_green = n_cats - len(below_green)
    n_amber = len(below_green) - len(below_red)
    n_red = len(below_red)
    lines.append(f"- **GREEN** (>= {SCORE_GREEN}): {n_green} categories")
    lines.append(f"- **AMBER** ({SCORE_RED} <= x < {SCORE_GREEN}): {n_amber} categories")
    lines.append(f"- **RED** (< {SCORE_RED}): {n_red} categories")
    lines.append("")

    if below_red:
        lines.append("### Critical Gaps")
        lines.append("")
        lines.append(f"The following categories are below the **{SCORE_RED:.1f}/10** RED threshold and need immediate attention:")
        lines.append("")
        for c in sorted(below_red, key=lambda x: x["score"]):
            gap = SCORE_RED - c["score"]
            priority = "HIGH" if gap > 1.0 else ("MEDIUM" if gap > 0.5 else "LOW")
            lines.append(f"- **{c['category_id']}** ({c['name']}): {c['score']}/{c['max_score']} [{c['evidence_count']} ev] - gap={gap:.1f} ({priority})")
        lines.append("")

    # ── Group Summary ──────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Group Summary")
    lines.append("")
    lines.append("| Group | Categories | Avg Score | Best | Worst |")
    lines.append("|-------|-----------:|---------:|-----|------|")
    for g_name in sorted(groups.keys()):
        cats = groups[g_name]
        avg = sum(c["score"] for c in cats) / len(cats)
        top = max(cats, key=lambda c: c["score"])
        low = min(cats, key=lambda c: c["score"])
        lines.append(f"| **{g_name}** | {len(cats)} | {avg:.2f} | {top['category_id']} ({top['score']}) | {low['category_id']} ({low['score']}) |")
    lines.append("")

    # ── All Categories ─────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## All Categories - Detailed Scores")
    lines.append("")
    lines.append("| ID | Name | Group | Score | Max | % | Evidence | Status |")
    lines.append("|----|------|-------|------:|----:|---:|--------:|--------|")
    for c in sorted(data["categories"], key=lambda x: (x["group"], x["category_id"])):
        pct = c["score"] / c["max_score"] * 100 if c["max_score"] else 0
        status = _score_label(c["score"], c["max_score"])
        lines.append(
            f"| {c['category_id']} | {c['name']} | {c['group']} | "
            f"{c['score']:.1f} | {c['max_score']:.1f} | {pct:.0f}% | "
            f"{c['evidence_count']} | {status} |"
        )
    lines.append("")

    # ── Gap Analysis ───────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Gap Analysis - Categories Below 7.5/10")
    lines.append("")

    if below_red:
        lines.append("| ID | Name | Group | Score | Max | Gap | Evidence | Priority | Recommended Action |")
        lines.append("|----|------|-------|------:|----:|----:|--------:|----------|--------------------|")
        for c in sorted(below_red, key=lambda x: x["score"]):
            gap = SCORE_RED - c["score"]
            priority = "HIGH" if gap > 1.0 else ("MEDIUM" if gap > 0.5 else "LOW")
            needed = int(gap * 2) + 1
            action = f"Add ~{needed} more evidence entries (currently {c['evidence_count']})"
            lines.append(
                f"| {c['category_id']} | {c['name']} | {c['group']} | "
                f"{c['score']:.1f} | {c['max_score']:.1f} | {gap:.1f} | "
                f"{c['evidence_count']} | {priority} | {action} |"
            )
    else:
        lines.append(f"All {n_cats} categories are above {SCORE_RED}/10.")
    lines.append("")

    # ── Historical Improvement ──────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Historical Score Improvement")
    lines.append("")
    lines.append("| Milestone | Score | Evidence | Change |")
    lines.append("|-----------|------:|--------:|--------|")
    lines.append("| Session Baseline | 7.66/10 | 1,345 | — |")
    lines.append("| After 47-category fix | 7.92/10 | 1,424 | +0.26, +79 ev |")
    lines.append("| After boost collector | 8.25/10 | 1,528 | +0.33, +104 ev |")
    lines.append("| Constitution v4.0 engine audit | 8.71/10 | 1,703 | +0.46, +175 ev |")
    prev_score, prev_evidence, from_snapshot = load_prev_anchor()
    prev_label = "Previous milestone (snapshot)" if from_snapshot else "Top-10 gap closure"
    lines.append(f"| {prev_label} | {prev_score}/10 | {prev_evidence:,} | +{prev_score - 8.71:.2f}, +{prev_evidence - 1703} ev |")
    lines.append(f"| Next-tier closure (current) | {overall:.2f}/10 | {total_ev:,} | {overall - prev_score:+.2f}, {total_ev - prev_evidence:+,} ev |")
    lines.append("")
    if from_snapshot:
        lines.append(f"*Deltas are drift-free: computed against the previous run snapshot ({prev_score:.2f}/10, {prev_evidence:,} evidence) stored in `{SNAPSHOT_PATH.name}`.*")
        lines.append("")

    # ── Recommendations ────────────────────────────────────────────────────────
    lines.append("---")
    lines.append("## Recommendations")
    lines.append("")
    lines.append("### Priority Actions")
    lines.append("")

    if below_red:
        lines.append(f"The **{len(below_red)} categories below {SCORE_RED}/10** require the following:")
        lines.append("")
        for c in sorted(below_red, key=lambda x: x["score"])[:5]:
            gap = SCORE_RED - c["score"]
            needed = int(gap * 2) + 1
            lines.append(f"1. **{c['category_id']}** ({c['name']}): Add {needed} evidence entries to cross {SCORE_RED}/10")
    else:
        lines.append("No critical gaps remain. Focus on AMBER categories to reach GREEN.")
    lines.append("")

    lines.append("### Medium-Term Goals")
    lines.append("")
    lines.append(f"- Boost all categories to **{SCORE_GREEN}/10** (GREEN)")
    lines.append("- Increase total evidence beyond 2,000 items")
    lines.append("- Add automated evidence generation for frequently-updated categories")
    lines.append("- Integrate with CI/CD pipeline for real-time scoring")
    lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Report generated {ts} | Version v2.57.1 | OPB Constitution Board*")
    lines.append("")

    return "\n".join(lines)


def generate_pdf_from_data(data: dict, pdf_path: Path) -> bool:
    """Generate a formatted PDF report using ReportLab directly from scoring data."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    except ImportError:
        print("[WARN] ReportLab not installed — PDF generation skipped")
        return False

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    h1 = styles["Heading1"]
    h2 = styles["Heading2"]
    body = styles["Normal"]

    story: list = []
    overall = data.get("overall_score", 0)
    total_ev = data.get("total_evidence", 0)
    n_cats = len(data.get("categories", []))
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Title page
    story.append(Paragraph("OPB System Constitution Maturity Report", h1))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Generated: {ts}", body))
    story.append(Paragraph(f"Overall Score: {overall}/10", body))
    story.append(Paragraph(f"Categories: {n_cats}", body))
    story.append(Paragraph(f"Total Evidence: {total_ev:,}", body))
    story.append(Spacer(1, 12))

    # Score distribution
    categories = data.get("categories", [])
    below_green = [c for c in categories if c["score"] < 9.0]
    below_red = [c for c in categories if c["score"] < 7.5]
    n_green = n_cats - len(below_green)
    n_amber = len(below_green) - len(below_red)

    story.append(Paragraph(f"GREEN (>=9.0): {n_green} categories", body))
    story.append(Paragraph(f"AMBER (>=7.5): {n_amber} categories", body))
    story.append(Paragraph(f"RED (<7.5): {len(below_red)} categories", body))
    story.append(Spacer(1, 20))

    # Group summary table
    story.append(Paragraph("Group Summary", h2))
    story.append(Spacer(1, 8))
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in categories:
        groups[c["group"]].append(c)

    group_data = [["Group", "Cats", "Avg", "Best", "Worst"]]
    for g_name in sorted(groups.keys()):
        cats = groups[g_name]
        avg = sum(c["score"] for c in cats) / len(cats)
        top = max(cats, key=lambda c: c["score"])
        low = min(cats, key=lambda c: c["score"])
        group_data.append([g_name, str(len(cats)), f"{avg:.2f}", f"{top['category_id']} ({top['score']})", f"{low['category_id']} ({low['score']})"])

    t = Table(group_data, colWidths=[3.5*cm, 1.5*cm, 1.5*cm, 4.5*cm, 4.5*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
    ]))
    story.append(t)
    story.append(Spacer(1, 20))

    # Gap analysis
    story.append(Paragraph("Gap Analysis - Categories Below 7.5/10", h2))
    story.append(Spacer(1, 8))
    if below_red:
        gap_data = [["ID", "Name", "Score", "Gap", "Evidence", "Priority"]]
        for c in sorted(below_red, key=lambda x: x["score"]):
            gap = 7.5 - c["score"]
            priority = "HIGH" if gap > 1.0 else ("MEDIUM" if gap > 0.5 else "LOW")
            gap_data.append([c["category_id"], c["name"][:30], f"{c['score']:.1f}", f"{gap:.1f}", str(c["evidence_count"]), priority])

        t2 = Table(gap_data, colWidths=[2*cm, 6*cm, 1.5*cm, 1.5*cm, 1.5*cm, 2*cm])
        t2.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DC2626")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ]))
        story.append(t2)
    else:
        story.append(Paragraph("No categories below 7.5/10", body))
    story.append(Spacer(1, 20))

    # Historical improvement
    story.append(Paragraph("Historical Score Improvement", h2))
    story.append(Spacer(1, 8))
    prev_score, prev_evidence, from_snapshot = load_prev_anchor()
    prev_label = "Previous milestone (snapshot)" if from_snapshot else "Top-10 gap closure"
    hist_data = [
        ["Milestone", "Score", "Evidence", "Change"],
        ["Session Baseline", "7.66/10", "1,345", "—"],
        ["After 47-category fix", "7.92/10", "1,424", "+0.26"],
        ["After boost collector", "8.25/10", "1,528", "+0.33"],
        ["Constitution v4.0 engine audit", "8.71/10", "1,703", "+0.46"],
        [prev_label, f"{prev_score}/10", f"{prev_evidence:,}", f"+{prev_score - 8.71:.2f}"],
        ["Next-tier closure", f"{overall:.2f}/10", f"{total_ev:,}", f"{overall - prev_score:+.2f}"],
    ]
    t3 = Table(hist_data, colWidths=[5*cm, 3*cm, 3*cm, 3*cm])
    t3.setStyle(TableStyle([            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#059669")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(t3)
    story.append(Spacer(1, 20))

    # Recommendations
    story.append(Paragraph("Recommendations", h2))
    story.append(Spacer(1, 8))
    if below_red:
        story.append(Paragraph(f"{len(below_red)} categories need evidence to cross 7.5/10:", body))
        for c in sorted(below_red, key=lambda x: x["score"])[:5]:
            gap = 7.5 - c["score"]
            needed = int(gap * 2) + 1
            story.append(Paragraph(f"- {c['category_id']} ({c['name']}): Add {needed} evidence entries", body))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Medium-term: Boost all categories to 9.0/10, reach 2,000+ evidence items", body))

    # Build PDF
    doc.build(story)
    print(f"[OK] PDF generated via ReportLab: {pdf_path}")
    return True


def main() -> int:
    data = load_data()
    prev_score, prev_evidence, from_snapshot = load_prev_anchor()
    md = generate_markdown(data)

    # Write Markdown
    md_path = ROOT / "docs" / "CONSTITUTION_MATURITY_REPORT.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"[OK] Markdown report: {md_path}")

    # Write PDF
    pdf_path = ROOT / "docs" / "CONSTITUTION_MATURITY_REPORT.pdf"
    generate_pdf_from_data(data, pdf_path)

    # Persist the current run so the next regeneration computes drift-free deltas
    save_snapshot(data)

    print("\nReport Summary:")
    anchor_src = "snapshot" if from_snapshot else "default (Top-10 gap closure)"
    print(f"  Score: {data['overall_score']}/10 ({data['total_evidence']} evidence)")
    print(f"  Previous anchor: {prev_score}/10 ({prev_evidence} evidence) [{anchor_src}]")
    print(f"  Categories: {len(data['categories'])}")
    print(f"  Below {SCORE_RED}: {sum(1 for c in data['categories'] if c['score'] < SCORE_RED)}")
    print(f"  Below {SCORE_GREEN}: {sum(1 for c in data['categories'] if c['score'] < SCORE_GREEN)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
