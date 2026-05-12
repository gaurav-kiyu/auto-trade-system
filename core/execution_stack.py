"""
Execution layer: paper fills vs broker-backed orders behind one small router.

``core.execution_engine.ExecutionEngine`` remains the broker primitive; this module adds
paper simulation and a config-driven router for future AUTO mode.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from core.execution_engine import ExecutionEngine, ExecutionResult


class TradingMode(str, Enum):
    MANUAL = "MANUAL"
    PAPER = "PAPER"
    AUTO = "AUTO"
    SIGNALS = "SIGNALS"


@dataclass(frozen=True)
class PaperFill:
    ok: bool
    qty: int
    price: float
    reason: str = ""


class PaperExecutionSimulator:
    """Deterministic immediate fill at a reference price ± slippage (no network)."""

    def __init__(self, *, slippage_pct: float = 0.0) -> None:
        self._slip = float(slippage_pct)

    def simulate_buy(
        self,
        *,
        direction: str,
        ref_price: float,
        qty: int,
    ) -> PaperFill:
        if ref_price <= 0 or qty <= 0:
            return PaperFill(False, 0, 0.0, reason="bad_input")
        d = str(direction).upper()
        mult = 1.0 + self._slip if d == "CALL" else 1.0 - self._slip
        px = round(float(ref_price) * mult, 4)
        return PaperFill(True, int(qty), px, reason="paper_simulated")


class ExecutionRouter:
    """
    Routes to paper simulation or broker ``ExecutionEngine`` based on ``TradingMode``.

    MANUAL/SIGNALS: do not auto-place; caller should only surface signals.
    """

    def __init__(
        self,
        mode: TradingMode,
        *,
        paper: PaperExecutionSimulator | None = None,
        broker_engine: ExecutionEngine | None = None,
        paper_routes_via_broker: bool = False,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._mode = mode
        self._paper = paper or PaperExecutionSimulator()
        self._broker = broker_engine
        self._paper_routes_via_broker = bool(paper_routes_via_broker)
        self._log = log_fn or (lambda _m: None)

    @property
    def mode(self) -> TradingMode:
        return self._mode

    def should_auto_execute(self) -> bool:
        return self._mode == TradingMode.AUTO and self._broker is not None

    def should_paper_execute(self) -> bool:
        return self._mode == TradingMode.PAPER

    def should_route_paper_via_broker(self) -> bool:
        """When True, PAPER mode uses ``broker_engine`` (e.g. PaperAdapter) instead of the in-memory simulator."""
        return (
            self._mode == TradingMode.PAPER
            and self._paper_routes_via_broker
            and self._broker is not None
        )

    def place_entry(
        self,
        *,
        name: str,
        direction: str,
        qty: int,
        strike: int,
        ref_price: float | None = None,
        retries: int = 3,
        retry_wait_s: float = 1.0,
    ) -> ExecutionResult | PaperFill:
        if self._mode in (TradingMode.MANUAL, TradingMode.SIGNALS):
            self._log(f"[exec] mode={self._mode.value} — no auto entry for {name}")
            return PaperFill(False, 0, 0.0, reason="manual_signals_only")

        if self._mode == TradingMode.PAPER:
            if self._paper_routes_via_broker and self._broker is not None:
                return self._broker.place_order(
                    name=name,
                    direction=direction,
                    qty=qty,
                    strike=strike,
                    retries=retries,
                    retry_wait_s=retry_wait_s,
                    is_exit=False,
                )
            if ref_price is None or ref_price <= 0:
                return PaperFill(False, 0, 0.0, reason="paper_needs_ref_price")
            return self._paper.simulate_buy(direction=direction, ref_price=float(ref_price), qty=qty)

        if self._broker is None:
            return ExecutionResult(False, reason="broker engine not configured")
        return self._broker.place_order(
            name=name,
            direction=direction,
            qty=qty,
            strike=strike,
            retries=retries,
            retry_wait_s=retry_wait_s,
            is_exit=False,
        )

    def place_exit(
        self,
        *,
        name: str,
        direction: str,
        qty: int,
        strike: int,
        retries: int = 3,
        retry_wait_s: float = 1.0,
    ) -> ExecutionResult | PaperFill:
        if self._mode in (TradingMode.MANUAL, TradingMode.SIGNALS):
            return PaperFill(False, 0, 0.0, reason="manual_signals_only")

        if self._mode == TradingMode.PAPER:
            if self._paper_routes_via_broker and self._broker is not None:
                return self._broker.place_order(
                    name=name,
                    direction=direction,
                    qty=qty,
                    strike=strike,
                    retries=retries,
                    retry_wait_s=retry_wait_s,
                    is_exit=True,
                )
            return PaperFill(True, int(qty), 0.0, reason="paper_exit_ack")

        if self._broker is None:
            return ExecutionResult(False, reason="broker engine not configured")
        return self._broker.place_order(
            name=name,
            direction=direction,
            qty=qty,
            strike=strike,
            retries=retries,
            retry_wait_s=retry_wait_s,
            is_exit=True,
        )

    def cancel_order(self, order_id: str | None) -> bool:
        if self._broker is None:
            return False
        return bool(self._broker.cancel_order(order_id))


def trading_mode_from_cfg(cfg: dict[str, Any], *, cli_paper: bool = False) -> TradingMode:
    from core.hybrid_execution import apply_execution_mode, normalize_execution_mode

    merged = dict(cfg or {})
    apply_execution_mode(merged, cli_paper=cli_paper, infer_blank_from_broker=False)
    raw = normalize_execution_mode(merged.get("EXECUTION_MODE", "MANUAL"))
    try:
        return TradingMode(raw)
    except Exception:
        return TradingMode.MANUAL
