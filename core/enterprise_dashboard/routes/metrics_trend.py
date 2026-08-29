"""Success Metrics Trend API routes for the Enterprise Dashboard.

Exposes the Constitution v4.0 success-metrics time-series tracker
(MET-07 Technical Debt Trending Down / MET-08 Developer Productivity
Trending Up) as read-only JSON endpoints under /api/metrics/trend/*:

  - GET /api/metrics/trend                — full report (verdicts + snapshots + stats
                                            + register consistency check)
  - GET /api/metrics/trend/stats          — quick statistics
  - GET /api/metrics/trend/snapshots      — snapshot history list
  - GET /api/metrics/trend/validate/{metric_id} — per-metric trend verdict
  - GET /api/metrics/trend/release-audits — release audit records (incl.
                                            register gate verdict)

The register consistency check (register ID prefixes aligned with what the
MET-07 tracker counts) is computed independently of the trend module, so a
registry drift — or an unavailable trend module — never hides the other.
All endpoints degrade gracefully when the trend module or its history file
is unavailable (fresh checkout before the first release capture).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import Depends

_log = logging.getLogger(__name__)

# Release audit records written by scripts/release_governance.py.
# This module is at core/enterprise_dashboard/routes/metrics_trend.py, so the
# project root is FOUR parents up (routes -> enterprise_dashboard -> core -> ROOT).
_AUDIT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs" / "audit"


def _list_audit_records(limit: int = 50) -> list[dict[str, Any]]:
    """Read release audit JSON records from ``logs/audit/`` (newest first).

    Legacy records written before the register-gate fields existed default to
    ``None`` / ``"unknown"``. Missing directory or corrupt JSON files are
    skipped gracefully.
    """
    records: list[dict[str, Any]] = []
    audit_dir = _AUDIT_DIR
    if not audit_dir.is_dir():
        return records
    try:
        files = sorted(
            audit_dir.glob("release_v*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return records
    for f in files[: max(1, min(limit, 500))]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        records.append({
            "filename": f.name,
            "version": data.get("version", ""),
            "date": data.get("date", ""),
            "branch": data.get("branch", ""),
            "changes_count": len(data.get("changes") or []),
            "trend_snapshot_captured": bool(data.get("trend_snapshot_captured", False)),
            # register_gate_passed may be absent in legacy records.
            "register_gate_passed": data.get("register_gate_passed"),
            "register_gate_status": data.get("register_gate_status", "unknown"),
            "captured_at": data.get("timestamp", 0.0),
        })
    return records


def _trend():
    from core.success_metrics_trend import get_metrics_trend
    return get_metrics_trend()


def _register_consistency():
    """Run the register-pattern consistency check (lazy import)."""
    from core.success_metrics_trend import check_register_consistency
    return check_register_consistency()


_REGISTER_DETAIL_KEYS = ("ok", "expected_prefix", "file_exists",
                          "tracker_count", "parsed_count", "matching_count",
                          "foreign_ids", "count_agrees")


def _compact_register_details(registers: dict[str, Any]) -> dict[str, Any]:
    """Strip the bulky ``row_ids`` list from each register detail.

    ``check_register_consistency()`` includes the full parsed ID list per
    register (43k+ rows for the dead-code register); the dashboard only needs
    the counts/status, so drop the per-row IDs before serializing.
    """
    return {
        rp: {k: r.get(k) for k in _REGISTER_DETAIL_KEYS if k in r}
        for rp, r in registers.items()
    }


def _register_consistency_payload(compact: bool = False) -> dict[str, Any]:
    """Build the register consistency section of API responses.

    Computed independently of the trend module. On drift the report still
    succeeds but flags the drifted registers, so a stale trend snapshot can
    never hide a broken MET-07 data source.

    Args:
        compact: When True (stats endpoint), return only the status summary
            instead of the full per-register detail.
    """
    try:
        consistency = _register_consistency()
        ok = bool(consistency.get("ok", False))
        registers = consistency.get("registers", {})
        payload: dict[str, Any] = {
            "ok": ok,
            "status": "aligned" if ok else "drift",
            "drifted_registers": [
                rp for rp, r in registers.items() if not r.get("ok", False)
            ],
        }
        if not compact:
            payload["registers"] = _compact_register_details(registers)
            payload["checked_at"] = consistency.get("checked_at", "")
        return payload
    except (ImportError, ValueError, TypeError, AttributeError) as exc:
        _log.debug("[DASH] Register consistency check unavailable: %s", exc)
        return {
            "ok": False,
            "status": "unavailable",
            "registers": {},
            "drifted_registers": [],
            "detail": str(exc),
        }

def register_metrics_trend_routes(app, dashboard, admin_only, operator_or_admin) -> None:  # type: ignore[no-untyped-def]
    """Register success-metrics trend API routes.

    Read-only analytics endpoints follow the same optional-auth convention as
    the /api/system/* routes (metrics are non-sensitive operational data).

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.

    """

    @app.get("/api/metrics/trend", tags=["MetricsTrend"])
    async def api_metrics_trend(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Full success-metrics trend report (verdicts, snapshots, stats)."""
        try:
            trend = _trend()
            report = trend.get_report()
            stats = trend.get_stats()
            payload = {
                "status": "ok",
                "metric_ids": report.get("metric_ids", []),
                "total_snapshots": report.get("total_snapshots", 0),
                "verdicts": report.get("verdicts", {}),
                "snapshots": report.get("snapshots", []),
                "stats": stats,
                "has_enough_data": stats.get("has_enough_data", False),
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Metrics trend report unavailable: %s", exc)
            payload = {
                "status": "unavailable",
                "detail": str(exc),
                "verdicts": {},
                "snapshots": [],
                "total_snapshots": 0,
                "has_enough_data": False,
            }
        payload["register_consistency"] = _register_consistency_payload()
        return payload

    @app.get("/api/metrics/trend/stats", tags=["MetricsTrend"])
    async def api_metrics_trend_stats(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Quick statistics for the trend tracker."""
        try:
            trend = _trend()
            payload = {"status": "ok", "stats": trend.get_stats(), "timestamp": time.time()}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Metrics trend stats unavailable: %s", exc)
            payload = {"status": "unavailable", "stats": {}, "detail": str(exc)}
        payload["register_consistency"] = _register_consistency_payload(compact=True)
        return payload

    @app.get("/api/metrics/trend/snapshots", tags=["MetricsTrend"])
    async def api_metrics_trend_snapshots(
        limit: int = 50,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Snapshot history (newest first), capped by limit."""
        try:
            trend = _trend()
            # FastAPI already coerces the typed ``limit: int`` query param.
            snaps = trend.list_snapshots(limit=max(1, min(limit, 500)))
            return {
                "status": "ok",
                "snapshots": [s.to_dict() for s in snaps],
                "count": len(snaps),
                "timestamp": time.time(),
            }
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Metrics trend snapshots unavailable: %s", exc)
            return {"status": "unavailable", "snapshots": [], "count": 0, "detail": str(exc)}

    @app.get("/api/metrics/trend/validate/{metric_id}", tags=["MetricsTrend"])
    async def api_metrics_trend_validate(
        metric_id: str,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """Validate a single trend metric (MET-07 / MET-08)."""
        try:
            trend = _trend()
            verdict = trend.validate_metric(metric_id.upper())
            return {"status": "ok", "verdict": verdict}
        except (ImportError, ValueError, TypeError, AttributeError) as exc:
            _log.debug("[DASH] Metrics trend validate unavailable: %s", exc)
            return {"status": "unavailable", "verdict": None, "detail": str(exc)}

    @app.get("/api/metrics/trend/release-audits", tags=["MetricsTrend"])
    async def api_metrics_trend_release_audits(
        limit: int = 50,
        user: Any = Depends(dashboard._auth_deps.require_auth_optional),
    ):
        """List release audit records with the register gate verdict."""
        records = _list_audit_records(limit=max(1, min(limit, 500)))
        return {
            "status": "ok",
            "audits": records,
            "count": len(records),
            "timestamp": time.time(),
        }
