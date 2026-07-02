"""
[DEPRECATED] Orchestrator — use core.services.use_cases.trading_orchestrator instead.

This module is a backward-compatibility wrapper. The ``Orchestrator`` class
is replaced by ``TradingOrchestrator`` (``core.services.use_cases.trading_orchestrator``).

.. deprecated:: 2.54.0
    Import from ``core.services.use_cases.trading_orchestrator`` (TradingOrchestrator)
    or ``core.strategy.orchestrator`` (StrategyOrchestrator) instead.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

warnings.warn(
    "core.orchestrator is DEPRECATED. "
    "Use core.services.use_cases.trading_orchestrator (TradingOrchestrator) instead.",
    DeprecationWarning,
    stacklevel=2,
)


@dataclass(frozen=True)
class _ExecutionFill:
    ok: bool
    filled_qty: int = 0
    fill_price: float | None = None
    status_verified: bool = False
    reason: str = ""


@dataclass(frozen=True)
class _ExecutionResult:
    ok: bool
    order_id: str | None = None
    broker_latency_ms: int = 0
    reason: str = ""


@dataclass
class OrchestratorSignal:
    name: str
    signal: dict[str, Any]
    risk: Any
    safety: Any | None = None
    execution_result: Any | None = None
    execution_fill: Any | None = None
    executed: bool = False
    note: str = ""


@dataclass
class OrchestratorCycle:
    snapshot: Any
    signals: list[OrchestratorSignal] = field(default_factory=list)
    reconciliation: Any | None = None
    saved: bool = False
    note: str = ""


class Orchestrator:
    def __init__(
        self,
        data_engine: Any,
        strategy_engine: Any,
        risk_engine: Any,
        execution_service: Any | None = None,
        state_manager: Any | None = None,
        *,
        safety_engine: Any | None = None,
        audit_engine: Any | None = None,
        reconciliation_engine: Any | None = None,
        names_provider: Callable[[], list[str]] | None = None,
        execution_mode_fn: Callable[[], str] | None = None,
        entry_gate_fn: Callable[[str, dict], bool] | None = None,
        system_mode_fn: Callable[[], str] | None = None,
        circuit_breaker_fn: Callable[[], bool] | None = None,
        market_hours_fn: Callable[[], bool] | None = None,
        market_vix_fn: Callable[[], float] | None = None,
        safety_context_fn: Callable[[Any], Any] | None = None,
        local_positions_fn: Callable[[], dict] | None = None,
        enforce_market_hours: bool = False,
    ):
        self._data_engine = data_engine
        self._strategy_engine = strategy_engine
        self._risk_engine = risk_engine
        self._execution_service = execution_service
        self._state_manager = state_manager
        self._safety_engine = safety_engine
        self._audit_engine = audit_engine
        self._reconciliation_engine = reconciliation_engine
        self._names_provider = names_provider or (lambda: [])
        self._execution_mode_fn = execution_mode_fn or (lambda: "MANUAL")
        self._entry_gate_fn = entry_gate_fn or (lambda n, s: True)
        self._system_mode_fn = system_mode_fn or (lambda: "NORMAL")
        self._circuit_breaker_fn = circuit_breaker_fn or (lambda: True)
        self._market_hours_fn = market_hours_fn or (lambda: True)
        self._market_vix_fn = market_vix_fn or (lambda: 0.0)
        self._safety_context_fn = safety_context_fn
        self._local_positions_fn = local_positions_fn
        self._enforce_market_hours = enforce_market_hours

    @staticmethod
    def _default_order_builder(name: str, signal: dict) -> dict[str, Any]:
        return {
            "name": name,
            "direction": signal.get("direction", "CALL"),
            "qty": signal.get("qty", 1),
            "strike": signal.get("strike", 0),
        }

    def run_cycle(self) -> OrchestratorCycle:
        from core.safety_state import check_kill_file_and_halt

        check_kill_file_and_halt()

        names = self._names_provider()

        if self._enforce_market_hours and not self._market_hours_fn():
            return OrchestratorCycle(
                snapshot=self._data_engine.fetch_market_snapshot(names),
                signals=[],
                saved=True,
                note="outside NSE market hours - cycle skipped",
            )
        snapshot = self._data_engine.fetch_market_snapshot(names)
        if not snapshot.healthy:
            return OrchestratorCycle(snapshot=snapshot, signals=[], saved=True, note=snapshot.note)

        signals: list[OrchestratorSignal] = []
        for name in names:
            frames = snapshot.frames.get(name, {})
            sig = self._strategy_engine.generate_signal(name, frames)
            if not sig:
                continue

            risk_result = self._risk_engine.quality_check(
                volume_ratio=float(sig.get("vol_ratio", 0)),
            )
            loss_check = self._risk_engine.loss_streak_check()
            risk_allowed = risk_result.allowed if hasattr(risk_result, 'allowed') else getattr(risk_result, 'is_allowed', True)

            safety_allowed = True
            safety_reason = ""
            if self._safety_engine and self._safety_context_fn:
                ctx = self._safety_context_fn(snapshot)
                safety_decision = self._safety_engine.evaluate(ctx)
                safety_allowed = safety_decision.allowed
                safety_reason = safety_decision.reason

            system_mode = self._system_mode_fn()
            if system_mode != "NORMAL":
                risk_allowed = False

            circuit_ok = self._circuit_breaker_fn()
            if not circuit_ok:
                risk_allowed = False

            if not safety_allowed:
                risk_allowed = False

            from types import SimpleNamespace

            risk_ns = SimpleNamespace(allowed=risk_allowed, reason="")
            safety_ns = SimpleNamespace(allowed=safety_allowed, reason=safety_reason)
            reconciliation = None
            entries = []

            reason_parts = []

            if self._reconciliation_engine:
                local_positions = self._local_positions_fn() if self._local_positions_fn else {}
                if local_positions:
                    recon_report = self._reconciliation_engine.reconcile_positions(local_positions)
                    reconciliation = recon_report
                    if not recon_report.ok:
                        risk_allowed = False
                        reason_parts.append("reconciliation mismatch")

            if system_mode != "NORMAL":
                risk_allowed = False
                reason_parts.append(f"System mode: {system_mode}")

            if not safety_allowed:
                risk_allowed = False
                reason_parts.append(safety_reason)
                if self._audit_engine:
                    try:
                        self._audit_engine.record("safety_blocked", severity="WARNING", reason=safety_reason)
                    except (ValueError, TypeError, OSError):
                        pass

            if not circuit_ok:
                risk_allowed = False
                reason_parts.append("CIRCUIT_BREAKER_ACTIVE")

            risk_ns = SimpleNamespace(
                allowed=risk_allowed and safety_allowed,
                reason="; ".join(reason_parts) if reason_parts else "",
            )

            if risk_allowed and safety_allowed and self._entry_gate_fn(name, sig):
                mode = self._execution_mode_fn()
                if mode == "AUTO" and self._execution_service:
                    try:
                        order_req = SimpleNamespace(
                            symbol=name,
                            lot_size=sig.get("qty", 1),
                            strike_price=sig.get("strike", 0),
                        )
                        result = self._execution_service.execute_order(order_req)
                        exec_result = _ExecutionResult(
                            ok=result.status.name == "FILLED" if hasattr(result.status, "name") else False,
                            order_id=result.order_id,
                            reason=getattr(result, "reject_reason", ""),
                        )
                        if exec_result.ok:
                            exec_fill = _ExecutionFill(
                                ok=True,
                                filled_qty=getattr(result, "filled_quantity", 0),
                                fill_price=getattr(result, "average_price", None),
                            )
                        else:
                            exec_fill = _ExecutionFill(ok=False, reason=exec_result.reason)
                        entries.append(
                            OrchestratorSignal(
                                name=name,
                                signal=sig,
                                risk=risk_ns,
                                safety=safety_ns,
                                executed=exec_result.ok,
                                execution_result=exec_result,
                                execution_fill=exec_fill,
                            )
                        )
                    except (ValueError, TypeError, OSError, ConnectionError) as e:
                        exec_result = _ExecutionResult(ok=False, reason=str(e))
                        entries.append(
                            OrchestratorSignal(
                                name=name,
                                signal=sig,
                                risk=risk_ns,
                                safety=safety_ns,
                                executed=False,
                                execution_result=exec_result,
                            )
                        )
                else:
                    entries.append(
                        OrchestratorSignal(
                            name=name,
                            signal=sig,
                            risk=risk_ns,
                            safety=safety_ns,
                            executed=False,
                        )
                    )
            else:
                entries.append(
                    OrchestratorSignal(
                        name=name,
                        signal=sig,
                        risk=risk_ns,
                        safety=safety_ns,
                        executed=False,
                    )
                )
            signals.extend(entries)

        saved = True
        if self._state_manager:
            self._state_manager.save()

        if self._audit_engine:
            try:
                self._audit_engine.record("cycle_complete", severity="INFO", symbol_count=len(signals))
            except (ValueError, TypeError, OSError):
                pass

        return OrchestratorCycle(
            snapshot=snapshot,
            signals=signals,
            reconciliation=reconciliation if signals else None,
            saved=saved,
        )


__all__ = [
    "Orchestrator",
    "OrchestratorCycle",
    "OrchestratorSignal",
    "_ExecutionFill",
    "_ExecutionResult",
]
