"""ExecutionRouter wiring — verifies ExecutionRouter construction and routing logic.

These tests import the preserved ``ExecutionRouter`` from the test helper
(``tests.helpers.legacy_execution_stack``) which was extracted when
``core/execution_stack.py`` and ``core/trading_orchestrator.py`` were removed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.helpers.legacy_execution_engine import ExecutionEngine, ExecutionResult
from tests.helpers.legacy_execution_stack import ExecutionRouter, trading_mode_from_cfg


def _make_router(mode: str, cfg: dict | None = None, *, broker_engine=None, cli_paper: bool = False) -> ExecutionRouter:
    """Helper to build an ExecutionRouter from config string (replaces deprecated build_execution_router)."""
    merged = dict(cfg or {})
    if mode:
        merged["EXECUTION_MODE"] = mode
    resolved_mode = trading_mode_from_cfg(merged, cli_paper=cli_paper)
    paper_via = bool(merged.get("EXECUTION_ROUTER_PAPER_USES_ADAPTER", False))
    return ExecutionRouter(resolved_mode, broker_engine=broker_engine, paper_routes_via_broker=paper_via)


def _dummy_engine() -> ExecutionEngine:
    return ExecutionEngine(
        broker_getter=lambda: None,
        verify_terminal_ok_fn=None,
        broker_snapshot_fn=lambda: {},
        capture_hook=None,
        sleep_fn=lambda s: None,
    )


def test_auto_with_broker_engine_allows_auto_execute() -> None:
    r = _make_router("AUTO", broker_engine=_dummy_engine())
    assert r.should_auto_execute()


def test_auto_without_broker_engine_blocks_auto_execute() -> None:
    r = _make_router("AUTO", broker_engine=None)
    assert not r.should_auto_execute()


def test_manual_blocks_auto_execute_even_with_engine() -> None:
    r = _make_router("MANUAL", broker_engine=_dummy_engine())
    assert not r.should_auto_execute()


def test_cli_paper_blocks_auto_execute() -> None:
    r = _make_router("AUTO", cli_paper=True, broker_engine=_dummy_engine())
    assert r.mode.value == "PAPER"
    assert not r.should_auto_execute()


def test_place_entry_forwards_retries_to_execution_engine() -> None:
    eng = ExecutionEngine(broker_getter=lambda: None, sleep_fn=lambda s: None)
    eng.place_order = MagicMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(True, order_id="oid", broker_latency_ms=12),
    )
    r = _make_router("AUTO", broker_engine=eng)
    r.place_entry(
        name="NIFTY",
        direction="CALL",
        qty=50,
        strike=24000,
        ref_price=100.0,
        retries=4,
        retry_wait_s=0.75,
    )
    eng.place_order.assert_called_once()
    _args, kwargs = eng.place_order.call_args
    assert kwargs["retries"] == 4
    assert kwargs["retry_wait_s"] == 0.75
    assert kwargs["is_exit"] is False


def test_place_exit_forwards_retries_and_is_exit() -> None:
    eng = ExecutionEngine(broker_getter=lambda: None, sleep_fn=lambda s: None)
    eng.place_order = MagicMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(True, order_id="ex", broker_latency_ms=3),
    )
    r = _make_router("AUTO", broker_engine=eng)
    r.place_exit(name="NIFTY", direction="CALL", qty=50, strike=24000, retries=1, retry_wait_s=2.0)
    eng.place_order.assert_called_once()
    _args, kwargs = eng.place_order.call_args
    assert kwargs["retries"] == 1
    assert kwargs["retry_wait_s"] == 2.0
    assert kwargs["is_exit"] is True


def test_paper_routes_via_broker_false_by_default() -> None:
    r = _make_router("PAPER", broker_engine=_dummy_engine())
    assert not r.should_route_paper_via_broker()


def test_paper_routes_via_broker_when_cfg_and_engine() -> None:
    r = _make_router("PAPER", {"EXECUTION_ROUTER_PAPER_USES_ADAPTER": True}, broker_engine=_dummy_engine())
    assert r.should_route_paper_via_broker()


def test_paper_place_entry_uses_engine_when_adapter_flag() -> None:
    eng = ExecutionEngine(broker_getter=lambda: None, sleep_fn=lambda s: None)
    eng.place_order = MagicMock(  # type: ignore[method-assign]
        return_value=ExecutionResult(True, order_id="p1", broker_latency_ms=5),
    )
    r = _make_router("PAPER", {"EXECUTION_ROUTER_PAPER_USES_ADAPTER": True}, broker_engine=eng)
    out = r.place_entry(name="N", direction="CALL", qty=25, strike=24000, ref_price=None)
    eng.place_order.assert_called_once()
    assert getattr(out, "order_id", None) == "p1"


def test_cancel_order_delegates_to_engine() -> None:
    class _B:
        def __init__(self) -> None:
            self.seen: list[str | None] = []

        def cancel_order(self, oid: str | None) -> bool:
            self.seen.append(oid)
            return True

    stub = _B()
    eng = ExecutionEngine(broker_getter=lambda: stub, sleep_fn=lambda s: None)
    r = _make_router("AUTO", broker_engine=eng)
    assert r.cancel_order("ord1") is True
    assert stub.seen == ["ord1"]
