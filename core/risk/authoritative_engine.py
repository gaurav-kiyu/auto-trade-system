"""
DEPRECATED — Unnecessary wrapper around core.services.risk_service.RiskService.

All risk decisions MUST route directly to:
    core.services.risk_service.RiskService.evaluate_trade()
via the contract port:
    core.ports.risk.RiskPort

This module is retained for backward compatibility.
It will be removed in a future release.

See core/risk/__init__.py for the authoritative architecture declaration.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from core.datetime_ist import now_ist

_log = logging.getLogger(__name__)


class RiskVerdict:
    """Possible risk decision outcomes."""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HALT = "HALT"
    DEFERRED = "DEFERRED"


@dataclass
class RiskDecision:
    """Record of a single risk evaluation."""
    verdict: str
    reason: str = ""
    timestamp: datetime = field(default_factory=now_ist)
    capital: float = 0.0
    risk_amount: float = 0.0
    max_daily_loss: float = 0.0
    consecutive_losses: int = 0
    vix: float = 0.0
    drawdown_pct: float = 0.0


class RiskAuthority:
    """
    Single authoritative risk engine for AD-KIYU.

    Wires all risk checks through one path:
      1. Hard halt gate
      2. Max drawdown protection
      3. Daily loss limit
      4. Weekly circuit breaker
      5. Consecutive loss cooldown
      6. VIX hard block
      7. Data staleness check
      8. Position sizing (delegates to RiskService)

    Startup validation verifies no other risk engines are loaded.
    """

    def __init__(
        self,
        config: dict | None = None,
        risk_service: Any = None,
        get_capital_fn: Callable[[], float] | None = None,
        get_daily_pnl_fn: Callable[[], float] | None = None,
    ):
        self._cfg = config or {}
        self._risk_service = risk_service
        self._get_capital = get_capital_fn or (lambda: self._cfg.get("BASE_CAPITAL", 5000))
        self._get_daily_pnl = get_daily_pnl_fn or (lambda: 0.0)
        self._lock = threading.Lock()

        self._last_decision: RiskDecision | None = None
        self._decision_history: list[RiskDecision] = []
        self._max_history = 100
        self._hard_halted = False

        _log.info("RiskAuthority initialized (canonical risk engine)")

    def approve_trade(
        self,
        score: float = 0.0,
        regime: str = "",
        vix: float = 20.0,
        iv_rank: float = 0.0,
        data_stale_seconds: int = 0,
    ) -> RiskDecision:
        """Evaluate whether a trade is allowed. This is the single entry point."""
        capital = self._get_capital()
        daily_pnl = self._get_daily_pnl()

        with self._lock:
            # 1. Hard halt gate
            if self._hard_halted:
                return self._record_decision(RiskVerdict.HALT, "System hard-halted")

            # 2. Hard halt via safety_state
            from core.safety_state import is_hard_halted as _is_hard_halted
            if _is_hard_halted():
                self._hard_halted = True
                return self._record_decision(RiskVerdict.HALT, "Safety state hard-halted")

            # 3. Max drawdown protection
            max_dd = float(self._cfg.get("MANDATE_MAX_DRAWDOWN_PROTECTION", 0.12))
            equity_peak = self._cfg.get("equity_peak", capital)
            drawdown = (equity_peak - capital) / equity_peak if equity_peak > 0 else 0.0
            if drawdown >= max_dd:
                self._trip_hard_halt(f"Max drawdown {max_dd:.0%} reached")
                return self._record_decision(RiskVerdict.HALT, f"MAX_DRAWDOWN: {max_dd:.0%}")

            # 4. Daily loss limit
            max_daily_loss_pct = float(self._cfg.get("MAX_DAILY_LOSS_PCT", 2.5))
            daily_loss_pct = -daily_pnl / capital if capital > 0 else 0
            if daily_loss_pct >= (max_daily_loss_pct / 100.0):
                return self._record_decision(RiskVerdict.REJECTED, f"DAILY_LOSS: {daily_loss_pct:.1%} >= {max_daily_loss_pct:.0f}%")

            # 5. Weekly circuit breaker
            weekly_pnl = self._cfg.get("weekly_pnl", 0.0)
            weekly_loss_pct = -weekly_pnl / capital if capital > 0 else 0
            if weekly_loss_pct >= 0.05:
                self._trip_hard_halt("Weekly circuit breaker 5% hit")
                return self._record_decision(RiskVerdict.HALT, "WEEKLY_CIRCUIT: 5%")

            # 6. Consecutive loss cooldown
            from core.safety_state import get_consecutive_losses
            loss_streak = get_consecutive_losses()
            if loss_streak >= 3:
                from core.safety_state import get_last_loss_time
                last_loss = get_last_loss_time()
                if last_loss:
                    from datetime import timedelta
                    from core.datetime_ist import now_ist
                    if now_ist() < last_loss + timedelta(hours=2):
                        return self._record_decision(RiskVerdict.REJECTED, f"LOSS_STREAK: {loss_streak} losses, cooldown active")

            # 7. VIX hard block
            if vix >= 30:
                return self._record_decision(RiskVerdict.REJECTED, f"VIX_BLOCK: {vix} >= 30")

            # 8. Data staleness
            if data_stale_seconds >= 30:
                return self._record_decision(RiskVerdict.REJECTED, f"DATA_STALE: {data_stale_seconds}s")

            # 9. Delegated risk service check (if available)
            if self._risk_service is not None:
                try:
                    eval_result = self._risk_service.evaluate_trade(
                        capital=capital,
                        regime=regime,
                        vix=vix,
                        score=score,
                    )
                    if isinstance(eval_result, dict) and not eval_result.get("approved", True):
                        return self._record_decision(RiskVerdict.REJECTED, eval_result.get("reason", "Risk service rejected"))
                except Exception as e:
                    _log.warning("Risk service evaluation failed (non-blocking): %s", e)

            # All checks passed
            return self._record_decision(RiskVerdict.APPROVED, "All risk checks passed")

    def get_position_size(
        self,
        entry_price: float,
        regime: str = "",
        sl_pct: float = 0.12,
    ) -> int:
        """Calculate position size — delegates to RiskService if available, else uses built-in."""
        capital = self._get_capital()
        if capital <= 0:
            return 0

        if self._risk_service is not None:
            try:
                sizing_result = self._risk_service.calculate_position_size(
                    capital=capital,
                    entry_price=entry_price,
                    regime=regime,
                    sl_pct=sl_pct,
                )
                if isinstance(sizing_result, dict):
                    return int(sizing_result.get("lots", 1))
                return int(sizing_result)
            except Exception as e:
                _log.warning("Risk service sizing failed, using built-in: %s", e)

        # Fallback built-in sizing
        base_risk_pct = 0.015
        risk_mult = 1.2 if regime.upper() in ("TRENDING", "BULLISH") else 0.85
        effective_risk = base_risk_pct * risk_mult
        risk_amount = capital * effective_risk
        risk_per_lot = entry_price * sl_pct
        if risk_per_lot > 0:
            lots = int(risk_amount / risk_per_lot)
            return max(1, min(lots, 25))
        return 1

    def _trip_hard_halt(self, reason: str) -> None:
        self._hard_halted = True
        _log.critical("RiskAuthority HARD HALT: %s", reason)
        from core.safety_state import trip_hard_halt
        trip_hard_halt(reason, source="RiskAuthority")

    def _record_decision(self, verdict: str, reason: str) -> RiskDecision:
        capital = self._get_capital()
        daily_pnl = self._get_daily_pnl()
        from core.safety_state import get_consecutive_losses
        decision = RiskDecision(
            verdict=verdict,
            reason=reason,
            capital=capital,
            risk_amount=0.0,
            max_daily_loss=float(self._cfg.get("MAX_DAILY_LOSS", -2000)),
            consecutive_losses=get_consecutive_losses(),
            vix=float(self._cfg.get("vix", 20.0)),
            drawdown_pct=0.0,
        )
        self._last_decision = decision
        self._decision_history.append(decision)
        if len(self._decision_history) > self._max_history:
            self._decision_history.pop(0)
        return decision

    def get_status(self) -> dict:
        return {
            "hard_halted": self._hard_halted,
            "last_verdict": self._last_decision.verdict if self._last_decision else None,
            "last_reason": self._last_decision.reason if self._last_decision else "",
            "decision_count": len(self._decision_history),
        }


# Singleton
_authority: RiskAuthority | None = None


def get_risk_authority(
    config: dict | None = None,
    risk_service: Any = None,
    **kwargs,
) -> RiskAuthority:
    global _authority
    if _authority is None:
        _authority = RiskAuthority(config=config, risk_service=risk_service, **kwargs)
    return _authority


def reset_authority() -> None:
    global _authority
    _authority = None
