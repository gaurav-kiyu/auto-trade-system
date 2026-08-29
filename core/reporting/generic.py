"""Generic report snapshots used by the Report Center exporters."""
from __future__ import annotations
from dataclasses import asdict, is_dataclass
from typing import Any


def _dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return [_dict(v) for v in value]
    return value


def build_report(report_id: str, dashboard) -> dict[str, Any]:
    if report_id == "signal-intelligence":
        from core.reporting.signal_intelligence import build_signal_intelligence_report
        return build_signal_intelligence_report()
    if report_id == "trades":
        return {"report_name": "Trade History", "generated_at": __import__("datetime").datetime.now().isoformat(), "rows": dashboard._load_recent_trades(days=3650, n=50000)}
    if report_id == "risk":
        from core.risk_dashboard import get_risk_dashboard
        return {"report_name": "Risk Snapshot", "generated_at": __import__("datetime").datetime.now().isoformat(), "report": _dict(get_risk_dashboard(dashboard._cfg).get_snapshot())}
    if report_id == "bi":
        from core.bi_dashboard import get_bi_dashboard
        return {"report_name": "Business Intelligence", "generated_at": __import__("datetime").datetime.now().isoformat(), "report": _dict(get_bi_dashboard().generate_bi_report(force=True))}
    if report_id == "governance":
        from core.strategy.approval_workflow import get_approval_workflow
        return {"report_name": "Strategy Governance", "generated_at": __import__("datetime").datetime.now().isoformat(), "report": _dict(get_approval_workflow().get_governance_report())}
    if report_id == "capacity":
        from core.capacity_planning import CapacityPlanner
        return {"report_name": "Capacity Planning", "generated_at": __import__("datetime").datetime.now().isoformat(), "report": _dict(CapacityPlanner(dashboard._cfg).analyze())}
    if report_id == "security":
        from core.security_auditor import get_security_auditor
        return {"report_name": "Security Assessment", "generated_at": __import__("datetime").datetime.now().isoformat(), "report": _dict(get_security_auditor().run_full_scan())}
    raise KeyError(report_id)
