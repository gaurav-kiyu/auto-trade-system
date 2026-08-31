"""Central Report Center: analysis plus PDF/Excel export."""
from __future__ import annotations

from fastapi import Depends, Query, Request
from fastapi.responses import Response


def register_reporting_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    @app.get("/api/reports/signal-intelligence")
    async def signal_intelligence_report(days: int = Query(90, ge=1, le=3650), category: str = "all", tier: str = "all", include_seed_samples: bool = Query(False), user=Depends(operator_or_admin)):
        from core.reporting.signal_intelligence import build_signal_intelligence_report
        return build_signal_intelligence_report(days=days, category=category, tier=tier, include_seed_samples=include_seed_samples)

    @app.get("/api/reports/signal-intelligence/export/{fmt}")
    async def export_signal_intelligence(fmt: str, days: int = Query(90, ge=1, le=3650), category: str = "all", tier: str = "all", user=Depends(operator_or_admin)):
        if fmt not in {"pdf", "xlsx"}:
            return Response(content="Unsupported format", status_code=400, media_type="text/plain")
        from core.reporting.exporter import signal_report_excel, signal_report_pdf
        from core.reporting.signal_intelligence import build_signal_intelligence_report
        report = build_signal_intelligence_report(days=days, category=category, tier=tier)
        if fmt == "pdf":
            return Response(signal_report_pdf(report), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="signal_intelligence_report.pdf"'})
        return Response(signal_report_excel(report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="signal_intelligence_report.xlsx"'})


    @app.get("/api/reports/export/{report_id}/{fmt}")
    async def export_generic_report(report_id: str, fmt: str, user=Depends(operator_or_admin)):
        """Export any Report Center report as PDF or Excel."""
        if fmt not in {"pdf", "xlsx"}:
            return Response(content="Unsupported format", status_code=400, media_type="text/plain")
        from core.reporting.generic import build_report
        from core.reporting.generic_exporter import export_generic_excel, export_generic_pdf
        try:
            report = build_report(report_id, dashboard)
        except KeyError:
            return Response(content="Unknown report", status_code=404, media_type="text/plain")
        except (ImportError, ValueError, TypeError, AttributeError, OSError) as exc:
            return Response(content=f"Report unavailable: {exc}", status_code=503, media_type="text/plain")
        if fmt == "pdf":
            return Response(export_generic_pdf(report), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{report_id}.pdf"'})
        return Response(export_generic_excel(report), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{report_id}.xlsx"'})

    @app.get("/api/reports/catalog")
    async def report_catalog(user=Depends(operator_or_admin)):
        return {
            "reports": [
                {"id": "signal-intelligence", "name": "Signal Historical Intelligence", "pdf": True, "excel": True},
                {"id": "trades", "name": "Trade History", "pdf": True, "excel": True},
                {"id": "bi", "name": "Business Intelligence", "pdf": True, "excel": True},
                {"id": "security", "name": "Security Assessment", "pdf": True, "excel": True},
                {"id": "governance", "name": "Strategy Governance", "pdf": True, "excel": True},
                {"id": "risk", "name": "Risk Snapshot", "pdf": True, "excel": True},
                {"id": "capacity", "name": "Capacity Planning", "pdf": True, "excel": True},
            ]
        }

    @app.post("/api/reports/table-export/{fmt}")
    async def export_rendered_report_tables(fmt: str, request: Request, user=Depends(operator_or_admin)):
        """Export the currently rendered report tables to PDF/XLSX.
        Used by report pages that already expose live tabular data but do not
        have a dedicated backend report builder. Payloads are bounded and
        require the same operator/admin authorization as the Report Center.
        """
        if fmt not in {"pdf", "xlsx"}:
            return Response(content="Unsupported format", status_code=400, media_type="text/plain")
        try:
            payload = await request.json()
            tables = payload.get("tables", []) if isinstance(payload, dict) else []
            if not isinstance(tables, list) or len(tables) > 20:
                return Response(content="Invalid table payload", status_code=400, media_type="text/plain")
            clean = []
            total_rows = 0
            for idx, table in enumerate(tables):
                if not isinstance(table, dict):
                    continue
                headers = table.get("headers", [])
                rows = table.get("rows", [])
                if not isinstance(headers, list) or not isinstance(rows, list):
                    continue
                headers = [str(x)[:120] for x in headers[:100]]
                safe_rows = []
                for row in rows[:10000]:
                    if not isinstance(row, list):
                        continue
                    safe_rows.append([str(x)[:2000] for x in row[:len(headers)]])
                total_rows += len(safe_rows)
                if total_rows > 50000:
                    break
                clean.append({"name": str(table.get("name") or f"Report{idx+1}")[:31], "headers": headers, "rows": safe_rows})
            if fmt == "xlsx":
                import io

                import xlsxwriter
                out = io.BytesIO()
                wb = xlsxwriter.Workbook(out, {"in_memory": True})
                header_fmt = wb.add_format({"bold": True, "bg_color": "#1f4e78", "font_color": "#ffffff", "border": 1})
                for table in clean:
                    ws = wb.add_worksheet(table["name"][:31] or "Report")
                    headers = table["headers"] or ["Value"]
                    ws.write_row(0, 0, headers, header_fmt)
                    for r, row in enumerate(table["rows"], 1):
                        ws.write_row(r, 0, row)
                    if table["rows"]:
                        ws.autofilter(0, 0, len(table["rows"]), len(headers)-1)
                    ws.freeze_panes(1, 0)
                    ws.set_column(0, len(headers)-1, 18)
                if not clean:
                    wb.add_worksheet("Report")
                wb.close()
                return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                headers={"Content-Disposition": 'attachment; filename="report_export.xlsx"'})
            import io

            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle
            out = io.BytesIO()
            doc = SimpleDocTemplate(out, pagesize=landscape(A4), rightMargin=18, leftMargin=18, topMargin=18, bottomMargin=18)
            styles = getSampleStyleSheet()
            story = [Paragraph("Report Export", styles["Title"])]
            for i, table in enumerate(clean):
                story.append(Paragraph(table["name"], styles["Heading2"]))
                data = [table["headers"] or ["Value"]] + table["rows"]
                tbl = Table(data, repeatRows=1)
                tbl.setStyle(TableStyle([
                    ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1f4e78")),
                    ("TEXTCOLOR", (0,0), (-1,0), colors.white),
                    ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
                    ("FONTSIZE", (0,0), (-1,-1), 6),
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                ]))
                story.append(tbl)
                if i < len(clean)-1:
                    story.append(PageBreak())
            if not clean:
                story.append(Paragraph("No tabular data was available on this report page.", styles["BodyText"]))
            doc.build(story)
            return Response(out.getvalue(), media_type="application/pdf",
                            headers={"Content-Disposition": 'attachment; filename="report_export.pdf"'})
        except (ValueError, TypeError, KeyError, OSError) as exc:
            return Response(content=f"Report export failed: {exc}", status_code=400, media_type="text/plain")

