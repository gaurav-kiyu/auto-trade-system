"""Tests for index_trader exit and trailing stop logic."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from core.position_service import reset_position_service


@pytest.fixture()
def mock_globals():
    """Set up mock module-level globals for index_trader.

    Notes:
        - Resets the PositionService singleton so each test gets a fresh service.
        - Patches _ltp_resolver (not get_underlying_ltp) because PositionService
          uses self._ltp_resolver.resolve() internally.
    """
    reset_position_service()
    mock_ltp = MagicMock()
    mock_ltp.resolve.return_value = None

    with (
        patch("index_app.index_trader.positions", {}) as pos,
        patch("index_app.index_trader._pos_lock") as lock,
        patch("index_app.index_trader._CFG", {
            "SL_PCT": "0.92", "TARGET_PCT": "1.3",
            "TRAIL_PCT": "0.93", "TRAIL_ACTIVATE": "1.1",
        }) as cfg,
        patch("index_app.index_trader.log") as log,
        patch("index_app.index_trader.send") as send,
        patch("index_app.index_trader._portfolio_service") as psvc,
        patch("index_app.index_trader._execution_service") as exec_svc,
        patch("index_app.index_trader._ltp_resolver", mock_ltp),
        patch("index_app.index_trader._reentry_trackers", {}),
        patch("index_app.index_trader._position_service", None),
    ):
        yield {
            "positions": pos,
            "lock": lock,
            "cfg": cfg,
            "log": log,
            "send": send,
            "psvc": psvc,
            "exec_svc": exec_svc,
            "ltp": mock_ltp,
        }


# ── Exit Failure Tests ───────────────────────────────────────────────────────


class TestExitFailure:
    """_exit_position retry logic when price fetch fails."""

    def _import_exit(self):
        from index_app.index_trader import _exit_position
        return _exit_position

    def _make_order_result(self, price: float):
        """Create a mock order result with the given average_price."""
        from core.ports.execution.execution_port import OrderStatus
        result = MagicMock()
        result.status = OrderStatus.FILLED
        result.average_price = price
        result.reject_reason = ""
        return result

    def test_exit_failure_marks_position(self, mock_globals):
        """When exit_price == entry_price for non-MANUAL, mark exit_failed."""
        m = mock_globals
        m["positions"]["NIFTY"] = {
            "direction": "CALL", "qty": 75, "entry_price": 100.0,
            "entry_order_direction": "BUY", "entry_time": time.time(),
        }
        m["ltp"].resolve.return_value = 100.0  # triggers exit_failed
        m["exec_svc"].execute_order.return_value = self._make_order_result(100.0)

        _exit = self._import_exit()
        _exit("NIFTY", "SL_HIT")
        pos = m["positions"].get("NIFTY")
        assert pos is not None
        assert pos["exit_failed"] is True
        assert pos["exit_retries"] == 1

    def test_exit_failure_retry_threshold(self, mock_globals):
        """After 3 retries, position is removed."""
        m = mock_globals
        m["positions"]["NIFTY"] = {
            "direction": "CALL", "qty": 75, "entry_price": 100.0,
            "entry_order_direction": "BUY", "exit_failed": True,
            "exit_retries": 2, "entry_time": time.time(),
        }
        m["ltp"].resolve.return_value = 100.0
        m["exec_svc"].execute_order.return_value = self._make_order_result(100.0)

        _exit = self._import_exit()
        _exit("NIFTY", "SL_HIT")
        assert "NIFTY" not in m["positions"]

    def test_successful_exit_removes_position(self, mock_globals):
        """Successful exit (exit_price != entry_price) removes position."""
        m = mock_globals
        m["positions"]["NIFTY"] = {
            "direction": "CALL", "qty": 75, "entry_price": 100.0,
            "entry_order_direction": "BUY", "entry_time": time.time(),
        }
        m["ltp"].resolve.return_value = 105.0
        m["exec_svc"].execute_order.return_value = self._make_order_result(108.0)

        _exit = self._import_exit()
        _exit("NIFTY", "TARGET_HIT")
        assert "NIFTY" not in m["positions"]

    def test_manual_exit_not_marked_failed(self, mock_globals):
        """MANUAL exit with entry_price match should not mark exit_failed."""
        m = mock_globals
        m["positions"]["NIFTY"] = {
            "direction": "CALL", "qty": 75, "entry_price": 100.0,
            "entry_order_direction": "BUY", "entry_time": time.time(),
        }
        m["ltp"].resolve.return_value = 100.0
        m["exec_svc"].execute_order.return_value = self._make_order_result(100.0)

        _exit = self._import_exit()
        _exit("NIFTY", "MANUAL")

        assert "NIFTY" not in m["positions"]

    def test_exit_noop_for_nonexistent_position(self, mock_globals):
        """Calling _exit_position with a non-existent name does nothing."""
        _exit = self._import_exit()
        _exit("NONEXISTENT", "SL_HIT")  # should not raise


# ── Trailing Stop Tests ─────────────────────────────────────────────────────


class TestTrailingStop:
    """_monitor_positions trailing stop logic."""

    @pytest.fixture()
    def mock_trailing(self, mock_globals):
        """Set up a CALL position with underlying at 18500, entry at 18000."""
        m = mock_globals
        m["positions"]["NIFTY"] = {
            "direction": "CALL", "qty": 75, "entry_price": 100.0,
            "entry_order_direction": "BUY",
            "underlying_entry_price": 18000.0,
            "entry_time": time.time(),
            "score": 80,
        }
        yield m

    def _import_monitor(self):
        from index_app.index_trader import _monitor_positions
        return _monitor_positions

    def test_trailing_initializes_peak(self, mock_trailing):
        """First call initializes peak_underlying and trail_activated."""
        m = mock_trailing
        m["ltp"].resolve.return_value = 18500.0
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["NIFTY"]
        assert pos["peak_underlying"] == 18500.0
        assert pos["trail_activated"] is False

    def test_trailing_updates_peak(self, mock_trailing):
        """When underlying goes higher, peak is updated."""
        m = mock_trailing
        m["ltp"].resolve.return_value = 18500.0
        monitor = self._import_monitor()
        monitor()
        m["ltp"].resolve.return_value = 19000.0
        monitor()
        pos = m["positions"]["NIFTY"]
        assert pos["peak_underlying"] == 19000.0

    def test_trailing_activates_after_profit_threshold(self, mock_trailing):
        """CALL: trail activates when move_pct >= trail_activate_pct - 1 (10%)."""
        m = mock_trailing
        m["ltp"].resolve.return_value = 20000.0  # move_pct = (20000-18000)/18000 = 11.1%
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["NIFTY"]
        assert pos["trail_activated"] is True

    def test_trailing_does_not_activate_below_threshold(self, mock_trailing):
        """CALL: trail does not activate below profit threshold."""
        m = mock_trailing
        m["ltp"].resolve.return_value = 18100.0  # move_pct = 0.56%
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["NIFTY"]
        assert pos["trail_activated"] is False

    def test_trailing_hit_calls_exit(self, mock_trailing):
        """CALL: when trail activated and underlying drops below level, exit."""
        m = mock_trailing
        # Call 1: underlying at 18500, init peak
        m["ltp"].resolve.return_value = 18500.0
        monitor = self._import_monitor()
        monitor()
        # Move up: underlying at 20000, activate trail
        m["ltp"].resolve.return_value = 20000.0
        monitor()
        # Drop: underlying at 18300, should hit trail
        m["ltp"].resolve.return_value = 18300.0
        # PositionService.monitor_positions() calls self.exit_position(), not
        # the module-level _exit_position - patch at the service method level
        with patch("core.position_service.PositionService.exit_position") as mock_exit:
            monitor()
            mock_exit.assert_called_with("NIFTY", "TRAIL_HIT")

    def test_trailing_not_hit_when_above_level(self, mock_trailing):
        """CALL: when trail activated but underlying above trail level, no exit."""
        m = mock_trailing
        m["ltp"].resolve.return_value = 18500.0
        monitor = self._import_monitor()
        monitor()
        # Move up to activate
        m["ltp"].resolve.return_value = 20000.0
        monitor()
        # Small drop but still above trail level (20000 * 0.93 = 18600)
        m["ltp"].resolve.return_value = 19000.0
        with patch("core.position_service.PositionService.exit_position") as mock_exit:
            monitor()
            mock_exit.assert_not_called()


class TestTrailingStopPUT:
    """_monitor_positions trailing stop for PUT positions."""

    @pytest.fixture()
    def mock_put(self, mock_globals):
        m = mock_globals
        m["positions"]["BANKNIFTY"] = {
            "direction": "PUT", "qty": 50, "entry_price": 80.0,
            "entry_order_direction": "SELL",
            "underlying_entry_price": 44000.0,
            "entry_time": time.time(),
            "score": 75,
        }
        yield m

    def _import_monitor(self):
        from index_app.index_trader import _monitor_positions
        return _monitor_positions

    def test_put_trailing_initializes(self, mock_put):
        m = mock_put
        m["ltp"].resolve.return_value = 43500.0
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["BANKNIFTY"]
        assert pos["peak_underlying"] == 43500.0

    def test_put_trailing_activates_on_profit(self, mock_put):
        """PUT: trail activates when move_pct <= -(trail_activate_pct - 1)."""
        m = mock_put
        m["ltp"].resolve.return_value = 39000.0  # move = -11.4%
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["BANKNIFTY"]
        assert pos["trail_activated"] is True

    def test_put_trailing_peak_updated(self, mock_put):
        """PUT: peak_underlying tracks highest value, preventing trail from triggering."""
        m = mock_put
        # Enter at 43500
        m["ltp"].resolve.return_value = 43500.0
        monitor = self._import_monitor()
        monitor()
        # Peak set to 43500
        assert m["positions"]["BANKNIFTY"]["peak_underlying"] == 43500.0
        # Drop to profit (-11.4%), activates trail
        m["ltp"].resolve.return_value = 39000.0
        monitor()
        assert m["positions"]["BANKNIFTY"]["trail_activated"] is True
        # Peak stays at its highest (43500), because 39000 < 43500
        assert m["positions"]["BANKNIFTY"]["peak_underlying"] == 43500.0
        # Rise above entry: peak updates to current (47000) before trail check,
        # making trail_level = 47000 * 1.07 = 50290, unreachable
        m["ltp"].resolve.return_value = 47000.0
        with patch("core.position_service.PositionService.exit_position") as mock_exit:
            monitor()
            mock_exit.assert_not_called()
            assert m["positions"]["BANKNIFTY"]["peak_underlying"] == 47000.0

    def test_put_trailing_does_not_activate_below_threshold(self, mock_put):
        """PUT: trail does not activate when profit is below threshold."""
        m = mock_put
        m["ltp"].resolve.return_value = 43800.0  # move = -0.45%
        monitor = self._import_monitor()
        monitor()
        pos = m["positions"]["BANKNIFTY"]
        assert pos["trail_activated"] is False
