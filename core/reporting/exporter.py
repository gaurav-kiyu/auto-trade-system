"""PDF/Excel exporters for dashboard reports.

The exporters accept already-generated report dictionaries, keeping rendering
separate from data collection and making every report exportable without
exposing filesystem paths to the client.
"""
from __future__ import annotations

import io
import json
from typing import Any


def _flatten_rows(rows: list[dict[str, Any]]) -> tuple[list[str], list[list[Any]]]:
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    values = [[row.get(k, "") for k in keys] for row in rows]
    return keys, values


def signal_report_excel(report: dict[str, Any]) -> bytes:
    import xlsxwriter

    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {"in_memory": True})
    header = wb.add_format({"bold": True, "bg_color": "#1f4e78", "font_color": "#ffffff", "border": 1})
    pct = wb.add_format({"num_format": "0.00"})

    summary = wb.add_worksheet("Summary")
    summary.write_row(0, 0, ["Metric", "Value"], header)
    row = 1
    for key, value in report.get("summary", {}).items():
        summary.write(row, 0, key)
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        summary.write(row, 1, value, pct if isinstance(value, (int, float)) else None)
        row += 1
    summary.write(row + 1, 0, "Data quality", header)
    for key, value in report.get("data_quality", {}).items():
        row += 1
        summary.write(row, 0, key)
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        summary.write(row, 1, value)
    summary.freeze_panes(1, 0)
    summary.autofilter(0, 0, max(row - 1, 1), 1)
    summary.set_column(0, 0, 34)
    summary.set_column(1, 1, 24)

    for sheet_name, key in (("Score", "score_breakdown"), ("Category", "category_breakdown"), ("Tier", "tier_breakdown"), ("Direction", "direction_breakdown")):
        ws = wb.add_worksheet(sheet_name)
        keys, values = _flatten_rows(report.get(key, []))
        if keys:
            ws.write_row(0, 0, keys, header)
            for r_idx, vals in enumerate(values, 1):
                ws.write_row(r_idx, 0, vals)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, len(values), len(keys) - 1)
            ws.set_column(0, len(keys) - 1, 20)

    ws = wb.add_worksheet("Recommendations")
    recs = report.get("recommendations", [])
    keys, values = _flatten_rows(recs)
    if keys:
        ws.write_row(0, 0, keys, header)
        for r_idx, vals in enumerate(values, 1):
            ws.write_row(r_idx, 0, vals)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(values), len(keys) - 1)
        ws.set_column(0, len(keys) - 1, 34)

    ws = wb.add_worksheet("Signals")
    keys, values = _flatten_rows(report.get("signals", []))
    if keys:
        ws.write_row(0, 0, keys, header)
        for r_idx, vals in enumerate(values, 1):
            ws.write_row(r_idx, 0, vals)
        ws.freeze_panes(1, 0)
        ws.autofilter(0, 0, len(values), len(keys) - 1)
        ws.set_column(0, len(keys) - 1, 18)

    wb.close()
    return output.getvalue()


def signal_report_pdf(report: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = [Paragraph(report.get("report_name", "Report"), styles["Title"]), Paragraph(report.get("generated_at", ""), styles["Normal"]), Spacer(1, 12)]

    rows = [["Metric", "Value"]] + [[str(k), str(v)] for k, v in report.get("summary", {}).items()]
    t = Table(rows, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
    story.append(t)
    story.append(Spacer(1, 12))

    for title, key in (("Score Breakdown", "score_breakdown"), ("Category Breakdown", "category_breakdown"), ("Tier Breakdown", "tier_breakdown"), ("Direction Breakdown", "direction_breakdown")):
        data = report.get(key, [])
        if not data:
            continue
        story.append(Paragraph(title, styles["Heading2"]))
        keys, values = _flatten_rows(data)
        tbl = Table([keys] + [[str(v) for v in vals] for vals in values], repeatRows=1)
        tbl.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e78")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7)]))
        story.append(tbl)
        story.append(Spacer(1, 8))

    if report.get("recommendations"):
        story.append(PageBreak())
        story.append(Paragraph("Evidence-Based Recommendations", styles["Heading1"]))
        for rec in report["recommendations"]:
            story.append(Paragraph(f"<b>{rec.get('severity','INFO')}</b> — {rec.get('recommendation','')}", styles["BodyText"]))
            story.append(Paragraph(f"Evidence: {rec.get('reason','')}", styles["BodyText"]))
            story.append(Spacer(1, 6))

    story.append(Spacer(1, 8))
    story.append(Paragraph(report.get("data_quality", {}).get("note", ""), styles["BodyText"]))
    doc.build(story)
    return output.getvalue()
