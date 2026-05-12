"""
Build a :class:`core.Orchestrator` wired to the live index bot engines.

The production main loop still uses the legacy path in :mod:`index_app.index_trader`;
this factory supports tests, tooling, and a gradual migration toward cycle-based flow.

Environment:

- ``OPB_ORCHESTRATOR_MARKET_HOURS`` — if ``0``/``false``/``no``/``off``, the orchestrator
  does not gate on NSE cash hours (useful for backtests and CI). Default: enforce IST session.
"""
from __future__ import annotations

import os
from typing import Any


def build_index_orchestrator():
    """Return an :class:`~core.Orchestrator` after engines exist (post-``_init_runtime_engines()``)."""
    import index_app.index_trader as m

    from core import Orchestrator, ReconciliationEngine, RiskEngineV2

    if m.DATA_ENGINE is None or m.STRATEGY_ENGINE is None or m.RISK_ENGINE is None:
        raise RuntimeError("Engines not initialized — call build_index_orchestrator() after _init_runtime_engines().")

    recon = ReconciliationEngine(broker_snapshot_fn=m._broker_positions_snapshot)

    def _risk_v2_state() -> dict:
        with m._pos_lock:
            n_open = len(m.positions)
        with m._state_lock:
            ndp = m.S.net_daily_pnl
            tc = m.S.trade_count
        with m._last_entry_ts_lock:
            last_ts = dict(m._last_entry_ts)
        return {
            "daily_pnl": float(ndp),
            "open_positions": int(n_open),
            "trade_count": int(tc),
            "last_trade_time": last_ts,
        }

    risk_v2 = RiskEngineV2(
        {
            "risk": {
                "max_daily_loss": float(m.MAX_DAILY_LOSS),
                "max_open": int(m.MAX_OPEN),
                "max_trades_day": int(m.EXPIRY_MAX_TRADES),
            },
            "timing": {"cooldown": int(m.COOLDOWN)},
        },
        _risk_v2_state,
    )

    def _names() -> list[str]:
        return list(m.INDEX_PRIORITY)

    def _exec_mode() -> str:
        return m._execution_mode_label()

    def _entry_gate(_name: str, _signal: dict[str, Any]) -> bool:
        return True

    _mh = os.environ.get("OPB_ORCHESTRATOR_MARKET_HOURS", "1").strip().lower()
    enforce_ist = _mh not in ("0", "false", "no", "off")

    return Orchestrator(
        data_engine=m.DATA_ENGINE,
        strategy_engine=m.STRATEGY_ENGINE,
        risk_engine=m.RISK_ENGINE,
        execution_engine=m.EXECUTION_ENGINE,
        state_manager=m.STATE_MANAGER,
        reconciliation_engine=recon,
        local_positions_fn=m._local_positions_snapshot,
        risk_engine_v2=risk_v2,
        enforce_market_hours=enforce_ist,
        names_provider=_names,
        entry_gate_fn=_entry_gate,
        execution_mode_fn=_exec_mode,
        market_vix_fn=m.get_india_vix,
        audit_engine=getattr(m, "_AUDIT_ENGINE", None),
    )
