"""Generic PDF/Excel rendering for arbitrary JSON-like report snapshots."""
from __future__ import annotations
import io
from typing import Any


def _rows(value: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(value, dict):
        out=[]
        for k,v in value.items(): out.extend(_rows(v, f"{prefix}.{k}" if prefix else str(k)))
        return out
    if isinstance(value, list):
        if not value: return [(prefix, "[]")]
        if all(isinstance(x, (str,int,float,bool)) or x is None for x in value): return [(prefix, ", ".join(map(str,value)))]
        return [(f"{prefix}[{i}]", str(v)) for i,v in enumerate(value[:500])]
    return [(prefix, value)]


def export_generic_excel(report: dict[str, Any]) -> bytes:
    import xlsxwriter
    out=io.BytesIO(); wb=xlsxwriter.Workbook(out,{"in_memory":True}); ws=wb.add_worksheet("Report")
    h=wb.add_format({"bold":True,"bg_color":"#1f4e78","font_color":"#ffffff","border":1})
    ws.write_row(0,0,["Field","Value"],h)
    for i,(k,v) in enumerate(_rows(report),1): ws.write(i,0,k); ws.write(i,1,str(v))
    ws.set_column(0,0,55); ws.set_column(1,1,100); ws.freeze_panes(1,0)
    ws.autofilter(0, 0, max(ws.dim_rowmax or 1, 1), 1)
    wb.close(); return out.getvalue()


def export_generic_pdf(report: dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import landscape,A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,Spacer
    out=io.BytesIO(); doc=SimpleDocTemplate(out,pagesize=landscape(A4),rightMargin=24,leftMargin=24,topMargin=24,bottomMargin=24)
    styles=getSampleStyleSheet(); name=str(report.get("report_name","Report")); rows=_rows(report)
    story=[Paragraph(name,styles["Title"]),Spacer(1,10)]
    data=[["Field","Value"]]+[[str(k),str(v)[:3000]] for k,v in rows[:1000]]
    t=Table(data,repeatRows=1); t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1f4e78")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.3,colors.grey),("FONTSIZE",(0,0),(-1,-1),7)])); story.append(t); doc.build(story); return out.getvalue()
