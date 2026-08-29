#!/usr/bin/env python3
"""Generate consolidated PDF report with constitution scores + PR audit + gap analysis.

Usage:
    python scripts/generate_consolidated_report.py
    python scripts/generate_consolidated_report.py --output docs/STAKEHOLDER_REPORT.pdf

Requires:
    reportlab==4.5.0 (installed)
    json data from scripts/score_system.py --json and scripts/run_pr_audit.py --json
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── ReportLab imports ───────────────────────────────────────────────────────
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Color palette ───────────────────────────────────────────────────────────
DARK_BLUE = HexColor("#002B5B")
MED_BLUE = HexColor("#006DAA")
LIGHT_BLUE = HexColor("#58A6FF")
GREEN = HexColor("#00A86B")
RED = HexColor("#E74C3C")
ORANGE = HexColor("#F39C12")
GREY = HexColor("#8B949E")
LIGHT_GREY = HexColor("#F0F4F8")
DARK_GREY = HexColor("#586069")
WHITE = HexColor("#FFFFFF")
BLACK = HexColor("#161B22")

# Score thresholds
THRESHOLD_GREEN = 9.0
THRESHOLD_AMBER = 8.0
THRESHOLD_RED = 7.5


def _score_color(score: float) -> Color:
    if score >= THRESHOLD_GREEN:
        return GREEN
    elif score >= THRESHOLD_AMBER:
        return ORANGE
    else:
        return RED


def _build_styles():
    styles = getSampleStyleSheet()
    s = {}

    s["title"] = ParagraphStyle(
        "ReportTitle", parent=styles["Title"],
        fontSize=24, textColor=DARK_BLUE, spaceAfter=4,
        alignment=TA_CENTER,
    )
    s["subtitle"] = ParagraphStyle(
        "ReportSubtitle", parent=styles["Normal"],
        fontSize=13, textColor=DARK_GREY, spaceAfter=16,
        alignment=TA_CENTER,
    )
    s["h1"] = ParagraphStyle(
        "H1", parent=styles["Heading1"],
        fontSize=16, textColor=DARK_BLUE,
        spaceBefore=14, spaceAfter=6,
    )
    s["h2"] = ParagraphStyle(
        "H2", parent=styles["Heading2"],
        fontSize=12, textColor=MED_BLUE,
        spaceBefore=10, spaceAfter=4,
    )
    s["body"] = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=9, leading=13, spaceAfter=4,
    )
    s["small"] = ParagraphStyle(
        "Small", parent=styles["Normal"],
        fontSize=7.5, leading=10, spaceAfter=2,
        textColor=DARK_GREY,
    )
    s["stat_value"] = ParagraphStyle(
        "StatValue", parent=styles["Normal"],
        fontSize=18, leading=22, textColor=DARK_BLUE,
        alignment=TA_CENTER,
    )
    s["stat_label"] = ParagraphStyle(
        "StatLabel", parent=styles["Normal"],
        fontSize=8, textColor=DARK_GREY,
        alignment=TA_CENTER,
    )
    s["category_name"] = ParagraphStyle(
        "CatName", parent=styles["Normal"],
        fontSize=8, leading=10,
    )
    s["category_score"] = ParagraphStyle(
        "CatScore", parent=styles["Normal"],
        fontSize=9, leading=11, alignment=TA_CENTER,
    )
    s["footer"] = ParagraphStyle(
        "Footer", parent=styles["Normal"],
        fontSize=7, textColor=DARK_GREY,
        alignment=TA_CENTER,
    )
    return s


def _make_stat_card(s, label: str, value: str, color: Color = DARK_BLUE):
    """Return a small table used as a stat card."""
    tbl = Table(
        [
            [Paragraph(value, ParagraphStyle("sv", fontSize=16, leading=20, textColor=color, alignment=TA_CENTER))],
            [Paragraph(label, ParagraphStyle("sl", fontSize=7.5, leading=9, textColor=DARK_GREY, alignment=TA_CENTER))],
        ],
        colWidths=[None],
    )
    tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREY),
    ]))
    return tbl


def load_score_data() -> dict:
    path = Path("_score_data.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    # Fallback: run the scoring
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/score_system.py", "--json"],
        capture_output=True, text=True, timeout=60,
    )
    return json.loads(result.stdout)


def load_pr_data() -> dict:
    path = Path("_pr_data.json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/run_pr_audit.py", "--json"],
        capture_output=True, text=True, timeout=120,
    )
    return json.loads(result.stdout)


def load_prev_anchor() -> dict:
    """Load the previous-milestone anchor from the stored snapshot.

    Returns an empty dict when the snapshot is absent or invalid so the
    report degrades gracefully to a historical-narrative-only table.
    """
    path = Path("_score_snapshot.json")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    prev_score = data.get("overall_score")
    prev_evidence = data.get("total_evidence")
    if prev_score is None or prev_evidence is None:
        return {}
    return {"score": float(prev_score), "evidence": int(prev_evidence)}


def _fmt_delta(score: float, evidence: int) -> str:
    """Render a sign-aware delta for the current vs previous milestone."""
    ds = f"{score:+.2f}"
    if evidence >= 0:
        de = f"+{evidence:,} ev"
    else:
        de = f"{evidence:,} ev"
    return f"{ds} / {de}"


def generate_report(output_path: str = "docs/CONSOLIDATED_STAKEHOLDER_REPORT.pdf") -> str:
    """Generate the consolidated PDF report."""
    s = _build_styles()
    score_data = load_score_data()
    pr_data = load_pr_data()

    overall_score = score_data["overall_score"]
    total_evidence = score_data["total_evidence"]
    n_categories = len(score_data["categories"])
    pr_score = pr_data["score"]
    pr_passed = pr_data["passed_checks"]
    pr_total = pr_data["total_checks"]

    # Group scores
    groups: dict[str, list[dict]] = defaultdict(list)
    for c in score_data["categories"]:
        groups[c["group"]].append(c)

    # Categories below thresholds
    below_green = [c for c in score_data["categories"] if c["score"] < THRESHOLD_GREEN]
    below_amber = [c for c in score_data["categories"] if c["score"] < THRESHOLD_AMBER]
    below_red = [c for c in score_data["categories"] if c["score"] < THRESHOLD_RED]

    # Build PDF
    os.makedirs(Path(output_path).parent, exist_ok=True)
    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        leftMargin=1.6 * cm, rightMargin=1.6 * cm,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
        title="OPB System - Consolidated Stakeholder Report",
        author="OPB Constitution Board",
    )

    story = []

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 1: EXECUTIVE SUMMARY
    # ═══════════════════════════════════════════════════════════════════════
    story.append(Paragraph("OPB Index Options Trading System", s["title"]))
    story.append(Paragraph("CONSOLIDATED CONSTITUTION & STAKEHOLDER REPORT", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=MED_BLUE, spaceAfter=10))
    story.append(Paragraph(
        f"Generated: {datetime.now(timezone.utc).strftime('%d %B %Y %H:%M UTC')}",
        s["small"],
    ))
    story.append(Spacer(1, 8))

    # Executive summary
    story.append(Paragraph("Executive Summary", s["h1"]))
    story.append(Paragraph(
        "This report consolidates the system's constitution scoring (engineering maturity) "
        "and PR audit quality metrics into a single stakeholder-friendly document. "
        f"The system achieves an overall constitution score of <b>{overall_score}/10</b> "
        f"across {n_categories} categories with <b>{total_evidence:,}</b> evidence items, "
        f"and a PR audit score of <b>{pr_score}/100</b>.",
        s["body"],
    ))

    # Key stat cards
    stat_data = [
        [
            _make_stat_card(s, "Constitution Score", f"{overall_score}/10", _score_color(overall_score)),
            _make_stat_card(s, "Evidence Items", f"{total_evidence:,}", MED_BLUE),
            _make_stat_card(s, "Categories", f"{n_categories}", DARK_BLUE),
            _make_stat_card(s, "PR Audit Score", f"{pr_score}/100", _score_color(pr_score / 10)),
            _make_stat_card(s, "PR Checks Passed", f"{pr_passed}/{pr_total}", GREEN if pr_passed == pr_total else ORANGE),
        ]
    ]
    stat_tbl = Table(stat_data, colWidths=[doc.width / 5] * 5)
    stat_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(stat_tbl)
    story.append(Spacer(1, 10))

    # Score distribution bar
    story.append(Paragraph("Score Distribution", s["h2"]))
    n_green = n_categories - len(below_green)
    n_amber = len(below_green) - len(below_amber)
    n_red = len(below_amber)
    dist_data = [[Paragraph(f"[GREEN] >=9.0: {n_green}", ParagraphStyle("dg", fontSize=9, textColor=GREEN)),
            Paragraph(f"[AMBER] >=8.0: {n_amber}", ParagraphStyle("da", fontSize=9, textColor=ORANGE)),
            Paragraph(f"[RED] {'>=7.5' if n_red > 0 else '<7.5'}: {n_red}", ParagraphStyle("dr", fontSize=9, textColor=RED)),
        ]
    ]
    dist_tbl = Table(dist_data, colWidths=[doc.width / 3] * 3)
    dist_tbl.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BOX", (0, 0), (-1, -1), 0.5, GREY),
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(dist_tbl)
    story.append(Spacer(1, 6))

    # Quick findings
    if below_red:
        story.append(Paragraph(
            f"<b>[!] {len(below_red)} categories below {THRESHOLD_RED}/10</b> require attention: "
            + ", ".join(c["category_id"] for c in below_red[:8])
            + ("..." if len(below_red) > 8 else ""),
            s["body"],
        ))

    if pr_data.get("sections"):
        failed = [sec for sec in pr_data["sections"] if not sec["passed"]]
        if failed:
            story.append(Paragraph(
                f"<b>[!] {len(failed)} PR audit checks failing:</b> "
                + ", ".join(sec["name"] for sec in failed),
                s["body"],
            ))
    story.append(Spacer(1, 8))

    # ═══════════════════════════════════════════════════════════════════════
    # PAGE 2+: CONSTITUTION SCORING BY GROUP
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("Constitution Scoring - Group Summary", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    group_rows = [["Group", "Categories", "Avg Score", "Top Category", "Lowest Category"]]
    for g_name in sorted(groups.keys()):
        cats = groups[g_name]
        avg = sum(c["score"] for c in cats) / len(cats)
        top = max(cats, key=lambda c: c["score"])
        low = min(cats, key=lambda c: c["score"])
        group_rows.append([
            Paragraph(g_name, s["category_name"]),
            Paragraph(str(len(cats)), ParagraphStyle("cnt", fontSize=9, alignment=TA_CENTER)),
            Paragraph(f"{avg:.2f}", ParagraphStyle(f"sc_{g_name}", fontSize=9, textColor=_score_color(avg), alignment=TA_CENTER)),
            Paragraph(f"{top['category_id']} ({top['score']})", s["small"]),
            Paragraph(f"{low['category_id']} ({low['score']})", s["small"]),
        ])

    group_tbl = Table(group_rows, colWidths=[doc.width * 0.22, doc.width * 0.10, doc.width * 0.12, doc.width * 0.28, doc.width * 0.28])
    group_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(group_tbl)
    story.append(Spacer(1, 10))

    # ═══════════════════════════════════════════════════════════════════════
    # ALL CATEGORIES TABLE
    # ═══════════════════════════════════════════════════════════════════════
    story.append(Paragraph("All Categories - Detailed Scores", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    all_rows = [["ID", "Name", "Group", "Score", "Max", "%", "Evidence"]]
    for c in sorted(score_data["categories"], key=lambda x: (x["group"], x["category_id"])):
        pct = c["score"] / c["max_score"] * 100 if c["max_score"] else 0
        all_rows.append([
            Paragraph(c["category_id"], s["small"]),
            Paragraph(c["name"], s["category_name"]),
            Paragraph(c["group"], s["small"]),
            Paragraph(f"{c['score']:.1f}", ParagraphStyle(f"sc_{c['category_id']}", fontSize=9, textColor=_score_color(c["score"]), alignment=TA_CENTER)),
            Paragraph(f"{c['max_score']:.1f}", ParagraphStyle("ms", fontSize=8, alignment=TA_CENTER, textColor=DARK_GREY)),
            Paragraph(f"{pct:.0f}%", ParagraphStyle(f"pct_{c['category_id']}", fontSize=8, alignment=TA_CENTER, textColor=_score_color(c["score"]))),
            Paragraph(str(c["evidence_count"]), ParagraphStyle("ev", fontSize=8, alignment=TA_CENTER)),
        ])

    all_tbl = Table(all_rows, colWidths=[doc.width * 0.08, doc.width * 0.30, doc.width * 0.18, doc.width * 0.10, doc.width * 0.08, doc.width * 0.10, doc.width * 0.08])
    all_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(all_tbl)

    # ═══════════════════════════════════════════════════════════════════════
    # GAP ANALYSIS
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("Gap Analysis - Categories Below 7.5/10", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    if below_red:
        gap_rows = [["ID", "Name", "Group", "Current", "Target", "Gap", "Evidence", "Priority"]]
        for c in sorted(below_red, key=lambda x: x["score"]):
            gap = THRESHOLD_RED - c["score"]
            priority = "HIGH" if gap > 1.0 else ("MEDIUM" if gap > 0.5 else "LOW")
            p_color = RED if priority == "HIGH" else (ORANGE if priority == "MEDIUM" else GREEN)
            gap_rows.append([
                Paragraph(c["category_id"], s["small"]),
                Paragraph(c["name"], s["category_name"]),
                Paragraph(c["group"], s["small"]),
                Paragraph(f"{c['score']:.1f}", ParagraphStyle(f"sc_{c['category_id']}", fontSize=9, textColor=RED, alignment=TA_CENTER)),
                Paragraph(f"{THRESHOLD_RED:.1f}", ParagraphStyle("tgt", fontSize=8, alignment=TA_CENTER, textColor=GREEN)),
                Paragraph(f"{gap:.1f}", ParagraphStyle(f"gap_{c['category_id']}", fontSize=9, textColor=p_color, alignment=TA_CENTER)),
                Paragraph(str(c["evidence_count"]), ParagraphStyle("ev", fontSize=8, alignment=TA_CENTER)),
                Paragraph(priority, ParagraphStyle(f"pri_{c['category_id']}", fontSize=8, textColor=p_color, alignment=TA_CENTER)),
            ])

        gap_tbl = Table(gap_rows, colWidths=[doc.width * 0.08, doc.width * 0.24, doc.width * 0.18, doc.width * 0.10, doc.width * 0.10, doc.width * 0.10, doc.width * 0.10, doc.width * 0.10])
        gap_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), RED),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("GRID", (0, 0), (-1, -1), 0.3, GREY),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(gap_tbl)
    else:
        story.append(Paragraph(
            f"<b>All {n_categories} categories are above {THRESHOLD_RED}/10!</b>",
            ParagraphStyle("congrats", fontSize=12, textColor=GREEN, spaceAfter=6),
        ))
    story.append(Spacer(1, 8))

    # Recommendations
    story.append(Paragraph("Recommended Actions for Gap Closure", s["h2"]))
    recs = []
    for c in below_red[:10]:
        needed = int((THRESHOLD_RED - c["score"]) * 2) + 1
        recs.append(
            f"• <b>{c['category_id']}</b> ({c['name']}): Add ~{needed} more evidence entries "
            f"(currently {c['evidence_count']}) to cross {THRESHOLD_RED}/10"
        )
    if recs:
        for r in recs:
            story.append(Paragraph(r, s["body"]))
    else:
        story.append(Paragraph("No critical gaps - maintain current evidence pipeline.", s["body"]))

    # ═══════════════════════════════════════════════════════════════════════
    # PR AUDIT RESULTS
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("PR Audit Results", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    story.append(Paragraph(
        f"Overall PR Audit Score: <b>{pr_score}/100</b> - "
        f"{'PASS' if pr_passed == pr_total else 'NEEDS ATTENTION'}",
        s["body"],
    ))

    pr_rows = [["Check", "Status", "Findings", "Duration"]]
    for sec in pr_data["sections"]:
        status_icon = "[PASS]" if sec["passed"] else "[FAIL]"
        pr_rows.append([
            Paragraph(sec["name"], s["category_name"]),
            Paragraph(f"{status_icon} {'PASS' if sec['passed'] else 'FAIL'}", ParagraphStyle(f"st_{sec['name']}", fontSize=9, textColor=GREEN if sec['passed'] else RED)),
            Paragraph(str(sec["findings_count"]), ParagraphStyle("fc", fontSize=9, alignment=TA_CENTER)),
            Paragraph(f"{sec['duration_sec']:.1f}s", ParagraphStyle("dur", fontSize=8, alignment=TA_CENTER, textColor=DARK_GREY)),
        ])

    pr_tbl = Table(pr_rows, colWidths=[doc.width * 0.30, doc.width * 0.25, doc.width * 0.20, doc.width * 0.25])
    pr_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(pr_tbl)
    story.append(Spacer(1, 8))

    # PR findings detail
    for sec in pr_data["sections"]:
        if sec["findings"]:
            story.append(Paragraph(f"Details: {sec['name']}", s["h2"]))
            for finding in sec["findings"]:
                story.append(Paragraph(
                    f"  • [{finding.get('severity', 'INFO')}] {finding.get('message', ''):.200}",
                    s["small"],
                ))

    # ═══════════════════════════════════════════════════════════════════════
    # HISTORICAL IMPROVEMENT
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("Historical Score Improvement", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    # Tracked milestones from this session (historical narrative)
    history_data = [
        ["Date", "Score", "Evidence", "Milestone"],
        ["Session Start", "7.66/10", "1,345", "Baseline"],
        ["After 47-category fix", "7.92/10", "1,424", "+79 evidence, 45 categories crossed 7.0"],
        ["After boost collector", "8.25/10", "1,528", "+104 evidence, 35 targeted categories boosted"],
        ["Constitution v4.0 engine audit", "8.71/10", "1,703", "+175 evidence, 111 categories live-scored"],
        ["Top-10 gap closure", "8.83/10", "1,757", "+54 evidence, 10 categories at 100%"],
    ]

    # Previous milestone is read from the stored snapshot (drift-free anchor),
    # so regenerations always delta against the previous actual run.
    prev = load_prev_anchor()
    if prev:
        history_data.append([
            "Previous run",
            f"{prev['score']}/10",
            f"{prev['evidence']:,}",
            "Snapshot anchor (previous milestone)",
        ])
    history_data.append([
        datetime.now(timezone.utc).strftime("%d %b %Y"),
        f"{overall_score}/10",
        f"{total_evidence:,}",
        "Current state"
        + (f" — delta {_fmt_delta(overall_score - prev['score'], total_evidence - prev['evidence'])}" if prev else ""),
    ])

    hist_tbl = Table(history_data, colWidths=[doc.width * 0.18, doc.width * 0.15, doc.width * 0.15, doc.width * 0.52])
    hist_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_GREY]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(hist_tbl)
    story.append(Spacer(1, 10))

    # Improvement summary
    story.append(Paragraph("Key Improvements", s["h2"]))
    improvements = [
        f"<b>Overall Score:</b> {prev['score'] if prev else 7.66:.2f}/10 → {overall_score}/10 "
        f"({_fmt_delta(overall_score - (prev['score'] if prev else 7.66), total_evidence - (prev['evidence'] if prev else 1345))})",
        "<b>New Modules:</b> Enterprise Decision Memory (KNW-01→KNW-04), Mediator Pattern, CQRS",
        "<b>New Features:</b> ADR import pipeline, Q&A on decisions, Knowledge Base, Pattern Learner, Auto-Learner",
        "<b>Constitution Categories Expanded:</b> 107 → 111 (4 new KNW categories)",
        "<b>Top-10 gap closure:</b> PRN/AST/SGS categories boosted to 100% (+54 evidence)",
        f"<b>Current coverage:</b> {n_categories} categories live-scored with {total_evidence:,} evidence items",
    ]
    for imp in improvements:
        story.append(Paragraph(f"• {imp}", s["body"]))

    # ═══════════════════════════════════════════════════════════════════════
    # SYSTEM OVERVIEW
    # ═══════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story.append(Paragraph("System Overview", s["h1"]))
    story.append(HRFlowable(width="100%", thickness=0.5, color=MED_BLUE, spaceAfter=6))

    overview_items = [
        "<b>Platform:</b> OPB Index Options Buying Bot v2.57.1",
        "<b>Purpose:</b> Automated NSE index options buying (NIFTY / BANKNIFTY / FINNIFTY)",
        "<b>Python:</b> 3.10–3.19 (enforced at startup)",
        "<b>Architecture:</b> Clean Architecture + DDD + CQRS + Event Sourcing",
        "<b>Brokers:</b> Zerodha Kite, Angel Broking - via abstract adapter layer",
        "<b>Data Sources:</b> Yahoo Finance, NSE API (when available), WebSocket feeds",
        "<b>ML:</b> LightGBM + scikit-learn (14 features, SHAP explainability)",
        f"<b>Governance:</b> Constitution Validation Engine (111 categories, {total_evidence:,} evidence items)",
        f"<b>Constitution Score:</b> {overall_score}/10 (up from 7.66)",
        f"<b>PR Audit Score:</b> {pr_score}/100",
    ]
    for item in overview_items:
        story.append(Paragraph(f"• {item}", s["body"]))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.3, color=GREY, spaceAfter=4))
    story.append(Paragraph(
        f"OPB Consolidated Stakeholder Report · Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} · "
        f"Version v2.57.1 · Constitution Score: {overall_score}/10 · PR Audit: {pr_score}/100",
        s["footer"],
    ))

    doc.build(story)
    print(f"[OK] PDF generated: {output_path}")
    return output_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate consolidated stakeholder PDF report")
    parser.add_argument("--output", "-o", default="docs/CONSOLIDATED_STAKEHOLDER_REPORT.pdf",
                        help="Output PDF path")
    args = parser.parse_args()
    generate_report(args.output)
