"""
Risk Engine V2 — DEPRECATED.

This module has been consolidated into ``core.risk_engine`` (RiskEngine class).

The unified RiskEngine now provides:
  - quality_check()   — v1 entry-quality checks (volume, spread, slippage)
  - loss_streak_check() — v1 consecutive loss guard
  - evaluate()         — v2 capital/drawdown/cooldown/position checks (single call)

Importing from this module is deprecated and will be removed in v3.0.
"""
from __future__ import annotations

import warnings
from typing import Any

from core.risk_engine import RiskEngine, RiskEngineV2Config

warnings.warn(
    "risk_engine_v2 is deprecated. Use core.risk_engine.RiskEngine instead.",
    DeprecationWarning,
    stacklevel=2,
)


class RiskEngineV2(RiskEngine):
    """
    Deprecated alias for the unified RiskEngine.
    Use ``core.risk_engine.RiskEngine`` instead.

    The old ``RiskEngineV2.evaluate()`` is available as
    ``core.risk_engine.evaluate_risk()``.
    """

    def __init__(self, config: dict[str, Any], get_state_fn: Any) -> None:
        v2_cfg = RiskEngineV2Config(
            max_daily_loss=float(config.get("risk", {}).get("max_daily_loss", -400)),
            max_open=int(config.get("risk", {}).get("max_open", 1)),
            max_trades_day=int(config.get("risk", {}).get("max_trades_day", 2)),
            cooldown_seconds=int(config.get("timing", {}).get("cooldown", 300)),
        )
        super().__init__(v2_config=v2_cfg, get_state_fn=get_state_fn)

    def evaluate(self, symbol: str) -> dict[str, Any]:
        result = super().evaluate(symbol)
        return {"allowed": result.allowed, "reason": result.reason}
