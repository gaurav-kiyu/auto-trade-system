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
    from core import Orchestrator, ReconciliationEngine

    import index_app.index_trader as m

    if m.DATA_ENGINE is None or m.STRATEGY_ENGINE is None or m.RISK_ENGINE is None:
        raise RuntimeError("Engines not initialized — call build_index_orchestrator() after _init_runtime_engines().")

    recon = ReconciliationEngine(broker_snapshot_fn=m._broker_positions_snapshot)

    def _names() -> list[str]:
        return list(m.INDEX_PRIORITY)

    def _exec_mode() -> str:
        return m._execution_mode_label()

    def _entry_gate(_name: str, _signal: dict[str, Any]) -> bool:
        # Block entry if hard halt, intraday loss, or kill file detected
        from core.safety_state import check_intraday_pnl_and_halt, check_kill_file_and_halt, is_hard_halted
        check_kill_file_and_halt()
        if is_hard_halted():
            return False
        check_intraday_pnl_and_halt(source="orchestrator_entry_gate")
        return not is_hard_halted()

    def _system_mode() -> str:
        try:
            from core.system_mode import get_system_mode_manager
            mgr = get_system_mode_manager()
            return str(mgr.get_current_mode())
        except Exception:
            return "NORMAL"

    def _circuit_breaker_allows() -> bool:
        try:
            from core.circuit_breaker_detector import create_circuit_breaker_detector
            cb = create_circuit_breaker_detector()
            return cb.is_trading_allowed() if hasattr(cb, 'is_trading_allowed') else True
        except Exception:
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
        enforce_market_hours=enforce_ist,
        names_provider=_names,
        entry_gate_fn=_entry_gate,
        execution_mode_fn=_exec_mode,
        market_vix_fn=m.get_india_vix,
        audit_engine=getattr(m, "_AUDIT_ENGINE", None),
        system_mode_fn=_system_mode,
        circuit_breaker_fn=_circuit_breaker_allows,
    )
