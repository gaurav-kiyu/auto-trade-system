"""
Risk and SLO route registration for the Enterprise Dashboard.

Handles: /api/risk/snapshot, /api/risk/alerts, /api/risk/limits,
/api/risk/concentration, /api/slo/compliance, /api/portfolio/asset-allocation,
/api/system/trades/export.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from typing import Any

from fastapi import Depends

_log = logging.getLogger(__name__)


def register_risk_routes(app, dashboard, admin_only, operator_or_admin):
    """Register risk, SLO, and portfolio routes.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        admin_only: FastAPI Depends for admin role.
        operator_or_admin: FastAPI Depends for operator or admin role.
    """

    @app.get("/api/risk/snapshot")
    async def api_risk_snapshot(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get global risk snapshot."""
        try:
            from core.risk_dashboard import get_risk_dashboard
            dash = get_risk_dashboard(dashboard._cfg)
            snap = dash.get_snapshot()
            return snap.to_dict()
        except ImportError:
            return {"status": "unavailable", "detail": "RiskDashboard not available (import error)"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Risk snapshot failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/slo/compliance")
    async def api_slo_compliance(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get SLO/SLA compliance report."""
        try:
            from core.slo_governance import get_slo_governance
            slo = get_slo_governance()
            report = slo.check_all_slos()
            return report.to_dict()
        except ImportError:
            return {"status": "unavailable", "detail": "SLOGovernance not available (import error)"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] SLO compliance check failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/risk/alerts")
    async def api_risk_alerts(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get active risk alerts."""
        try:
            from core.risk_dashboard import get_risk_dashboard
            dash = get_risk_dashboard(dashboard._cfg)
            alerts = dash.get_alerts(unacknowledged_only=True)
            return {
                "alerts": [a.to_dict() for a in alerts],
                "count": len(alerts),
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "RiskDashboard not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Risk alerts failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/risk/limits")
    async def api_risk_limits(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get risk limit utilization across all categories."""
        try:
            from core.risk_dashboard import get_risk_dashboard
            dash = get_risk_dashboard(dashboard._cfg)
            snap = dash.get_snapshot()
            limits = [
                {
                    "name": m.name,
                    "utilization_pct": m.utilization_pct,
                    "limit_value": m.limit_value,
                    "current_value": m.current_value,
                    "unit": m.unit,
                    "status": m.status,
                }
                for m in snap.metrics
            ]
            return {
                "limits": limits,
                "count": len(limits),
                "timestamp": time.time(),
            }
        except ImportError:
            return {"status": "unavailable", "detail": "RiskDashboard not available"}
        except (ValueError, TypeError, AttributeError) as exc:
            _log.warning("[DASH] Risk limits failed: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/risk/concentration")
    async def api_risk_concentration(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Calculate position concentration risk metrics."""
        trades = dashboard._load_recent_trades(days=1, n=500)
        state = dashboard._read_state()
        capital = state.get("base_capital", state.get("capital", 1_000_000)) or 1_000_000
        open_positions = [t for t in trades if t.get("status") == "open" or t.get("exit_time") is None]
        concentration_risk = "LOW"
        single_largest_pct = 0
        total_exposure = 0
        by_index = {}
        for t in open_positions:
            val = abs(t.get("pnl", 0)) + abs(t.get("entry_price", 0) * t.get("quantity", 0))
            total_exposure += val
            idx = t.get("index", t.get("symbol", "unknown"))
            by_index[idx] = by_index.get(idx, 0) + val
        for idx, val in by_index.items():
            pct = (val / capital * 100) if capital > 0 else 0
            if pct > single_largest_pct:
                single_largest_pct = pct
        if single_largest_pct > 30:
            concentration_risk = "CRITICAL"
        elif single_largest_pct > 15:
            concentration_risk = "HIGH"
        elif single_largest_pct > 8:
            concentration_risk = "MODERATE"
        return {
            "concentration_risk": concentration_risk,
            "single_largest_index_pct": round(single_largest_pct, 2),
            "total_exposure": round(total_exposure, 2),
            "capital": capital,
            "exposure_pct": round((total_exposure / capital * 100) if capital > 0 else 0, 2),
            "open_position_count": len(open_positions),
            "by_index": {k: {"exposure": round(v, 2), "pct": round((v / capital * 100) if capital > 0 else 0, 2)} for k, v in by_index.items()},
            "timestamp": time.time(),
        }

    @app.get("/api/portfolio/asset-allocation", tags=["Risk"])
    async def api_portfolio_allocation(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Get multi-asset portfolio allocation breakdown."""
        aggregator = dashboard._bot_refs.get("portfolio_aggregator")
        if aggregator is None:
            return {"status": "unavailable", "detail": "Portfolio aggregator not wired"}

        try:
            state = dashboard._read_state()
            cash = state.get("capital", state.get("base_capital", 0)) or 0

            equity_positions = dashboard._bot_refs.get("equity_positions", [])
            fo_futures = dashboard._bot_refs.get("fo_futures", [])
            fo_options = dashboard._bot_refs.get("fo_options", [])
            commodity_positions = dashboard._bot_refs.get("commodity_positions", [])
            currency_positions = dashboard._bot_refs.get("currency_positions", [])
            bond_positions = dashboard._bot_refs.get("bond_positions", [])
            equity_holdings = dashboard._bot_refs.get("equity_holdings", [])
            sip_plans = dashboard._bot_refs.get("sip_plans", [])
            mf_holdings = dashboard._bot_refs.get("mf_holdings", [])

            snapshot = aggregator.aggregate(
                equity_positions=equity_positions,
                fo_futures=fo_futures,
                fo_options=fo_options,
                commodity_positions=commodity_positions,
                currency_positions=currency_positions,
                bond_positions=bond_positions,
                equity_holdings=equity_holdings,
                sip_plans=sip_plans,
                mf_holdings=mf_holdings,
                cash_balance=float(cash),
            )

            return {
                "status": "ok",
                "total_value": round(snapshot.total_value, 2),
                "cash": round(snapshot.cash, 2),
                "positions_count": len(snapshot.positions),
                "allocation_by_asset": snapshot.metadata.get("exposures", {}),
                "timestamp": time.time(),
            }
        except (ValueError, TypeError, AttributeError, RuntimeError) as exc:
            _log.warning("[DASH] Portfolio allocation error: %s", exc)
            return {"status": "error", "detail": str(exc)}

    @app.get("/api/system/trades/export")
    async def api_trades_export(user: Any = Depends(dashboard._auth_deps.require_auth_optional)):
        """Export trades as CSV download."""
        trades = dashboard._load_recent_trades(days=90, n=5000)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "symbol", "direction", "entry_price", "exit_price",
                         "quantity", "pnl", "status", "entry_time", "exit_time",
                         "strike", "expiry", "index"])
        for t in trades:
            writer.writerow([
                t.get("created_at", t.get("entry_time", "")),
                t.get("symbol", t.get("index", "")),
                t.get("direction", ""),
                t.get("entry_price", ""),
                t.get("exit_price", ""),
                t.get("quantity", ""),
                t.get("pnl", ""),
                t.get("status", ""),
                t.get("entry_time", ""),
                t.get("exit_time", ""),
                t.get("strike", ""),
                t.get("expiry", ""),
                t.get("index", ""),
            ])
        csv_data = output.getvalue()
        output.close()
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=trades_export.csv"},
        )
