from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

from .audit_engine import AuditEngine
from .data_engine import DataEngine, MarketDataSnapshot
from .datetime_ist import is_nse_cash_session
from .execution_engine import ExecutionEngine, ExecutionFill, ExecutionResult
from .reconciliation_engine import ReconciliationEngine, ReconciliationReport
from .risk_engine import RiskDecision, RiskEngine
from .safety_engine import SafetyContext, SafetyDecision, SafetyEngine
from .state_manager import StateManager
from .strategy_engine import StrategyEngine


@dataclass(frozen=True)
class OrchestratorSignal:
    name: str
    signal: dict[str, Any]
    risk: RiskDecision
    safety: SafetyDecision | None = None
    executed: bool = False
    execution_result: ExecutionResult | None = None
    execution_fill: ExecutionFill | None = None


@dataclass(frozen=True)
class OrchestratorCycle:
    snapshot: MarketDataSnapshot
    signals: list[OrchestratorSignal]
    reconciliation: ReconciliationReport | None
    saved: bool
    note: str = ""


class Orchestrator:
    """Conductor for one trading cycle using the existing engine boundaries."""

    def __init__(
        self,
        *,
        data_engine: DataEngine,
        strategy_engine: StrategyEngine,
        risk_engine: RiskEngine,
        execution_engine: ExecutionEngine | None,
        state_manager: StateManager,
        reconciliation_engine: ReconciliationEngine | None = None,
        names_provider: Callable[[], list[str]] | None = None,
        entry_gate_fn: Callable[[str, dict[str, Any]], bool] | None = None,
        execution_mode_fn: Callable[[], str] | None = None,
        market_vix_fn: Callable[[], float] | None = None,
        order_builder_fn: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        safety_engine: SafetyEngine | None = None,
        safety_context_fn: Callable[[MarketDataSnapshot], SafetyContext] | None = None,
        audit_engine: AuditEngine | None = None,
        now_fn: Callable[[], float] | None = None,
        local_positions_fn: Callable[[], dict[str, Any]] | None = None,
        risk_engine_v2: RiskEngineV2 | None = None,
        enforce_market_hours: bool = False,
        market_hours_fn: Callable[[], bool] | None = None,
        system_mode_fn: Callable[[], str] | None = None,
        circuit_breaker_fn: Callable[[], bool] | None = None,
        idempotency_check_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._data_engine = data_engine
        self._strategy_engine = strategy_engine
        self._risk_engine = risk_engine
        self._execution_engine = execution_engine
        self._state_manager = state_manager
        self._reconciliation_engine = reconciliation_engine
        self._names_provider = names_provider or (lambda: [])
        self._entry_gate_fn = entry_gate_fn or (lambda name, signal: True)
        self._execution_mode_fn = execution_mode_fn or (lambda: "MANUAL")
        self._market_vix_fn = market_vix_fn or (lambda: 0.0)
        self._order_builder_fn = order_builder_fn or self._default_order_builder
        self._safety_engine = safety_engine
        self._safety_context_fn = safety_context_fn or (lambda snapshot: SafetyContext(data_healthy=snapshot.healthy))
        self._audit_engine = audit_engine
        self._now_fn = now_fn or time.time
        self._local_positions_fn = local_positions_fn
        self._risk_engine_v2 = risk_engine_v2
        self._enforce_market_hours = bool(enforce_market_hours)
        self._market_hours_fn = market_hours_fn or is_nse_cash_session
        self._system_mode_fn = system_mode_fn
        self._circuit_breaker_fn = circuit_breaker_fn
        self._idempotency_check_fn = idempotency_check_fn

    def _capture(self, payload: dict[str, Any]) -> None:
        _log.warning("ORCHESTRATOR: %s", payload.get("event", "unknown"))

    @staticmethod
    def _default_order_builder(name: str, signal: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": name,
            "direction": str(signal.get("direction") or "CALL"),
            "qty": int(signal.get("qty") or 1),
            "strike": int(signal.get("strike") or 0),
        }

    def run_cycle(self) -> OrchestratorCycle:
        from core.safety_state import check_kill_file_and_halt
        check_kill_file_and_halt()
        names = list(self._names_provider() or [])
        snapshot = self._data_engine.fetch_market_snapshot(names)
        signals: list[OrchestratorSignal] = []
        reconciliation: ReconciliationReport | None = None

        outside_hours = self._enforce_market_hours and not bool(self._market_hours_fn())
        if snapshot.healthy and not outside_hours:
            vix = float(self._market_vix_fn() or 0.0)
            safety = self._safety_engine.evaluate(self._safety_context_fn(snapshot)) if self._safety_engine else SafetyDecision(True, "")
            for name in names:
                frames = snapshot.frames.get(name) if isinstance(snapshot.frames, dict) else None
                if not frames:
                    continue
                signal = self._strategy_engine.generate_signal(name, frames, vix=vix)
                if not signal:
                    continue
                quality = self._risk_engine.quality_check(volume_ratio=float(signal.get("vol_ratio") or 0.0))
                streak = self._risk_engine.loss_streak_check()
                latency = RiskDecision(self._risk_engine.latency_ok(self._now_fn()), "latency gate failed")
                allowed = quality
                if allowed.allowed:
                    allowed = streak
                if allowed.allowed and not latency.allowed:
                    allowed = latency
                if allowed.allowed and not safety.allowed:
                    allowed = RiskDecision(False, safety.reason)

                if allowed.allowed and self._risk_engine_v2:
                    v2 = self._risk_engine_v2.evaluate(name)
                    if not v2.get("allowed", True):
                        allowed = RiskDecision(False, str(v2.get("reason") or "risk v2 gate"))

                execution_result: ExecutionResult | None = None
                execution_fill: ExecutionFill | None = None
                executed = False
                mode = str(self._execution_mode_fn() or "MANUAL").upper()
                if allowed.allowed and mode == "AUTO" and self._execution_engine and self._entry_gate_fn(name, signal):
                    # System mode gate: block if system is halted/degraded/broker_down
                    if self._system_mode_fn:
                        system_mode = self._system_mode_fn()
                        if system_mode in ("BROKER_DOWN", "SAFE_MODE", "MARKET_HALTED"):
                            self._capture({"event": "system_mode_blocked", "symbol": name, "mode": system_mode})
                            allowed = RiskDecision(False, f"SYSTEM_MODE_BLOCKED: {system_mode}")

                    # Circuit breaker gate: block if market-wide circuit breaker triggered
                    if allowed.allowed and self._circuit_breaker_fn:
                        if not self._circuit_breaker_fn():
                            self._capture({"event": "circuit_breaker_blocked", "symbol": name})
                            allowed = RiskDecision(False, "CIRCUIT_BREAKER_ACTIVE")

                    order = self._order_builder_fn(name, signal)
                    intent_id = str(order.get("intent_id") or f"{name}_{int(time.time())}")
                    execution_result = self._execution_engine.place_order(
                        name=str(order.get("name") or name),
                        direction=str(order.get("direction") or signal.get("direction") or "CALL"),
                        qty=int(order.get("qty") or 1),
                        strike=int(order.get("strike") or 0),
                        intent_id=intent_id,
                    )
                    if execution_result and execution_result.ok and execution_result.order_id:
                        execution_fill = self._execution_engine.verify_fill(str(execution_result.order_id))
                        executed = bool(execution_fill.ok)
                    else:
                        executed = False
                signals.append(
                    OrchestratorSignal(
                        name=name,
                        signal=dict(signal),
                        risk=allowed,
                        safety=safety,
                        executed=executed,
                        execution_result=execution_result,
                        execution_fill=execution_fill,
                    )
                )
                if self._audit_engine:
                    audit_payload: dict[str, Any] = {
                        "symbol": name,
                        "allowed": allowed.allowed,
                        "reason": allowed.reason,
                        "executed": executed,
                        "execution_mode": mode,
                    }
                    if execution_fill is not None:
                        audit_payload["fill_ok"] = execution_fill.ok
                        audit_payload["filled_qty"] = execution_fill.filled_qty
                        audit_payload["fill_price"] = execution_fill.fill_price
                        audit_payload["fill_verified"] = execution_fill.status_verified
                        if execution_fill.reason:
                            audit_payload["fill_reason"] = execution_fill.reason
                    if execution_result and execution_result.order_id:
                        audit_payload["order_id"] = execution_result.order_id
                    self._audit_engine.record("orchestrator_signal", **audit_payload)

        if self._reconciliation_engine:
            local_positions: dict[str, dict[str, Any]] = {}
            if self._local_positions_fn:
                try:
                    raw_local = self._local_positions_fn() or {}
                except Exception:
                    raw_local = {}
                if isinstance(raw_local, dict):
                    for sym, row in raw_local.items():
                        if not isinstance(row, dict):
                            continue
                        try:
                            local_positions[str(sym)] = {
                                "qty": int(row.get("qty") or row.get("quantity") or 0),
                                "entry": float(row.get("entry") or row.get("avg_price") or row.get("average_price") or 0.0),
                            }
                        except Exception:
                            continue
            reconciliation = self._reconciliation_engine.reconcile_positions(local_positions)

        self._state_manager.save()
        if self._audit_engine:
            cycle_note = snapshot.note if not snapshot.healthy else ("outside_hours" if outside_hours else "ok")
            self._audit_engine.record(
                "orchestrator_cycle",
                symbols=names,
                healthy=snapshot.healthy,
                signal_count=len(signals),
                note=cycle_note,
            )
        if not snapshot.healthy:
            note = snapshot.note
        elif outside_hours:
            note = "skipped — outside NSE session hours (IST)"
        else:
            note = f"processed {len(signals)} signal(s)"
        return OrchestratorCycle(snapshot=snapshot, signals=signals, reconciliation=reconciliation, saved=True, note=note)
