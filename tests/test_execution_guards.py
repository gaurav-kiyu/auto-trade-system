"""
Tests for core/execution_guards.py - Pre-trade validation and risk controls.

Covers:
  - GuardResult dataclass
  - TradeFrequencyRecord dataclass
  - ExecutionGuards initialization with config
  - check_all_guards full pipeline
  - Individual guards: price sanitizer, slippage, stale data,
    trade frequency, consecutive losses, time-based reduction
  - record_trade, record_win, record_loss, reset_daily
  - health_check and singleton getter
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from core.execution_guards import ExecutionGuards, GuardResult, TradeFrequencyRecord, get_execution_guards
from core.safety_state import _HARD_HALT, get_consecutive_losses, reset_consecutive_losses

# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_state() -> None:
    _HARD_HALT.clear()
    reset_consecutive_losses()


@pytest.fixture()
def guards() -> ExecutionGuards:
    return ExecutionGuards({
        "SLIPPAGE_GUARD_THRESHOLD_PCT": 2.0,
        "MAX_QUOTE_AGE_SECONDS": 2.0,
        "MAX_TRADES_PER_DAY": 10,
        "MIN_TRADE_INTERVAL_SECONDS": 30,
        "MAX_CONSECUTIVE_LOSSES": 3,
    })


# ── Dataclasses ──────────────────────────────────────────────────────


class TestGuardResult:
    def test_passed(self) -> None:
        r = GuardResult(passed=True)
        assert r.passed
        assert r.reason == ""
        assert r.details == {}

    def test_failed_with_reason(self) -> None:
        r = GuardResult(passed=False, reason="Invalid price", details={"price": -1})
        assert not r.passed
        assert r.reason == "Invalid price"
        assert r.details["price"] == -1


class TestTradeFrequencyRecord:
    def test_creation(self) -> None:
        now = datetime.now()
        r = TradeFrequencyRecord(timestamp=now, symbol="NIFTY", direction="CALL", qty=1)
        assert r.timestamp == now
        assert r.symbol == "NIFTY"
        assert r.pnl == 0.0  # default


# ── Init ─────────────────────────────────────────────────────────────


class TestInit:
    def test_default_config(self) -> None:
        g = ExecutionGuards()
        assert g._slippage_threshold_pct == 2.0
        assert g._max_quote_age_seconds == 2.0
        assert g._max_trades_per_day == 10

    def test_custom_config(self) -> None:
        g = ExecutionGuards({"SLIPPAGE_GUARD_THRESHOLD_PCT": 5.0, "MAX_TRADES_PER_DAY": 5})
        assert g._slippage_threshold_pct == 5.0
        assert g._max_trades_per_day == 5

    def test_alert_callback(self) -> None:
        g = ExecutionGuards()
        calls: list[str] = []
        g.set_alert_callback(lambda msg: calls.append(msg))
        g._check_slippage_guard("NIFTY", 100.0, 105.0)  # 5% > 2% threshold
        assert len(calls) >= 1
        assert "Slippage" in calls[0]


# ── check_all_guards ────────────────────────────────────────────────


class TestCheckAllGuards:
    def test_all_pass(self, guards: ExecutionGuards) -> None:
        ok, reason, details = guards.check_all_guards(
            "NIFTY", "CALL", 100.0, 100.5, datetime.now(),
        )
        assert ok
        assert reason == ""

    def test_price_sanitizer_fails_first(self, guards: ExecutionGuards) -> None:
        ok, reason, details = guards.check_all_guards(
            "NIFTY", "CALL", 100.0, -1.0, datetime.now(),
        )
        assert not ok
        assert "Negative price" in reason

    def test_slippage_fails(self, guards: ExecutionGuards) -> None:
        ok, reason, details = guards.check_all_guards(
            "NIFTY", "CALL", 100.0, 105.0, datetime.now(),
        )
        assert not ok
        assert "Slippage" in reason

    def test_stale_data_fails(self, guards: ExecutionGuards) -> None:
        old_ts = datetime.now() - timedelta(seconds=10)
        ok, reason, details = guards.check_all_guards(
            "NIFTY", "CALL", 100.0, 100.5, old_ts,
        )
        assert not ok
        assert "Stale" in reason or "quote" in reason.lower()


# ── Price Sanitizer ─────────────────────────────────────────────────


class TestPriceSanitizer:
    def test_none_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", None)  # type: ignore
        assert not r.passed

    def test_nan_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", float("nan"))
        assert not r.passed

    def test_inf_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", float("inf"))
        assert not r.passed

    def test_negative_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", -10.0)
        assert not r.passed

    def test_zero_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", 0.0)
        assert not r.passed

    def test_valid_price(self, guards: ExecutionGuards) -> None:
        r = guards._check_price_sanitizer("NIFTY", 23500.0)
        assert r.passed

    def test_zero_price_allowed(self) -> None:
        g = ExecutionGuards({"ALLOW_ZERO_PRICE": True})
        r = g._check_price_sanitizer("NIFTY", 0.0)
        assert r.passed


# ── Slippage Guard ──────────────────────────────────────────────────


class TestSlippageGuard:
    def test_within_threshold(self, guards: ExecutionGuards) -> None:
        r = guards._check_slippage_guard("NIFTY", 100.0, 101.0)
        assert r.passed

    def test_exceeds_threshold(self, guards: ExecutionGuards) -> None:
        r = guards._check_slippage_guard("NIFTY", 100.0, 105.0)
        assert not r.passed

    def test_invalid_model_price_skips(self, guards: ExecutionGuards) -> None:
        r = guards._check_slippage_guard("NIFTY", 0.0, 100.0)
        assert r.passed

    def test_invalid_live_price_skips(self, guards: ExecutionGuards) -> None:
        r = guards._check_slippage_guard("NIFTY", 100.0, 0.0)
        assert r.passed

    def test_deviation_in_details(self, guards: ExecutionGuards) -> None:
        r = guards._check_slippage_guard("NIFTY", 100.0, 103.0)
        deviation = r.details.get("deviation_pct", 0)
        assert deviation == 3.0


# ── Stale Data Watchdog ─────────────────────────────────────────────


class TestStaleData:
    def test_no_timestamp_skips(self, guards: ExecutionGuards) -> None:
        r = guards._check_stale_data("NIFTY", None)
        assert r.passed

    def test_fresh_quote(self, guards: ExecutionGuards) -> None:
        r = guards._check_stale_data("NIFTY", datetime.now())
        assert r.passed

    def test_stale_quote(self, guards: ExecutionGuards) -> None:
        old = datetime.now() - timedelta(seconds=5)
        r = guards._check_stale_data("NIFTY", old)
        assert not r.passed

    def test_age_in_details(self, guards: ExecutionGuards) -> None:
        old = datetime.now() - timedelta(seconds=3)
        r = guards._check_stale_data("NIFTY", old)
        assert r.details.get("quote_age_seconds", 0) >= 2.5


# ── Trade Frequency ─────────────────────────────────────────────────


class TestTradeFrequency:
    def test_first_trade_allowed(self, guards: ExecutionGuards) -> None:
        r = guards._check_trade_frequency("NIFTY")
        assert r.passed

    def test_records_trade(self, guards: ExecutionGuards) -> None:
        guards.record_trade("NIFTY", "CALL", 1)
        assert guards.get_trades_today() == 1

    def test_reset_daily_clears(self, guards: ExecutionGuards) -> None:
        guards.record_trade("NIFTY", "CALL", 1)
        guards.reset_daily()
        assert guards.get_trades_today() == 0


# ── Consecutive Losses ──────────────────────────────────────────────


class TestConsecutiveLosses:
    def test_start_at_zero(self, guards: ExecutionGuards) -> None:
        r = guards._check_consecutive_losses()
        assert r.passed

    def test_record_loss_increments(self, guards: ExecutionGuards) -> None:
        guards.record_loss()
        assert get_consecutive_losses() == 1

    def test_record_win_resets(self, guards: ExecutionGuards) -> None:
        guards.record_loss()
        guards.record_loss()
        guards.record_win()
        assert get_consecutive_losses() == 0


# ── Health Check ────────────────────────────────────────────────────


class TestHealthCheck:
    def test_returns_status(self, guards: ExecutionGuards) -> None:
        status = guards.health_check()
        assert "consecutive_losses" in status
        assert "trades_today" in status
        assert status["consecutive_losses"] == 0

    def test_records_trades_reflected(self, guards: ExecutionGuards) -> None:
        guards.record_trade("NIFTY", "CALL", 1)
        status = guards.health_check()
        assert status["trades_today"] >= 1


# ── Singleton ───────────────────────────────────────────────────────


class TestSingleton:
    def test_get_execution_guards_returns_instance(self) -> None:
        g = get_execution_guards()
        assert isinstance(g, ExecutionGuards)

    def test_get_execution_guards_singleton(self) -> None:
        g1 = get_execution_guards()
        g2 = get_execution_guards()
        assert g1 is g2

    def test_custom_config(self) -> None:
        g = ExecutionGuards({"MAX_TRADES_PER_DAY": 5})
        assert g._max_trades_per_day == 5

    def test_default_config(self) -> None:
        g = ExecutionGuards()
        assert g._max_trades_per_day == 10
