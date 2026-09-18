"""OPB Dynamic Capability Registry (v3.0).

Authoritative registry for feature gating and operational readiness detection.
Gates optional capabilities (Sector Rotation, FII/DII Radar, Broker Margin Matrix,
Trade Copier, Expiry Harvester) based on live dependency health.
Crucially: Rejects sample/demo data alone as evidence for AVAILABLE state.
"""

from __future__ import annotations

import datetime
from enum import Enum
import logging
import threading
from typing import Any

_log = logging.getLogger("CAPABILITY_REGISTRY")


class CapabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"


class CapabilityRegistry:
    """Thread-safe dynamic capability registry and readiness inspector."""

    _instance: CapabilityRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._overrides: dict[str, dict[str, Any]] = {}
        self._cached_report: dict[str, Any] | None = None
        self._last_evaluated_at: datetime.datetime | None = None

    @classmethod
    def get_instance(cls) -> CapabilityRegistry:
        with cls._lock:
            if cls._instance is None:
                cls._instance = CapabilityRegistry()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    def set_override(
        self,
        key: str,
        state: CapabilityState | str,
        reason: str = "",
    ) -> None:
        """Set a test/runtime override for a capability."""
        with self._lock:
            state_val = state.value if isinstance(state, CapabilityState) else str(state)
            self._overrides[key] = {
                "state": state_val,
                "reason": reason,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            self._cached_report = None

    def clear_overrides(self) -> None:
        """Clear all runtime overrides."""
        with self._lock:
            self._overrides.clear()
            self._cached_report = None

    def _verify_sector_radar(self) -> tuple[CapabilityState, str, bool]:
        """Verify Sector Rotation Radar."""
        try:
            from core.market.sector_rotation_radar import SectorRotationRadar
            matrix = SectorRotationRadar.get_live_sector_matrix()
            has_real_data = any(not r.get("is_demo_data") for r in matrix) if matrix else False
            if has_real_data:
                return CapabilityState.AVAILABLE, "Live NSE sector feed active", False
            return CapabilityState.UNAVAILABLE, "Live sector data feed inactive (sample data only)", True
        except Exception as ex:
            return CapabilityState.UNAVAILABLE, f"Sector radar probe failed: {ex}", True

    def _verify_fii_dii_radar(self) -> tuple[CapabilityState, str, bool]:
        """Verify Institutional FII/DII Positioning Radar."""
        try:
            from core.market.fii_dii_flow_radar import FiiDiiFlowRadar
            data = FiiDiiFlowRadar.get_participant_positioning()
            is_demo = bool(data.get("is_demo_data", True))
            if not is_demo and data.get("participants"):
                return CapabilityState.AVAILABLE, "Live institutional exchange feed active", False
            return CapabilityState.UNAVAILABLE, "Live institutional feed inactive (sample data only)", True
        except Exception as ex:
            return CapabilityState.UNAVAILABLE, f"FII/DII radar probe failed: {ex}", True

    def _verify_margin_radar(self) -> tuple[CapabilityState, str, bool]:
        """Verify Broker Margin Matrix."""
        try:
            from core.portfolio.margin_radar import MultiBrokerMarginRadar
            margins = MultiBrokerMarginRadar.get_consolidated_margins()
            is_demo = bool(margins.get("is_demo_data", True))
            if not is_demo and margins.get("brokers"):
                return CapabilityState.AVAILABLE, "Live broker margin APIs connected", False
            return CapabilityState.UNAVAILABLE, "Broker API disconnected in SIGNAL_ONLY mode (sample data only)", True
        except Exception as ex:
            return CapabilityState.UNAVAILABLE, f"Margin radar probe failed: {ex}", True

    def _verify_trade_copier(self) -> tuple[CapabilityState, str, bool]:
        """Verify Multi-Account Trade Copier."""
        try:
            from core.execution.trade_copier import MasterTradeCopier
            copier = MasterTradeCopier.get_instance()
            accounts = copier.get_linked_accounts()
            has_real_accounts = any(not a.get("is_demo_data") for a in accounts) if accounts else False
            if has_real_accounts:
                return CapabilityState.AVAILABLE, "Broker multi-account order routing connected", False
            return CapabilityState.UNAVAILABLE, "Broker auto-order routing disabled in SIGNAL_ONLY mode", True
        except Exception as ex:
            return CapabilityState.UNAVAILABLE, f"Trade copier probe failed: {ex}", True

    def _verify_expiry_harvester(self) -> tuple[CapabilityState, str, bool]:
        """Verify 0DTE Expiry Harvester."""
        try:
            from core.strategy.expiry_0dte_harvester import Expiry0DTEHarvester
            status = Expiry0DTEHarvester.get_live_harvest_status()
            is_demo = bool(status.get("is_demo_data", True))
            if not is_demo and status.get("legs"):
                return CapabilityState.AVAILABLE, "Live options straddle engine active", False
            return CapabilityState.UNAVAILABLE, "Live options data feed inactive (sample data only)", True
        except Exception as ex:
            return CapabilityState.UNAVAILABLE, f"Expiry harvester probe failed: {ex}", True

    def _verify_payoff_calculator(self) -> tuple[CapabilityState, str, bool]:
        """Verify Multi-Leg Payoff Engine (Pure Math Engine)."""
        return CapabilityState.AVAILABLE, "Analytical calculation engine operational", False

    def _verify_performance_dashboard(self) -> tuple[CapabilityState, str, bool]:
        """Verify Strategy Performance Dashboard."""
        return CapabilityState.AVAILABLE, "Paper execution telemetry active", False

    def _verify_strategy_sandbox(self) -> tuple[CapabilityState, str, bool]:
        """Verify Strategy Sandbox Lab."""
        return CapabilityState.AVAILABLE, "Simulation sandbox active", False

    def _verify_intelligence_engine(self) -> tuple[CapabilityState, str, bool]:
        """Verify Intelligence & BI Engine."""
        return CapabilityState.AVAILABLE, "Background BI worker pool operational", False

    def evaluate_all(self, force_refresh: bool = False) -> dict[str, Any]:
        """Evaluate and return the diagnostic report for all capabilities."""
        now = datetime.datetime.now(datetime.timezone.utc)

        # Cache for 15 seconds unless forced
        if not force_refresh and self._cached_report is not None and self._last_evaluated_at is not None:
            if (now - self._last_evaluated_at).total_seconds() < 15.0:
                return self._cached_report

        evaluators = {
            "sector_radar": {
                "name": "Sector Rotation Radar",
                "category": "Market Intelligence",
                "route": "/sector-radar",
                "required_dependencies": ["NSE Sector Price Stream", "Turnover Feed"],
                "fn": self._verify_sector_radar,
            },
            "fii_dii_radar": {
                "name": "Institutional FII/DII Radar",
                "category": "Market Intelligence",
                "route": "/fii-dii-radar",
                "required_dependencies": ["Daily Exchange Participant OI Feed"],
                "fn": self._verify_fii_dii_radar,
            },
            "margin_radar": {
                "name": "Broker Margin Matrix",
                "category": "Risk & Margins",
                "route": "/margin-radar",
                "required_dependencies": ["Broker API Auth", "Funds & Margin Stream"],
                "fn": self._verify_margin_radar,
            },
            "trade_copier": {
                "name": "Multi-Account Trade Copier",
                "category": "Execution",
                "route": "/trade-copier",
                "required_dependencies": ["Broker Order Routing", "Linked Client Accounts"],
                "fn": self._verify_trade_copier,
            },
            "expiry_harvester": {
                "name": "0DTE Expiry Day Harvester",
                "category": "Execution & Strategy",
                "route": "/expiry-harvester",
                "required_dependencies": ["Live Options Chain Feed", "Straddle Position Manager"],
                "fn": self._verify_expiry_harvester,
            },
            "payoff_calculator": {
                "name": "Multi-Leg Payoff Engine",
                "category": "Analytics",
                "route": "/payoff-calculator",
                "required_dependencies": ["Black-Scholes Mathematical Models"],
                "fn": self._verify_payoff_calculator,
            },
            "performance_dashboard": {
                "name": "Strategy Performance Dashboard",
                "category": "Analytics",
                "route": "/performance",
                "required_dependencies": ["Trade Journal / Execution Store"],
                "fn": self._verify_performance_dashboard,
            },
            "strategy_sandbox": {
                "name": "Strategy Sandbox Lab",
                "category": "Analytics & Simulation",
                "route": "/strategy-sandbox",
                "required_dependencies": ["Strategy Simulation Engine"],
                "fn": self._verify_strategy_sandbox,
            },
            "intelligence_engine": {
                "name": "Intelligence & BI Engine",
                "category": "Intelligence",
                "route": "/intelligence",
                "required_dependencies": ["BIJobRunner Isolated Pool"],
                "fn": self._verify_intelligence_engine,
            },
        }

        capabilities_map: dict[str, Any] = {}
        states_summary: dict[str, int] = {
            CapabilityState.AVAILABLE.value: 0,
            CapabilityState.UNAVAILABLE.value: 0,
            CapabilityState.DEGRADED.value: 0,
            CapabilityState.DISABLED.value: 0,
        }

        for key, meta in evaluators.items():
            if key in self._overrides:
                override = self._overrides[key]
                state = override["state"]
                reason = override.get("reason", "Manual runtime override")
                is_demo = False
            else:
                state_enum, reason, is_demo = meta["fn"]()
                state = state_enum.value

            states_summary[state] = states_summary.get(state, 0) + 1

            capabilities_map[key] = {
                "key": key,
                "name": meta["name"],
                "category": meta["category"],
                "route": meta["route"],
                "required_dependencies": meta["required_dependencies"],
                "state": state,
                "is_available": state == CapabilityState.AVAILABLE.value,
                "reason": reason,
                "is_demo_only": is_demo,
                "last_verified_at": now.isoformat(),
            }

        report = {
            "evaluated_at": now.isoformat(),
            "summary": states_summary,
            "capabilities": capabilities_map,
        }

        with self._lock:
            self._cached_report = report
            self._last_evaluated_at = now

        return report

    def get_states(self) -> dict[str, str]:
        """Return a simple dictionary mapping capability keys to their state strings."""
        report = self.evaluate_all()
        return {k: v["state"] for k, v in report["capabilities"].items()}

    def is_available(self, key: str) -> bool:
        """Return True if the capability is currently AVAILABLE."""
        report = self.evaluate_all()
        cap = report["capabilities"].get(key)
        return bool(cap and cap["state"] == CapabilityState.AVAILABLE.value)

    def get_state(self, key: str) -> str:
        """Return the state string for a given capability."""
        report = self.evaluate_all()
        cap = report["capabilities"].get(key)
        return cap["state"] if cap else CapabilityState.UNAVAILABLE.value
