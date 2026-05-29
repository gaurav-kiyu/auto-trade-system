"""
Legacy RiskEngine Adapter — wraps RiskPort (RiskService) with the old RiskEngine interface.

This adapter allows the deprecated core/orchestrator.py to continue working
without importing from the deprecated core/risk_engine.py module.

ARCHITECTURE:
    The canonical risk path is:  RiskPort  →  RiskService  →  evaluate_trade()
    This adapter adds backward-compatible shim methods (quality_check, loss_streak_check)
    so callers migrating from legacy RiskEngine can do so incrementally.

Will be removed alongside orchestrator.py in v2.55.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.ports.risk.risk_port import RiskEvaluation, RiskPort
from core.safety_state import get_consecutive_losses

# ── Backward-compatible types matching the old RiskEngine interface ──────────


@dataclass(frozen=True)
class RiskConfig:
    """Backward-compatible risk configuration matching the old RiskEngine interface."""
    min_volume_ratio:        float = 0.0
    max_spread_pct:          float = 1.0
    max_slippage_pct:        float = 1.0
    portfolio_risk_cap_pct:  float = 0.75
    max_consecutive_losses:  int   = 3
    max_api_latency_ms:      int   = 2000


@dataclass(frozen=True)
class RiskDecision:
    """Backward-compatible risk decision result matching the old RiskEngine interface."""
    allowed: bool
    reason: str = ""


class RiskPortAdapter:
    """
    Adapter that wraps a RiskPort (RiskService) with the legacy RiskEngine interface.

    Provides quality_check(), loss_streak_check(), latency_ok() methods
    that the orchestrator expects, backed by RiskService/RiskPort calls.
    """

    def __init__(
        self,
        risk_service: RiskPort,
        *,
        min_volume_ratio: float = 0.0,
        max_spread_pct: float = 1.0,
        max_slippage_pct: float = 1.0,
        max_consecutive_losses: int = 3,
        max_api_latency_ms: int = 2000,
        get_daily_pnl_fn: Callable[[], float] | None = None,
    ) -> None:
        self._risk_service = risk_service
        self._min_volume_ratio = min_volume_ratio
        self._max_spread_pct = max_spread_pct
        self._max_slippage_pct = max_slippage_pct
        self._max_consecutive_losses = max_consecutive_losses
        self._max_api_latency_ms = max_api_latency_ms
        self._get_daily_pnl_fn = get_daily_pnl_fn

    # ── Backward-compatible interface (mirrors old RiskEngine API) ──────────

    def quality_check(
        self,
        *,
        volume_ratio: float | None = None,
        spread_pct: float | None = None,
        slippage_pct: float | None = None,
    ) -> RiskDecision:
        """Check entry quality thresholds (volume, spread, slippage)."""
        if volume_ratio is not None and volume_ratio < self._min_volume_ratio:
            return RiskDecision(False, f"low volume {volume_ratio:.2f}x < {self._min_volume_ratio:.2f}x")
        if spread_pct is not None and spread_pct > self._max_spread_pct:
            return RiskDecision(False, f"spread {spread_pct*100:.2f}% > {self._max_spread_pct*100:.2f}%")
        if slippage_pct is not None and slippage_pct > self._max_slippage_pct:
            return RiskDecision(False, f"slippage {slippage_pct*100:.2f}% > {self._max_slippage_pct*100:.2f}%")
        return RiskDecision(True, "")

    def loss_streak_check(self) -> RiskDecision:
        """Check if consecutive loss limit is breached."""
        streak = get_consecutive_losses()
        if streak >= self._max_consecutive_losses:
            return RiskDecision(False, f"loss streak {streak} >= {self._max_consecutive_losses}")
        return RiskDecision(True, "")

    def latency_ok(self, start_ts: float) -> bool:
        """Check if API latency is within limits."""
        elapsed_ms = (time.time() - start_ts) * 1000
        return elapsed_ms <= self._max_api_latency_ms

    # ── Forwarded RiskPort methods (for completeness) ───────────────────────

    def evaluate_trade(
        self,
        symbol: str,
        signal_data: dict[str, Any],
        portfolio_metrics: Any,
    ) -> RiskEvaluation:
        """Forward to RiskService.evaluate_trade()."""
        return self._risk_service.evaluate_trade(symbol, signal_data, portfolio_metrics)

    def get_position_size(self, name: str, ltp: float, vix: float = 0.0) -> int:
        """Get position size via RiskService sizing (backward-compat name)."""
        try:
            metrics = self._risk_service.get_portfolio_risk_metrics()
            from core.ports.risk.risk_port import PositionSizingInput
            sizing_input = PositionSizingInput(
                symbol=name,
                entry_price=ltp,
                stop_loss_price=ltp * 0.95,
                capital_available=metrics.available_capital,
                risk_per_trade=0.02,
                lot_size=50,
                volatility=vix,
            )
            return self._risk_service.calculate_position_size(sizing_input)
        except Exception:
            return 0

    def current_loss_streak(self) -> int:
        """Get current consecutive loss count."""
        return get_consecutive_losses()

    def portfolio_risk_rupees(self) -> float:
        """Get current portfolio risk in rupees."""
        try:
            metrics = self._risk_service.get_portfolio_risk_metrics()
            return metrics.used_capital
        except Exception:
            return 0.0

    def get_portfolio_risk_metrics(self) -> Any:
        """Forward to RiskService.get_portfolio_risk_metrics()."""
        return self._risk_service.get_portfolio_risk_metrics()

    def health_check(self) -> dict[str, Any]:
        """Forward to RiskService.health_check()."""
        return self._risk_service.health_check()
