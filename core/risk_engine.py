"""
Risk Engine — Unified entry-quality, portfolio-risk, and capital management.

Consolidates:
  - risk_engine.py (v1 — QualityEngine pattern with injected callbacks)
  - risk_engine_v2.py (v2 — Dict-based RiskEngineV2 evaluates capital/drawdown/cooldown)

Usage:
    # Via DI container (preferred):
    engine = RiskEngine(config=RiskConfig(), ...)
    decision = engine.evaluate(symbol, ltp, vix)

    # Direct:
    from core.risk_engine import evaluate_risk
    result = evaluate_risk(state, config)
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.safety_state import trip_hard_halt, is_hard_halted

# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskConfig:
    """Base risk configuration (v1 quality checks)."""
    min_volume_ratio:      float = 0.0
    max_spread_pct:        float = 1.0
    max_slippage_pct:      float = 1.0
    portfolio_risk_cap_pct: float = 0.75
    max_consecutive_losses: int   = 3
    max_api_latency_ms:     int   = 2000


@dataclass
class RiskEngineV2Config:
    """Extended risk configuration (v2 capital/drawdown/cooldown checks)."""
    max_daily_loss:   float = -400.0
    max_open:         int   = 1
    max_trades_day:   int   = 2
    cooldown_seconds: int   = 300


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason:  str = ""


@dataclass(frozen=True)
class RiskEvalResult:
    """Consolidated risk evaluation result from all checks."""
    allowed:           bool
    reason:            str
    quality_ok:        bool   = True
    capital_ok:        bool   = True
    cooldown_ok:       bool   = True
    loss_streak_ok:    bool   = True
    latency_ok:        bool   = True
    daily_loss_ok:     bool   = True
    max_trades_ok:     bool   = True
    max_positions_ok:  bool   = True


# ── Unified RiskEngine (v1 + v2) ─────────────────────────────────────────────

class RiskEngine:
    """
    Unified risk engine combining entry-quality checks (v1) with
    capital/drawdown/cooldown checks (v2).

    Thread-safe: all mutable checks are confined to the evaluate() call.
    """

    def __init__(
        self,
        *,
        config: RiskConfig | None = None,
        v2_config: RiskEngineV2Config | None = None,
        position_size_fn: Callable[[str, float, float], int] | None = None,
        portfolio_risk_fn: Callable[[], float] | None = None,
        consecutive_loss_fn: Callable[[], int] | None = None,
        latency_check_fn: Callable[[float], bool] | None = None,
        get_state_fn: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.config      = config or RiskConfig()
        self.v2_config   = v2_config or RiskEngineV2Config()
        self._position_size_fn    = position_size_fn
        self._portfolio_risk_fn   = portfolio_risk_fn
        self._consecutive_loss_fn = consecutive_loss_fn
        self._latency_check_fn    = latency_check_fn
        self._get_state_fn        = get_state_fn

    # ── v1 methods ───────────────────────────────────────────────────────

    def get_position_size(self, name: str, ltp: float, vix: float = 0.0) -> int:
        if self._position_size_fn is None:
            return 0
        return int(self._position_size_fn(name, ltp, vix))

    def portfolio_risk_rupees(self) -> float:
        if self._portfolio_risk_fn is None:
            return 0.0
        return float(self._portfolio_risk_fn() or 0.0)

    def latency_ok(self, start_ts: float) -> bool:
        if not self._latency_check_fn:
            return True
        return bool(self._latency_check_fn(start_ts))

    def current_loss_streak(self) -> int:
        if not self._consecutive_loss_fn:
            return 0
        try:
            return max(0, int(self._consecutive_loss_fn()))
        except Exception:
            return 0

    def quality_check(
        self,
        *,
        volume_ratio: float | None = None,
        spread_pct: float | None = None,
        slippage_pct: float | None = None,
    ) -> RiskDecision:
        if volume_ratio is not None and volume_ratio < self.config.min_volume_ratio:
            return RiskDecision(False, f"low volume {volume_ratio:.2f}x < {self.config.min_volume_ratio:.2f}x")
        if spread_pct is not None and spread_pct > self.config.max_spread_pct:
            return RiskDecision(False, f"spread {spread_pct*100:.2f}% > {self.config.max_spread_pct*100:.2f}%")
        if slippage_pct is not None and slippage_pct > self.config.max_slippage_pct:
            return RiskDecision(False, f"slippage {slippage_pct*100:.2f}% > {self.config.max_slippage_pct*100:.2f}%")
        return RiskDecision(True, "")

    def loss_streak_check(self) -> RiskDecision:
        streak = self.current_loss_streak()
        if streak >= self.config.max_consecutive_losses:
            return RiskDecision(False, f"loss streak {streak} >= {self.config.max_consecutive_losses}")
        return RiskDecision(True, "")

    # ── v2 methods ───────────────────────────────────────────────────────

    def evaluate(self, symbol: str) -> RiskEvalResult:
        """
        Full risk evaluation (v1 + v2) for a given symbol.

        This is the primary entry point for the trading loop.
        """
        state = self._get_state_fn() if self._get_state_fn else {}
        failures: list[str] = []

        # v2 checks (capital/drawdown/cooldown)
        daily_pnl = float(state.get("daily_pnl", 0.0))
        daily_loss_ok = daily_pnl > self.v2_config.max_daily_loss
        if not daily_loss_ok:
            failures.append(f"max daily loss ({daily_pnl} <= {self.v2_config.max_daily_loss})")

        open_positions = int(state.get("open_positions", 0))
        max_positions_ok = open_positions < self.v2_config.max_open
        if not max_positions_ok:
            failures.append(f"max open ({open_positions}/{self.v2_config.max_open})")

        trades_today = int(state.get("trade_count", 0))
        max_trades_ok = trades_today < self.v2_config.max_trades_day
        if not max_trades_ok:
            failures.append(f"max trades today ({trades_today}/{self.v2_config.max_trades_day})")

        now = time.time()
        last_trade_time = float(state.get("last_trade_time", {}).get(symbol, 0) if isinstance(state.get("last_trade_time"), dict) else 0)
        cooldown_ok = (now - last_trade_time) >= self.v2_config.cooldown_seconds
        if not cooldown_ok:
            failures.append(f"cooldown ({int(now - last_trade_time)}s < {self.v2_config.cooldown_seconds}s)")

        # v1 checks
        loss_streak_ok = self.loss_streak_check().allowed
        quality_ok = self.quality_check().allowed
        latency_ok = True

        allowed = len(failures) == 0 and quality_ok and loss_streak_ok
        reason = "; ".join(failures) if failures else "within limits"

        return RiskEvalResult(
            allowed=allowed,
            reason=reason,
            quality_ok=quality_ok,
            capital_ok=daily_loss_ok,
            cooldown_ok=cooldown_ok,
            loss_streak_ok=loss_streak_ok,
            latency_ok=latency_ok,
            daily_loss_ok=daily_loss_ok,
            max_trades_ok=max_trades_ok,
            max_positions_ok=max_positions_ok,
        )


# ── Standalone evaluation function (backward-compatible with v2) ──────────────

def evaluate_risk(
    state: dict[str, Any],
    config: dict[str, Any],
    symbol: str = "",
) -> dict[str, Any]:
    """
    Standalone risk evaluation (backward-compatible with RiskEngineV2 API).

    Args:
        state:  Trader state dict with keys: daily_pnl, open_positions, trade_count, last_trade_time.
        config: Config dict with keys: risk.* and timing.*.
        symbol: Symbol to check cooldown for.

    Returns:
        {"allowed": bool, "reason": str}

    Example::

        >>> evaluate_risk({"daily_pnl": -500}, {"risk": {"max_daily_loss": -400}})
        {'allowed': False, 'reason': 'max daily loss (-500 <= -400)'}
    """
    risk_cfg = config.get("risk", {})
    timing_cfg = config.get("timing", {})

    max_daily_loss = float(risk_cfg.get("max_daily_loss", -400))
    daily_pnl = float(state.get("daily_pnl", 0.0))
    if daily_pnl <= max_daily_loss:
        trip_hard_halt(
            f"max daily loss breach: {daily_pnl} <= {max_daily_loss}",
            source="evaluate_risk",
        )
        return {"allowed": False, "reason": f"max daily loss ({daily_pnl} <= {max_daily_loss})"}

    max_open = int(risk_cfg.get("max_open", 1))
    open_positions = int(state.get("open_positions", 0))
    if open_positions >= max_open:
        return {"allowed": False, "reason": f"max open positions ({open_positions}/{max_open})"}

    max_trades = int(risk_cfg.get("max_trades_day", 2))
    trades_today = int(state.get("trade_count", 0))
    if trades_today >= max_trades:
        return {"allowed": False, "reason": f"max trades per day ({trades_today}/{max_trades})"}

    cooldown = int(timing_cfg.get("cooldown", 300))
    last_trade_time = float(state.get("last_trade_time", {}).get(symbol, 0) if isinstance(state.get("last_trade_time"), dict) else 0)
    now = time.time()
    if now - last_trade_time < cooldown:
        return {"allowed": False, "reason": f"in cooldown ({int(now - last_trade_time)}s < {cooldown}s)"}

    return {"allowed": True, "reason": "within limits"}
