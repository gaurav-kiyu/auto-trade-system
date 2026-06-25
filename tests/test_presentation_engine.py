"""Tests for core.presentation_engine - operator-facing text formatting."""

from __future__ import annotations

from core.presentation_engine import PresentationEngine


class TestPresentationEngine:
    """Tests for PresentationEngine - text formatting for alerts and dashboard."""

    def setup_method(self) -> None:
        self.engine = PresentationEngine()

    def test_money_format(self) -> None:
        assert self.engine._money(1234.5) == "₹1,234.5"
        assert self.engine._money(0) == "₹0.0"

    def test_money_negative(self) -> None:
        assert self.engine._money(-500.0) == "₹-500.0"

    def test_money_from_string(self) -> None:
        assert self.engine._money("1234.5") == "₹1,234.5"

    def test_money_custom_currency(self) -> None:
        engine = PresentationEngine(currency_symbol="$")
        assert engine._money(100.0) == "$100.0"

    def test_pnl_default_formatter(self) -> None:
        # Without custom formatter, uses _money
        assert self.engine._pnl(1000.0) == "₹1,000.0"

    def test_pnl_custom_formatter(self) -> None:
        engine = PresentationEngine(pnl_formatter=lambda v: f"{v:+.2f} pts")
        assert engine._pnl(100.0) == "+100.00 pts"
        assert engine._pnl(-50.0) == "-50.00 pts"

    def test_manual_signal_message(self) -> None:
        msg = self.engine.manual_signal_message(
            name="NIFTY", signal_type="CALL", strike=18500,
            entry=18550.0, qty=1, sl=18450.0, target=18700.0,
            net_rr=2.5, score=75.0, why="Breakout confirmation",
        )
        assert "NIFTY" in msg
        assert "CALL" in msg
        assert "18500" in msg
        assert "₹18,550.0" in msg  # entry formatted
        assert "₹18,450.0" in msg  # sl formatted
        assert "2.5" in msg
        assert "75" in msg

    def test_new_trade_message(self) -> None:
        msg = self.engine.new_trade_message(
            name="BANKNIFTY", action="BUY", strike=44000,
            entry=44100.0, qty=2, target=44500.0,
            risk_amt=2000.0, profit_amt=4000.0, sl=43900.0,
            why="Strong momentum", score=82.0, iv=15.5, vix=14.2,
            net_rr=2.0, mode_label="PAPER",
        )
        assert "BANKNIFTY" in msg
        assert "BUY" in msg
        assert "44000" in msg
        assert "₹44,100.0" in msg
        assert "PAPER" in msg
        assert "82" in msg
        assert "15.5" in msg
        assert "14.2" in msg

    def test_dashboard_broker_mode_paper(self) -> None:
        text = self.engine.dashboard_broker_mode(
            execution_mode="PAPER", broker_backend="kite", broker_api_enabled=False,
        )
        assert "Paper mode" in text

    def test_dashboard_broker_mode_manual(self) -> None:
        text = self.engine.dashboard_broker_mode(
            execution_mode="MANUAL", broker_backend="none", broker_api_enabled=False,
        )
        assert "Manual mode" in text

    def test_dashboard_broker_mode_auto(self) -> None:
        text = self.engine.dashboard_broker_mode(
            execution_mode="AUTO", broker_backend="kite", broker_api_enabled=True,
        )
        assert "Auto mode" in text
        assert "kite" in text.lower()

    def test_dashboard_broker_mode_signals(self) -> None:
        text = self.engine.dashboard_broker_mode(
            execution_mode="SIGNALS", broker_backend="", broker_api_enabled=False,
        )
        assert "Signals mode" in text

    def test_dashboard_broker_mode_named(self) -> None:
        text = self.engine.dashboard_broker_mode_named(
            execution_mode="AUTO", broker_name="Zerodha", broker_api_enabled=True,
        )
        assert "Auto mode" in text
        assert "Zerodha" in text

    def test_signal_summary(self) -> None:
        sig = {"name": "NIFTY", "direction": "CALL", "score": 85, "threshold": 60}
        text = self.engine.signal_summary(sig)
        assert "NIFTY" in text
        assert "CALL" in text
        assert "85" in text
        assert "60" in text

    def test_signal_summary_with_context(self) -> None:
        sig = {"name": "NIFTY", "direction": "CALL", "score": 75, "threshold": 60}
        text = self.engine.signal_summary(sig, confidence_text="High IV", learner_text="Trending regime")
        assert "High IV" in text
        assert "Trending regime" in text

    def test_signal_summary_default_why(self) -> None:
        sig = {"name": "NIFTY", "direction": "PUT", "score": 65, "threshold": 50}
        text = self.engine.signal_summary(sig)
        assert "Signal passed filters" in text
