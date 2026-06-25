"""Tests for core.dashboard_engine - frontend text builder."""

from __future__ import annotations

from core.dashboard_engine import DashboardEngine


class TestDashboardEngine:
    """Tests for DashboardEngine - operator-friendly dashboard text."""

    def setup_method(self) -> None:
        self.engine = DashboardEngine()

    def test_none_input_returns_placeholder(self) -> None:
        text, color = self.engine.format_trading_desk_line(None)
        assert "next scan cycle" in text
        assert color == "#8b949e"

    def test_empty_dict_returns_defaults(self) -> None:
        text, color = self.engine.format_trading_desk_line({})
        assert isinstance(text, str)
        assert isinstance(color, str)

    def test_vix_displayed(self) -> None:
        text, _ = self.engine.format_trading_desk_line({"vix": 14.5, "vix_block": 20, "vix_halt": 30})
        assert "14.5" in text
        assert "20" in text
        assert "30" in text

    def test_vix_none(self) -> None:
        text, _ = self.engine.format_trading_desk_line({"vix": None, "vix_block": 20, "vix_halt": 30})
        assert "n/a" in text

    def test_loss_pct_displayed(self) -> None:
        text, _ = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "loss_pct_limit": 45.3,
        })
        assert "45%" in text

    def test_min_rr_displayed(self) -> None:
        text, _ = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "min_rr": 1.5,
        })
        assert "1.50" in text

    def test_sl_target_displayed(self) -> None:
        text, _ = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "sl_pct": 0.08, "tgt_pct": 0.15,
        })
        assert "8%" in text
        assert "15%" in text

    def test_circuit_displayed(self) -> None:
        text, _ = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "circuit": "NORMAL",
        })
        assert "NORMAL" in text

    def test_hard_halt_shown(self) -> None:
        text, color = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "circuit": "NORMAL", "hard_halt": True,
        })
        assert "HARD HALT" in text
        assert color == "#f85149"

    def test_trip_circuit_changes_color(self) -> None:
        _, color = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "circuit": "TRIPPED",
        })
        assert color == "#f0883e"

    def test_sig_quality_appended(self) -> None:
        text, _ = self.engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "circuit": "NORMAL", "sig_quality": "GOOD",
        })
        assert "GOOD" in text

    def test_custom_execution_label_fn(self) -> None:
        def label_fn(dsk):
            return f"MODE:{dsk.get('mode', '?')}"
        engine = DashboardEngine(execution_label_fn=label_fn)
        text, _ = engine.format_trading_desk_line({
            "vix": 14, "vix_block": 20, "vix_halt": 30,
            "circuit": "NORMAL", "mode": "PAPER",
        })
        assert "MODE:PAPER" in text
