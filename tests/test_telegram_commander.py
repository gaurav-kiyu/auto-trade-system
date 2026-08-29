"""
Tests for core.telegram_commander - Telegram message builders and factory.

Covers:
  - build_rich_signal_message - full decision-support signal message
  - build_compact_signal_message - one-line compact signal
  - build_trade_entry_message - trade open notification
  - build_trade_exit_message - trade close notification with P&L
  - build_status_message - bot status summary
  - build_positions_message - open positions list
  - build_pending_signals_message - pending signal queue
  - build_commander factory - returns None when disabled
"""

from __future__ import annotations

from unittest.mock import MagicMock

from core.telegram_commander import (
    TelegramCommander,
    build_commander,
    build_compact_signal_message,
    build_pending_signals_message,
    build_positions_message,
    build_rich_signal_message,
    build_status_message,
    build_trade_entry_message,
    build_trade_exit_message,
)


class TestBuildRichSignalMessage:
    """Tests for build_rich_signal_message()."""

    def _make_signal(self, **overrides) -> dict:
        base = {
            "index_name": "NIFTY",
            "direction": "CALL",
            "score": 75,
            "tier": "STRONG",
            "regime": "TRENDING",
            "session": "MORNING",
            "vix": 15.5,
            "iv_rank": 45.0,
            "pcr": 1.3,
            "adx": 28.0,
            "rsi": 55.0,
            "entry_price": 25000.0,
            "sl_price": 24800.0,
            "target_price": 25500.0,
            "rr": 2.5,
            "lots": 1,
            "signal_id": "SIG-001",
            "ml_win_probability": 0.65,
            "soft_blocks": [],
        }
        base.update(overrides)
        return base

    def test_minimal_signal(self) -> None:
        """Minimal signal should still produce a message."""
        msg = build_rich_signal_message({"index_name": "NIFTY", "direction": "CALL", "score": 50})
        assert "NIFTY" in msg
        assert "CALL" in msg
        assert "50" in msg

    def test_full_signal_contains_key_sections(self) -> None:
        """Full signal should contain market, technical, and risk sections."""
        sig = self._make_signal()
        msg = build_rich_signal_message(sig)
        assert "NIFTY" in msg
        assert "CALL" in msg
        assert "STRONG" in msg
        # Regime label is mapped: TRENDING -> Trending
        assert "Trending" in msg or "TRENDING" in msg
        assert "VIX" in msg
        assert "IV Rank" in msg
        assert "RSI" in msg
        assert "ADX" in msg
        assert "ML Win Prob" in msg

    def test_put_signal(self) -> None:
        """PUT signal should show bearish indicators."""
        sig = self._make_signal(direction="PUT")
        msg = build_rich_signal_message(sig)
        assert "PUT" in msg

    def test_soft_blocks_included(self) -> None:
        """Soft blocks should appear in cautions section."""
        sig = self._make_signal(soft_blocks=["high_iv", "expiry_week"])
        msg = build_rich_signal_message(sig)
        assert "high_iv" in msg
        assert "expiry_week" in msg

    def test_signal_id_included(self) -> None:
        """Signal ID should appear in action commands."""
        sig = self._make_signal()
        msg = build_rich_signal_message(sig)
        assert "SIG-001" in msg
        assert "/approve" in msg
        assert "/reject" in msg

    def test_soft_blocks_json_string(self) -> None:
        """Soft blocks as JSON string should be parsed."""
        sig = self._make_signal(soft_blocks='["block_a", "block_b"]')
        msg = build_rich_signal_message(sig)
        assert "block_a" in msg
        assert "block_b" in msg

    def test_weak_tier(self) -> None:
        """Weak tier should still render."""
        sig = self._make_signal(tier="WEAK", score=40)
        msg = build_rich_signal_message(sig)
        assert "WEAK" in msg
        assert "40" in msg


class TestBuildCompactSignalMessage:
    """Tests for build_compact_signal_message()."""

    def test_basic_signal(self) -> None:
        """Compact signal should be one line."""
        sig = {"index_name": "BANKNIFTY", "direction": "PUT", "score": 60, "tier": "MODERATE", "regime": "RANGING"}
        msg = build_compact_signal_message(sig)
        assert "BANKNIFTY" in msg
        assert "PUT" in msg
        assert "60" in msg
        # Tier truncated to 3 chars: MODERATE -> MOD
        assert "MOD" in msg
        assert "60" in msg

    def test_with_vix(self) -> None:
        """VIX should appear in compact format."""
        sig = {"index_name": "NIFTY", "direction": "CALL", "score": 80, "tier": "STRONG",
               "regime": "TRENDING", "vix": 18.5}
        msg = build_compact_signal_message(sig)
        assert "VIX" in msg
        assert "18" in msg


class TestBuildTradeEntryMessage:
    """Tests for build_trade_entry_message()."""

    def test_basic_trade(self) -> None:
        """Trade entry should show key params."""
        trade = {
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "sl_price": 24800.0, "target_price": 25500.0, "lots": 2,
            "mode": "PAPER", "score": 75, "trade_id": "T-001", "lot_size": 25,
        }
        msg = build_trade_entry_message(trade)
        assert "TRADE OPEN" in msg
        assert "PAPER" in msg
        assert "25000" in msg
        assert "24800" in msg
        assert "25500" in msg
        assert "T-001" in msg

    def test_live_trade(self) -> None:
        """Live trade should show LIVE tag."""
        trade = {"index_name": "NIFTY", "direction": "PUT", "entry_price": 25000.0,
                 "sl_price": 25200.0, "target_price": 24500.0, "lots": 1,
                 "mode": "LIVE", "score": 80, "trade_id": "T-002", "lot_size": 50}
        msg = build_trade_entry_message(trade)
        assert "LIVE" in msg

    def test_risk_calculation(self) -> None:
        """Risk/reward should be calculated from entry/SL/TP."""
        trade = {"index_name": "NIFTY", "direction": "CALL", "entry_price": 100.0,
                 "sl_price": 90.0, "target_price": 130.0, "lots": 1, "mode": "PAPER",
                 "score": 60, "trade_id": "T-003", "lot_size": 50}
        msg = build_trade_entry_message(trade)
        # Risk per lot = (100 - 90) * 50 = 500, tot risk = 500
        # Reward per lot = (130 - 100) * 50 = 1500, tot reward = 1500
        # R:R = 1500/500 = 3.0
        assert "R:R" in msg


class TestBuildTradeExitMessage:
    """Tests for build_trade_exit_message()."""

    def test_winning_trade(self) -> None:
        """Winning trade should show positive P&L."""
        trade = {
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "exit_price": 25300.0, "net_pnl": 1500.0, "exit_reason": "TARGET",
            "hold_mins": 45.0, "mode": "PAPER", "trade_id": "T-001",
        }
        msg = build_trade_exit_message(trade)
        assert "TRADE CLOSED" in msg
        # Exit reason label: TARGET -> Target Hit
        assert "Target Hit" in msg
        # P&L should show positive value
        assert "1,500" in msg

    def test_losing_trade(self) -> None:
        """Losing trade should show negative P&L."""
        trade = {
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "exit_price": 24700.0, "net_pnl": -1500.0, "exit_reason": "SL",
            "hold_mins": 15.0, "mode": "PAPER", "trade_id": "T-002",
        }
        msg = build_trade_exit_message(trade)
        # Exit reason label: SL -> Stop Loss
        assert "Stop Loss" in msg
        assert "TRADE CLOSED" in msg

    def test_with_cumulative_pnl(self) -> None:
        """Cumulative P&L should appear when provided."""
        trade = {
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "exit_price": 25100.0, "net_pnl": 500.0, "exit_reason": "TRAIL",
            "mode": "PAPER", "trade_id": "T-003", "cumulative_pnl": 3200.0,
        }
        msg = build_trade_exit_message(trade)
        assert "Day P&L" in msg

    def test_with_win_rate(self) -> None:
        """Session win rate should appear when provided."""
        trade = {
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "exit_price": 25100.0, "net_pnl": 500.0, "exit_reason": "TARGET",
            "mode": "PAPER", "trade_id": "T-004", "session_win_rate": 0.6,
        }
        msg = build_trade_exit_message(trade)
        assert "Win Rate" in msg

    def test_put_direction_pnl(self) -> None:
        """PUT direction should invert move percentage."""
        trade = {
            "index_name": "BANKNIFTY", "direction": "PUT", "entry_price": 50000.0,
            "exit_price": 49000.0, "net_pnl": 2000.0, "exit_reason": "TARGET",
            "mode": "PAPER", "trade_id": "T-005",
        }
        msg = build_trade_exit_message(trade)
        assert "PUT" in msg
        # For PUT: spot moved down 2% → PUT should be +2% (inverted)
        assert "+2" in msg or "2.0" in msg


class TestBuildStatusMessage:
    """Tests for build_status_message()."""

    def test_running_status(self) -> None:
        """Running state should show green indicators."""
        state = {"execution_mode": "PAPER", "capital": 100000.0, "daily_pnl": 2500.0,
                 "daily_loss_limit": -5000.0, "daily_target": 5000.0, "open_positions": 1,
                 "max_open": 3, "trades_today": 2, "max_trades_day": 4, "vix": 15.0,
                 "hard_halt": False, "paused": False, "pending_signals": 0, "last_scan_secs": 5}
        msg = build_status_message(state)
        assert "RUNNING" in msg
        assert "PAPER" in msg
        assert "100,000" in msg or "100000" in msg
        assert "2,500" in msg or "2500" in msg

    def test_halted_status(self) -> None:
        """Halted state should show halt indicator."""
        state = {"execution_mode": "AUTO", "capital": 100000.0, "daily_pnl": -6000.0,
                 "daily_loss_limit": -5000.0, "daily_target": 5000.0, "open_positions": 0,
                 "max_open": 3, "trades_today": 3, "max_trades_day": 4,
                 "hard_halt": True, "paused": False, "pending_signals": 0}
        msg = build_status_message(state)
        assert "HALTED" in msg

    def test_paused_status(self) -> None:
        """Paused state should show pause indicator."""
        state = {"execution_mode": "MANUAL", "capital": 100000.0, "daily_pnl": 0.0,
                 "daily_loss_limit": -5000.0, "daily_target": 5000.0, "open_positions": 0,
                 "max_open": 3, "trades_today": 0, "max_trades_day": 4,
                 "hard_halt": False, "paused": True, "pending_signals": 0}
        msg = build_status_message(state)
        assert "PAUSED" in msg


class TestBuildPositionsMessage:
    """Tests for build_positions_message()."""

    def test_empty_positions(self) -> None:
        """Empty positions should return no-positions message."""
        msg = build_positions_message([])
        assert "No open positions" in msg

    def test_single_position(self) -> None:
        """Single position should show details."""
        positions = [{
            "index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0,
            "ltp": 25100.0, "sl_price": 24800.0,
        }]
        msg = build_positions_message(positions)
        assert "NIFTY" in msg
        assert "CALL" in msg
        assert "25000" in msg
        assert "25100" in msg

    def test_multiple_positions(self) -> None:
        """Multiple positions should all be listed."""
        positions = [
            {"index_name": "NIFTY", "direction": "CALL", "entry_price": 25000.0, "ltp": 25100.0, "sl_price": 24800.0},
            {"index_name": "BANKNIFTY", "direction": "PUT", "entry_price": 50000.0, "ltp": 49800.0, "sl_price": 50300.0},
        ]
        msg = build_positions_message(positions)
        assert "NIFTY" in msg
        assert "BANKNIFTY" in msg
        assert "CALL" in msg
        assert "PUT" in msg


class TestBuildPendingSignalsMessage:
    """Tests for build_pending_signals_message()."""

    def test_no_pending(self) -> None:
        """No pending signals should return empty message."""
        msg = build_pending_signals_message([])
        assert "No pending signals" in msg

    def test_with_pending(self) -> None:
        """Pending signals should show queue."""
        class FakeSignal:
            def __init__(self):
                self.signal_id = "SIG-001"
                self.index_name = "NIFTY"
                self.direction = "CALL"
                self.score = 75
                self.reason = "Strong trend"
                self.analyst_name = "Operator"

            def to_dict(self):
                return {
                    "signal_id": self.signal_id,
                    "index_name": self.index_name,
                    "direction": self.direction,
                    "score": self.score,
                    "reason": self.reason,
                    "analyst_name": self.analyst_name,
                }

        signals = [FakeSignal()]
        msg = build_pending_signals_message(signals)
        assert "SIG-001" in msg
        assert "NIFTY" in msg
        assert "CALL" in msg
        assert "75" in msg
        assert "/approve" in msg
        assert "/reject" in msg


class TestBuildCommander:
    """Tests for build_commander factory."""

    def test_disabled_by_config(self) -> None:
        """When telegram_commander_enabled is False, returns None."""
        commander = build_commander(
            cfg={"telegram_commander_enabled": False},
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=MagicMock(),
            send_fn=MagicMock(),
        )
        assert commander is None

    def test_enabled_but_no_token(self) -> None:
        """When enabled but no BOT_TOKEN, commander is created but not started."""
        commander = build_commander(
            cfg={"telegram_commander_enabled": True},
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=MagicMock(return_value={}),
            send_fn=MagicMock(),
        )
        # No BOT_TOKEN -> _thread not started, but commander returned
        assert commander is not None
        assert not commander.is_running()

    def test_enabled_with_token(self) -> None:
        """When enabled with token, commander is created."""
        commander = build_commander(
            cfg={
                "telegram_commander_enabled": True,
                "BOT_TOKEN": "test:token",
                "CHAT_ID": "12345",
                "telegram_authorized_user_ids": ["user1"],
                "telegram_poll_interval_secs": 30,
            },
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=MagicMock(return_value={}),
            send_fn=MagicMock(),
        )
        assert commander is not None
        assert isinstance(commander, TelegramCommander)


class TestCommanderBalance:
    """Tests for _cmd_balance - /balance command."""

    def _make_commander(self, state_fn=None, send_fn=None):
        return TelegramCommander(
            cfg={"telegram_commander_enabled": True, "BOT_TOKEN": "test:token", "CHAT_ID": "123"},
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=state_fn or MagicMock(return_value={
                "capital": 100000.0, "reserved_capital": 25000.0,
                "daily_pnl": 1500.0, "open_positions": 2, "max_open": 5,
            }),
            send_fn=send_fn or MagicMock(),
        )

    def test_balance_shows_capital_breakdown(self) -> None:
        """Balance command should show total, reserved, and available capital."""
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_balance()
        msg = send_mock.call_args[0][0]
        assert "100,000" in msg or "100000" in msg
        assert "25,000" in msg or "25000" in msg
        assert "Balance" in msg
        assert "Available" in msg

    def test_balance_shows_daily_pnl(self) -> None:
        """Balance command should show daily P&L."""
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_balance()
        msg = send_mock.call_args[0][0]
        assert "1,500" in msg or "1500" in msg
        assert "Day P&L" in msg

    def test_balance_shows_positions(self) -> None:
        """Balance command should show open positions count."""
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_balance()
        msg = send_mock.call_args[0][0]
        assert "2/5" in msg or "Positions" in msg

    def test_balance_handles_error(self) -> None:
        """Balance command should handle errors gracefully."""
        send_mock = MagicMock()
        cmd = self._make_commander(
            state_fn=MagicMock(side_effect=ValueError("test error")),
            send_fn=send_mock,
        )
        cmd._cmd_balance()
        msg = send_mock.call_args[0][0]
        assert "unavailable" in msg.lower() or "error" in msg.lower()


class TestCommanderPnl:
    """Tests for _cmd_pnl - /pnl and /perf commands."""

    def _make_commander(self, pnl_data=None, send_fn=None):
        return TelegramCommander(
            cfg={"telegram_commander_enabled": True, "BOT_TOKEN": "test:token", "CHAT_ID": "123"},
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=MagicMock(return_value={}),
            send_fn=send_fn or MagicMock(),
            pnl_fn=MagicMock(return_value=pnl_data or {
                "daily_pnl": 2500.0, "trades_today": 3, "wins_today": 2, "profit_factor": 1.8,
                "sharpe_ratio": 1.2, "cumulative_pnl": 15000.0,
            }),
        )

    def test_pnl_shows_daily(self) -> None:
        """P&L command should show daily P&L and cumulative metrics."""
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_pnl()
        msg = send_mock.call_args[0][0]
        assert "2,500" in msg or "2500" in msg
        assert "P&L" in msg or "Pnl" in msg
        # Cumulative metrics from enrichment path
        assert "PF:" in msg or "pf:" in msg.lower()
        assert "Sharpe" in msg

    def test_pnl_shows_trades_and_winrate(self) -> None:
        """P&L command should show trade count and win rate."""
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_pnl()
        msg = send_mock.call_args[0][0]
        assert "Trades" in msg or "trades" in msg
        assert "Wins" in msg or "wins" in msg
        assert "Win" in msg or "WR" in msg

    def test_pnl_shows_weekly_when_available(self) -> None:
        """P&L command should show weekly P&L when available."""
        send_mock = MagicMock()
        pnl_data = {"daily_pnl": 1000.0, "trades_today": 1, "wins_today": 1, "weekly_pnl": 5000.0}
        cmd = self._make_commander(pnl_data=pnl_data, send_fn=send_mock)
        cmd._cmd_pnl()
        msg = send_mock.call_args[0][0]
        assert "Week" in msg or "weekly" in msg.lower()

    def test_pnl_handles_error(self) -> None:
        """P&L command should handle errors gracefully."""
        send_mock = MagicMock()
        cmd = self._make_commander(
            pnl_data={"daily_pnl": 1000.0, "trades_today": 1, "wins_today": 1},
            send_fn=send_mock,
        )
        # Make pnl_fn fail on second call (enrichment path)
        cmd._pnl_fn = MagicMock(side_effect=[{"daily_pnl": 1000.0, "trades_today": 1, "wins_today": 1}, ValueError("perf error")])
        cmd._cmd_pnl()
        msg = send_mock.call_args[0][0]
        # Should still get the base P&L message, not an error
        assert "unavailable" not in msg.lower()


class TestCommanderMarkOrderPlaced:
    """Tests for /placed and /unplaced - marks a SignalTracker signal as
    "order actually placed", the same historical field the admin dashboard
    checkbox writes to (core.signals.signal_tracker.mark_order_placed)."""

    def _make_commander(self, send_fn=None):
        return TelegramCommander(
            cfg={"telegram_commander_enabled": True, "BOT_TOKEN": "test:token", "CHAT_ID": "123"},
            queue=MagicMock(),
            workflow=MagicMock(),
            state_fn=MagicMock(return_value={}),
            send_fn=send_fn or MagicMock(),
        )

    def test_placed_with_no_args_shows_usage(self) -> None:
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_mark_order_placed([], "gaurav", placed=True)
        msg = send_mock.call_args[0][0]
        assert "Usage" in msg
        assert "/placed" in msg

    def test_placed_marks_signal_and_confirms(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.return_value = True
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_mark_order_placed(["SIG-42"], "gaurav", placed=True)
        tracker_mock.mark_order_placed.assert_called_once_with("SIG-42", True, "telegram:gaurav")
        msg = send_mock.call_args[0][0]
        assert "SIG-42" in msg
        assert "Marked as ordered" in msg

    def test_unplaced_unmarks_signal(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.return_value = True
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_mark_order_placed(["SIG-42"], "gaurav", placed=False)
        tracker_mock.mark_order_placed.assert_called_once_with("SIG-42", False, "telegram:gaurav")
        msg = send_mock.call_args[0][0]
        assert "Unmarked" in msg

    def test_unknown_signal_id_reports_not_found(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.return_value = False
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_mark_order_placed(["SIG-DOES-NOT-EXIST"], "gaurav", placed=True)
        msg = send_mock.call_args[0][0]
        assert "not found" in msg.lower()

    def test_tracker_exception_is_reported_not_raised(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.side_effect = ValueError("db locked")
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._cmd_mark_order_placed(["SIG-42"], "gaurav", placed=True)  # must not raise
        msg = send_mock.call_args[0][0]
        assert "SIG-42" in msg

    def test_dispatch_routes_placed_command(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.return_value = True
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._dispatch("/placed", ["SIG-99"], "u1", "gaurav")
        tracker_mock.mark_order_placed.assert_called_once_with("SIG-99", True, "telegram:gaurav")

    def test_dispatch_routes_unplaced_command(self, monkeypatch) -> None:
        tracker_mock = MagicMock()
        tracker_mock.mark_order_placed.return_value = True
        monkeypatch.setattr(
            "core.signals.signal_tracker.SignalTracker.get_instance",
            MagicMock(return_value=tracker_mock),
        )
        send_mock = MagicMock()
        cmd = self._make_commander(send_fn=send_mock)
        cmd._dispatch("/unplaced", ["SIG-99"], "u1", "gaurav")
        tracker_mock.mark_order_placed.assert_called_once_with("SIG-99", False, "telegram:gaurav")
