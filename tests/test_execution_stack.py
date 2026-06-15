"""Tests for core.execution_stack — paper fills vs broker-backed orders."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.execution_stack import (
    ExecutionRouter,
    PaperExecutionSimulator,
    PaperFill,
    TradingMode,
    trading_mode_from_cfg,
)


# ── TradingMode enum ──────────────────────────────────────────────────────

def test_trading_mode_values() -> None:
    assert TradingMode.MANUAL.value == "MANUAL"
    assert TradingMode.PAPER.value == "PAPER"
    assert TradingMode.AUTO.value == "AUTO"
    assert TradingMode.SIGNALS.value == "SIGNALS"


# ── PaperFill dataclass ──────────────────────────────────────────────────

def test_paper_fill_default() -> None:
    fill = PaperFill(ok=True, qty=50, price=23000.0)
    assert fill.ok is True
    assert fill.qty == 50
    assert fill.price == 23000.0
    assert fill.reason == ""


def test_paper_fill_with_reason() -> None:
    fill = PaperFill(ok=False, qty=0, price=0.0, reason="bad_input")
    assert fill.ok is False
    assert fill.reason == "bad_input"


# ── PaperExecutionSimulator ──────────────────────────────────────────────

def test_simulate_buy_call_default_slippage() -> None:
    sim = PaperExecutionSimulator()
    result = sim.simulate_buy(direction="CALL", ref_price=23000.0, qty=50)
    assert result.ok is True
    assert result.qty == 50
    assert result.price == 23000.0  # no slippage by default
    assert result.reason == "paper_simulated"


def test_simulate_buy_put_with_slippage() -> None:
    sim = PaperExecutionSimulator(slippage_pct=0.001)
    result = sim.simulate_buy(direction="PUT", ref_price=23000.0, qty=25)
    assert result.ok is True
    assert result.qty == 25
    # PUT: ref_price * (1 - 0.001) = 22977.0
    assert result.price == 23000.0 * (1 - 0.001)


def test_simulate_buy_call_with_slippage() -> None:
    sim = PaperExecutionSimulator(slippage_pct=0.002)
    result = sim.simulate_buy(direction="CALL", ref_price=100.0, qty=10)
    assert result.ok is True
    assert result.price == 100.0 * (1 + 0.002)


def test_simulate_buy_bad_input() -> None:
    sim = PaperExecutionSimulator()
    result = sim.simulate_buy(direction="CALL", ref_price=0.0, qty=50)
    assert result.ok is False
    assert result.reason == "bad_input"

    result2 = sim.simulate_buy(direction="CALL", ref_price=100.0, qty=0)
    assert result2.ok is False


def test_simulate_buy_lowercase_direction() -> None:
    sim = PaperExecutionSimulator(slippage_pct=0.005)
    result = sim.simulate_buy(direction="call", ref_price=200.0, qty=10)
    assert result.ok is True
    import math
    assert math.isclose(result.price, 200.0 * (1 + 0.005), rel_tol=1e-9)


# ── ExecutionRouter construction ─────────────────────────────────────────

def test_router_default_mode() -> None:
    router = ExecutionRouter(mode=TradingMode.MANUAL)
    assert router.mode == TradingMode.MANUAL
    assert router.should_auto_execute() is False
    assert router.should_paper_execute() is False


def test_router_auto_mode() -> None:
    router = ExecutionRouter(mode=TradingMode.AUTO, broker_engine=MagicMock())
    assert router.should_auto_execute() is True


def test_router_paper_mode() -> None:
    router = ExecutionRouter(mode=TradingMode.PAPER)
    assert router.should_paper_execute() is True


def test_router_paper_via_broker() -> None:
    broker = MagicMock()
    router = ExecutionRouter(mode=TradingMode.PAPER, broker_engine=broker, paper_routes_via_broker=True)
    assert router.should_route_paper_via_broker() is True


def test_router_paper_via_broker_no_broker() -> None:
    router = ExecutionRouter(mode=TradingMode.PAPER, paper_routes_via_broker=True, broker_engine=None)
    assert router.should_route_paper_via_broker() is False


# ── ExecutionRouter place_entry ──────────────────────────────────────────

def test_router_place_entry_manual() -> None:
    router = ExecutionRouter(mode=TradingMode.MANUAL)
    fill = router.place_entry(name="NIFTY", direction="CALL", qty=50, strike=23000)
    assert fill.ok is False
    assert fill.reason == "manual_signals_only"


def test_router_place_entry_paper() -> None:
    router = ExecutionRouter(mode=TradingMode.PAPER)
    fill = router.place_entry(name="NIFTY", direction="CALL", qty=50, strike=23000, ref_price=23000.0)
    assert fill.ok is True
    assert fill.qty == 50


def test_router_place_entry_paper_no_price() -> None:
    router = ExecutionRouter(mode=TradingMode.PAPER)
    fill = router.place_entry(name="NIFTY", direction="CALL", qty=50, strike=23000)
    assert fill.ok is False
    assert fill.reason == "paper_needs_ref_price"


def test_router_place_entry_auto_no_broker() -> None:
    router = ExecutionRouter(mode=TradingMode.AUTO, broker_engine=None)
    result = router.place_entry(name="NIFTY", direction="CALL", qty=50, strike=23000)
    from core.ports.execution.execution_port import OrderStatus
    assert result.status == OrderStatus.REJECTED
    assert "not configured" in result.reject_reason


# ── ExecutionRouter place_exit ───────────────────────────────────────────

def test_router_place_exit_manual() -> None:
    router = ExecutionRouter(mode=TradingMode.MANUAL)
    fill = router.place_exit(name="NIFTY", direction="CALL", qty=50, strike=23000)
    assert fill.ok is False


def test_router_place_exit_paper() -> None:
    router = ExecutionRouter(mode=TradingMode.PAPER)
    fill = router.place_exit(name="NIFTY", direction="CALL", qty=50, strike=23000)
    assert fill.ok is True


def test_router_cancel_order_no_broker() -> None:
    router = ExecutionRouter(mode=TradingMode.MANUAL)
    assert router.cancel_order("ORD001") is False


# ── trading_mode_from_cfg ────────────────────────────────────────────────

def test_trading_mode_from_cfg_manual() -> None:
    mode = trading_mode_from_cfg({"EXECUTION_MODE": "MANUAL"})
    assert mode == TradingMode.MANUAL


def test_trading_mode_from_cfg_paper() -> None:
    mode = trading_mode_from_cfg({"EXECUTION_MODE": "PAPER"})
    assert mode == TradingMode.PAPER


def test_trading_mode_from_cfg_auto() -> None:
    mode = trading_mode_from_cfg({"EXECUTION_MODE": "AUTO"})
    assert mode == TradingMode.AUTO


def test_trading_mode_from_cfg_cli_paper_override() -> None:
    with MagicMock() as _mock:
        mode = trading_mode_from_cfg({"EXECUTION_MODE": "AUTO"}, cli_paper=True)
    assert mode in (TradingMode.PAPER, TradingMode.MANUAL)
