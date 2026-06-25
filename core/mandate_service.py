"""
Mandate Service - extracted from index_app/index_trader.py (GAP-05).

Consolidates trade mandate/risk checking, position sizing, and market status
into a single injectable service.  Reduces index_trader.py by ~200 lines.

Usage
-----
    from core.mandate_service import MandateService

    service = MandateService(
        cfg=_CFG,
        risk_service=_risk_service,
        warmup_manager=_warmup_manager,
        mandate_enforcer=_MANDATE_ENFORCER,
    )
    allowed, reason = service.check_mandate_trade_allowed("TRENDING", 85)
    qty = service.get_position_size("NIFTY", 180.0)
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


class MandateService:
    """Trade mandate, position sizing, and market status service.

    Encapsulates the risk/mandate checking logic that was previously
    scattered as module-level functions in index_trader.py.

    Dependencies
    ------------
    cfg              : dict          - Global config dict (``_CFG``)
    risk_service     : RiskService | None  - Canonical risk service
    warmup_manager   : MarketWarmup | None - Market warm-up throttle
    mandate_enforcer : MandateEnforcer | None - Legacy fallback enforcer
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        risk_service: Any | None = None,
        warmup_manager: Any | None = None,
        mandate_enforcer: Any | None = None,
        holidays: set[str] | None = None,
    ):
        self._cfg = cfg or {}
        self._risk_service = risk_service
        self._warmup_manager = warmup_manager
        self._mandate_enforcer = mandate_enforcer
        self._holidays = holidays or set()

    # ── Market Status ─────────────────────────────────────────────────────

    def market_status(self) -> str:
        """Return market status: OPEN / CLOSED / HOLIDAY.

        Independent of any service - only depends on time and holiday set.
        """
        try:
            now = now_ist()
            weekday = now.weekday()
            if weekday >= 5:
                return "CLOSED"
            today_str = now.strftime("%Y-%m-%d")
            if today_str in self._holidays:
                return "HOLIDAY"
            hour, minute = now.hour, now.minute
            mins = hour * 60 + minute
            if 555 <= mins <= 920:
                return "OPEN"
            return "CLOSED"
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _mkt_err:
            _log.warning("Market status check failed: %s - assuming OPEN", _mkt_err)
            return "OPEN"

    # ── Position Sizing ───────────────────────────────────────────────────

    def get_position_size(self, name: str, entry: float, vix: float = 0.0) -> int:
        """Risk-based position sizing via RiskService with legacy fallback.

        Args:
            name:  Symbol/index name.
            entry: Entry price (option premium).
            vix:   Current VIX level (optional).

        Returns:
            Recommended lot quantity.
        """
        sl_pct = float(self._cfg.get("SL_PCT", 0.92))

        if self._risk_service is not None:
            try:
                from core.ports.risk.risk_port import PositionSizingInput

                metrics = self._risk_service.get_portfolio_risk_metrics()
                sizing_input = PositionSizingInput(
                    symbol=name,
                    entry_price=entry,
                    stop_loss_price=entry * sl_pct,
                    capital_available=metrics.available_capital,
                    risk_per_trade=self._risk_service.config.default_risk_per_trade,
                    lot_size=self._risk_service._get_lot_size(name),
                    volatility=self._risk_service.get_live_vix(),
                )
                return int(self._risk_service.calculate_position_size(sizing_input))
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                _log.debug("RiskService position sizing failed - using fallback sizing")

        # Fallback to mandate enforcer
        if self._mandate_enforcer is not None:
            try:
                regime = "SIDEWAYS"
                sl_pct_val = 1.0 - sl_pct
                return int(self._mandate_enforcer.get_position_size(entry, regime, sl_pct_val))
            except (ValueError, TypeError, AttributeError, IndexError, OSError):
                _log.debug("Mandate enforcer fallback failed - returning 1")

        # Ultimate fallback
        return 1

    # ── Mandate Checks ────────────────────────────────────────────────────

    def check_mandate_trade_allowed(
        self,
        regime: str = "SIDEWAYS",
        score: int = 70,
        iv_rank: float = 25.0,
    ) -> tuple[bool, str]:
        """Consolidated trade entry gate via RiskService (replaces ProductionMandateEnforcer).

        Args:
            regime:  Market regime classification.
            score:   Signal score (0-100).
            iv_rank: IV rank percentile.

        Returns:
            (allowed: bool, reason: str)
        """
        if self._risk_service is not None:
            try:
                # 1. Check trading window (9:20-11:30, 13:00-14:45)
                if not self._risk_service.is_in_trading_window():
                    return False, "MANDATE_BLOCK: Outside trading window"

                # 2. Check skip first 20 min
                if self._risk_service.should_skip_first_20_min():
                    return False, "MANDATE_BLOCK: First 20 minutes"

                # 3. Check skip last 45 min
                if self._risk_service.should_skip_last_45_min():
                    return False, "MANDATE_BLOCK: Last 45 minutes"

                # 4. Check score threshold by regime
                min_score = self._risk_service.get_min_score_for_regime(regime)
                if self._warmup_manager is not None:
                    min_score += self._warmup_manager.score_threshold_adjustment()
                if score < min_score:
                    return False, f"MANDATE_BLOCK: Score {score} < {min_score} for {regime}"

                # 5. Check false signal filter
                if self._risk_service.should_block_false_signal(score, iv_rank):
                    return False, f"MANDATE_BLOCK: False signal (score={score}, iv={iv_rank})"

                # 6. Check max trades today via RiskService
                metrics = self._risk_service.get_portfolio_risk_metrics()
                daily_vix = self._risk_service.get_live_vix()
                max_trades = self._risk_service.get_max_trades_per_day(
                    daily_vix, metrics.consecutive_losses
                )
                trades_today = metrics.open_positions_count
                if trades_today >= max_trades:
                    return (
                        False,
                        f"MANDATE_BLOCK: Max trades today ({trades_today} >= {max_trades})",
                    )

                # 7. Check hard stop/VIX via health
                can_trade, reason = self._check_hard_stops_via_risk()
                if not can_trade:
                    return False, f"MANDATE_BLOCK: {reason}"

                return True, "MANDATE_ALLOWED"
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                _log.debug("RiskService mandate check failed - using legacy mandate enforcer")

        # Fallback to mandate enforcer
        if self._mandate_enforcer is not None:
            try:
                can_trade, reason = self._mandate_enforcer.can_trade()
                if not can_trade:
                    return False, f"MANDATE_BLOCK: {reason}"

                if not self._mandate_enforcer.is_in_trading_window():
                    return False, "MANDATE_BLOCK: Outside trading window"

                if self._mandate_enforcer.should_skip_first_20_min():
                    return False, "MANDATE_BLOCK: First 20 minutes"

                if self._mandate_enforcer.should_skip_last_45_min():
                    return False, "MANDATE_BLOCK: Last 45 minutes"

                min_score = self._mandate_enforcer.get_min_score(regime)
                if self._warmup_manager is not None:
                    min_score += self._warmup_manager.score_threshold_adjustment()
                if score < min_score:
                    return False, f"MANDATE_BLOCK: Score {score} < {min_score} for {regime}"

                if self._mandate_enforcer.should_block_false_signal(score, iv_rank):
                    return False, f"MANDATE_BLOCK: False signal (score={score}, iv={iv_rank})"

                status = self._mandate_enforcer.get_status()
                if status.get("trades_today", 0) >= status.get("max_trades_today", 99):
                    return False, "MANDATE_BLOCK: Max trades today reached"

                return True, "MANDATE_ALLOWED"
            except (ValueError, TypeError, AttributeError, IndexError, OSError):
                _log.debug("Mandate enforcer fallback failed - allowing trade")

        # No enforcer available - allow by default (fail-open for safety)
        return True, "MANDATE_ALLOWED (no enforcer)"

    def get_mandate_status(self) -> dict[str, Any]:
        """Current mandate/risk state.

        Returns:
            Dict with trades_today, max_trades_today, can_trade, viable_regimes.
        """
        if self._risk_service is not None:
            try:
                metrics = self._risk_service.get_portfolio_risk_metrics()
                return {
                    "trades_today": metrics.open_positions_count,
                    "max_trades_today": self._risk_service.get_max_trades_per_day(
                        self._risk_service.get_live_vix(),
                        metrics.consecutive_losses,
                    ),
                    "can_trade": metrics.open_positions_count
                    < self._risk_service.config.max_open_positions,
                    "viable_regimes": ["TRENDING", "BULLISH", "SIDEWAYS"],
                }
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                _log.debug("RiskService get_mandate_status failed - using legacy enforcer")

        if self._mandate_enforcer is not None:
            try:
                return self._mandate_enforcer.get_status()
            except (ValueError, TypeError, AttributeError, IndexError, OSError):
                _log.debug("Mandate enforcer fallback failed - returning defaults")

        return {
            "trades_today": 0,
            "max_trades_today": 99,
            "can_trade": True,
            "viable_regimes": ["TRENDING", "SIDEWAYS"],
        }

    # ── Wait Reasons ──────────────────────────────────────────────────────

    def get_wait_reason_components(self, sd: dict[str, Any] | None) -> tuple[str, list[str]]:
        """Analyse a signal dict and return wait reason + components.

        Args:
            sd: Signal dict (or None).

        Returns:
            (display: str, reasons: list[str])
        """
        reasons: list[str] = []
        if not isinstance(sd, dict):
            return "WAIT", []

        market_status_value = str(sd.get("market_status", "")).upper()
        if market_status_value and market_status_value != "OPEN":
            reasons.append("Market")

        score = sd.get("score")
        threshold = sd.get("threshold")
        if score is None or threshold is None:
            reasons.append("Score")
        elif score < threshold:
            reasons.append("Score")

            regime = str(sd.get("regime", "")).upper()
            adx = float(sd.get("adx", 999.0) or 999.0)
            if regime == "CHOPPY" or adx < 14.0:
                reasons.append("ADX")

            rr = float(sd.get("rr", 999.0) or 999.0)
            if rr < 1.5:
                reasons.append("RR")

            vix = float(sd.get("vix", 0.0) or 0.0)
            if vix > 27.0:
                reasons.append("VIX")

            mins_to_eod = float(sd.get("mins_to_eod", 999.0) or 999.0)
            if mins_to_eod < 40.0:
                reasons.append("EOD")

            cooldown_s = float(sd.get("cooldown_s", 0.0) or 0.0)
            if cooldown_s > 0.0:
                reasons.append("Cooldown")

        if not reasons:
            return "PASS", []

        display = ", ".join(reasons[:2])
        return f"WAIT: {display}", reasons

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_hard_stops_via_risk(self) -> tuple[bool, str]:
        """Check hard stops via RiskService."""
        if self._risk_service is not None:
            try:
                metrics = self._risk_service.get_portfolio_risk_metrics()
                if metrics.daily_pnl <= metrics.max_daily_loss:
                    return False, (
                        f"Daily loss limit: {metrics.daily_pnl:.2f} <= {metrics.max_daily_loss:.2f}"
                    )
                if metrics.consecutive_losses >= metrics.max_consecutive_losses:
                    return False, (
                        f"Consecutive losses: {metrics.consecutive_losses} "
                        f">= {metrics.max_consecutive_losses}"
                    )
                live_vix = self._risk_service.get_live_vix()
                if live_vix > 35:
                    return False, f"VIX too high: {live_vix:.1f} > 35"
                return True, "OK"
            except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as _risk_err:
                _log.debug("RiskService check_hard_stops failed (falling back to OK): %s", _risk_err)
        return True, "OK"


# ── Singleton factory ─────────────────────────────────────────────────────────

_mandate_service_instance: MandateService | None = None
_mandate_service_lock = threading.RLock()


def get_mandate_service(
    cfg: dict[str, Any] | None = None,
    risk_service: Any | None = None,
    warmup_manager: Any | None = None,
    mandate_enforcer: Any | None = None,
    holidays: set[str] | None = None,
) -> MandateService:
    """Return the process-level MandateService singleton."""
    global _mandate_service_instance
    with _mandate_service_lock:
        if _mandate_service_instance is None:
            _mandate_service_instance = MandateService(
            cfg=cfg,
            risk_service=risk_service,
            warmup_manager=warmup_manager,
            mandate_enforcer=mandate_enforcer,
            holidays=holidays,
        )
    return _mandate_service_instance


def reset_mandate_service() -> None:
    """Force-reset singleton (tests only)."""
    global _mandate_service_instance
    with _mandate_service_lock:
        _mandate_service_instance = None


__all__ = [
    "MandateService",
    "get_mandate_service",
    "reset_mandate_service",
]

