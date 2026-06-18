from __future__ import annotations

import logging
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

# ── DEPRECATED MODULE (REMOVAL TARGET v3.1) ────────────────────────
# This module is the legacy synchronous Orchestrator. It MUST NOT be used
# for new development.
#
# MIGRATION PATH:
#   1. core/services/use_cases/trading_orchestrator.py (TradingOrchestrator)
#      — Complete trading lifecycle from market data to notifications.
#   2. core/services/execution_service.py (ExecutionService)
#      — Order execution with deterministic state machine + idempotency.
#   3. core/execution/deterministic_state_machine.py (ExecutionStateMachine)
#      — Low-level order state machine with exactly-once guarantees.
#
# This module uses the port-based ExecutionService for order execution.
#
# See core/services/use_cases/trading_orchestrator.py for a reference
# implementation of the port-based execution path.
#
# This module will be removed in v3.1.
warnings.warn(
    "core/orchestrator.py is DEPRECATED (removal target v3.1). "
    "Use core/services/use_cases/trading_orchestrator.py "
    "(TradingOrchestrator) instead.",
    FutureWarning,
    stacklevel=2,
)

from .audit_engine import AuditEngine
from .data_engine import DataEngine, MarketDataSnapshot
from .datetime_ist import is_nse_cash_session
from .reconciliation_engine import ReconciliationEngine, ReconciliationReport
from .risk.legacy_adapter import RiskDecision, RiskPortAdapter
from .safety_engine import SafetyContext, SafetyDecision, SafetyEngine
from .state_manager import StateManager
from .strategy_engine import StrategyEngine


# ── Local execution dataclasses (formerly mirrored from the removed execution_engine) ──


@dataclass(frozen=True)
class _ExecutionFill:
    """Local dataclass for order fill info (formerly mirrored from the removed core.execution_engine).

    This is a frozen dataclass used by the Orchestrator to report fill status.
    """
    ok: bool
    filled_qty: int = 0
    fill_price: float | None = None
    status_verified: bool = False
    reason: str = ""


@dataclass(frozen=True)
class _ExecutionResult:
    """Local dataclass for order execution result (formerly mirrored from the removed core.execution_engine).

    This is a frozen dataclass used by the Orchestrator to report execution status.
    """
    ok: bool
    order_id: str | None = None
    broker_latency_ms: int = 0
    reason: str = ""


@dataclass(frozen=True)
class OrchestratorSignal:
    name: str
    signal: dict[str, Any]
    risk: RiskDecision
    safety: SafetyDecision | None = None
    executed: bool = False
    execution_result: _ExecutionResult | None = None
    execution_fill: _ExecutionFill | None = None


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
        risk_engine: RiskPortAdapter,
        execution_service: Any | None = None,
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
        enforce_market_hours: bool = False,
        market_hours_fn: Callable[[], bool] | None = None,
        system_mode_fn: Callable[[], str] | None = None,
        circuit_breaker_fn: Callable[[], bool] | None = None,
        idempotency_check_fn: Callable[[str], bool] | None = None,
    ) -> None:
        self._data_engine = data_engine
        self._strategy_engine = strategy_engine
        self._risk_engine = risk_engine
        # Port-based ExecutionService — see core/services/execution_service.py
        # Uses ExecutionService.execute_order() with OrderRequest/OrderResult
        self._execution_service: Any | None = execution_service
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

                execution_result: _ExecutionResult | None = None
                execution_fill: _ExecutionFill | None = None
                executed = False
                mode = str(self._execution_mode_fn() or "MANUAL").upper()
                # Safety gates (system_mode + circuit_breaker) fire regardless of executor
                executor_available = self._execution_service is not None
                if allowed.allowed and mode == "AUTO" and executor_available and self._entry_gate_fn(name, signal):
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

                    # Execute via ExecutionService (port-based path only)
                    if allowed.allowed and self._execution_service is not None:
                        order = self._order_builder_fn(name, signal)
                        intent_id = str(order.get("intent_id") or f"{name}_{int(time.time())}")
                        direction = str(order.get("direction") or signal.get("direction") or "CALL")
                        qty = int(order.get("qty") or 1)
                        strike = int(order.get("strike") or 0)

                        try:
                            from core.ports.execution.execution_port import (
                                ExecutionContext as ExCtx,
                                ExecutionMode as ExMode,
                                OrderRequest,
                                OrderType,
                                OrderStatus,
                            )
                            order_request = OrderRequest(
                                symbol=name,
                                direction=direction.upper(),
                                strike_price=float(strike),
                                lot_size=qty,
                                order_type=OrderType.MARKET,
                                strategy_id=signal.get("strategy_id", ""),
                                idempotency_key=intent_id,
                            )
                            exec_ctx = ExCtx(
                                execution_mode=ExMode.AUTOMATIC,
                                correlation_id=intent_id,
                            )
                            order_result = self._execution_service.execute_order(
                                order_request, exec_ctx
                            )
                            # Map OrderResult -> local _ExecutionResult / _ExecutionFill
                            ok = order_result.status in (
                                OrderStatus.FILLED,
                                OrderStatus.PARTIALLY_FILLED,
                                OrderStatus.SUBMITTED,
                            )
                            execution_result = _ExecutionResult(
                                ok=ok,
                                order_id=order_result.order_id or intent_id,
                                broker_latency_ms=0,
                                reason=order_result.reject_reason or "",
                            )
                            if ok and order_result.order_id:
                                fill_ok = order_result.status in (
                                    OrderStatus.FILLED,
                                    OrderStatus.PARTIALLY_FILLED,
                                )
                                execution_fill = _ExecutionFill(
                                    ok=fill_ok,
                                    filled_qty=order_result.filled_quantity or 0,
                                    fill_price=order_result.average_price or None,
                                    status_verified=True,
                                    reason="",
                                )
                                executed = fill_ok
                            else:
                                executed = False
                        except (ValueError, TypeError, ImportError, AttributeError) as exc:
                            _log.error("[ORCH] ExecutionService failed: %s", exc)
                            execution_result = _ExecutionResult(False, reason=str(exc))
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
                except (ValueError, TypeError, AttributeError):
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
                        except (ValueError, TypeError, KeyError):
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
            note = "skipped - outside NSE session hours (IST)"
        else:
            note = f"processed {len(signals)} signal(s)"
        return OrchestratorCycle(snapshot=snapshot, signals=signals, reconciliation=reconciliation, saved=True, note=note)
