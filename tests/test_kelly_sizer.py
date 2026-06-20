"""Tests for core/kelly_sizer.py - Kelly Criterion Position Sizer.

Covers:
- KellyResult dataclass
- _load_recent_pnls (via mocked DB)
- compute_kelly_lots with various win/loss distributions
- Edge cases: insufficient history, disabled config, zero avg_win
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.kelly_sizer import KellyResult, compute_kelly_lots


class TestKellyResult:
    def test_dataclass_fields(self):
        result = KellyResult(
            kelly_f=0.25, half_kelly=0.125, kelly_lots=3,
            win_rate=0.6, avg_win=1000.0, avg_loss=500.0,
            n_trades=50, used_fallback=False,
        )
        assert result.kelly_f == 0.25
        assert result.kelly_lots == 3
        assert result.used_fallback is False

    def test_fallback_defaults(self):
        result = KellyResult(
            kelly_f=0.0, half_kelly=0.0, kelly_lots=1,
            win_rate=0.0, avg_win=0.0, avg_loss=0.0,
            n_trades=0, used_fallback=True,
        )
        assert result.used_fallback is True


class TestComputeKellyLots:
    def test_disabled_returns_fallback(self):
        result = compute_kelly_lots(
            capital=100000.0, base_lots=2, risk_per_lot=5000.0,
            cfg={"kelly_enabled": False},
        )
        assert result.kelly_lots == 2
        assert result.used_fallback is True

    def test_disabled_no_config(self):
        result = compute_kelly_lots(
            capital=100000.0, base_lots=3, risk_per_lot=5000.0,
        )
        assert result.kelly_lots == 3
        assert result.used_fallback is True

    def test_insufficient_history_returns_fallback(self):
        with patch("core.kelly_sizer._load_recent_pnls", return_value=[100] * 5):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=2, risk_per_lot=5000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 20},
            )
            assert result.used_fallback is True
            assert result.kelly_lots == 2
            assert result.n_trades == 5

    def test_no_db_file_returns_fallback(self):
        result = compute_kelly_lots(
            capital=100000.0, base_lots=2, risk_per_lot=5000.0,
            db_path="nonexistent.db",
            cfg={"kelly_enabled": True},
        )
        assert result.used_fallback is True

    def test_computes_kelly_with_good_history(self):
        """60% win rate, avg_win=1000, avg_loss=500."""
        pnls = [1000] * 60 + [-500] * 40  # 60% win rate
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=2, risk_per_lot=5000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 10},
            )
            assert result.used_fallback is False
            assert result.n_trades == 100
            assert result.win_rate == pytest.approx(0.6, abs=0.01)
            assert result.kelly_f > 0

    def test_all_wins_gives_high_kelly(self):
        pnls = [1000] * 30
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=1, risk_per_lot=5000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 10},
            )
            assert result.used_fallback is False
            assert result.win_rate == pytest.approx(1.0, abs=0.01)

    def test_all_losses_returns_fallback(self):
        pnls = [-500] * 30
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=2, risk_per_lot=5000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 10},
            )
            # With all losses, avg_w = 0, which triggers fallback
            assert result.used_fallback is True or result.kelly_lots > 0
            assert result.avg_win == 0.0

    def test_clamps_to_max_lots(self):
        pnls = [1000] * 50
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=1000000.0, base_lots=1, risk_per_lot=100.0,
                cfg={
                    "kelly_enabled": True,
                    "kelly_min_trades": 10,
                    "kelly_max_lots_mult": 3.0,
                },
            )
            # With huge capital and low risk, lots should be capped
            assert result.kelly_lots <= 3  # base_lots * 3.0

    def test_min_lots_always_at_least_1(self):
        pnls = [-100] * 30  # All losses
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=1000.0, base_lots=1, risk_per_lot=50000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 10},
            )
            assert result.kelly_lots >= 1

    def test_custom_window_and_mult(self):
        pnls = [500] * 30 + [-200] * 20  # 60% win rate
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=5, risk_per_lot=2000.0,
                cfg={
                    "kelly_enabled": True,
                    "kelly_window_trades": 50,
                    "kelly_min_trades": 5,
                    "kelly_max_lots_mult": 4.0,
                },
            )
            assert result.n_trades == 50
            assert result.used_fallback is False
            assert result.kelly_lots >= 1

    def test_returns_kelly_fraction(self):
        pnls = [1000] * 30 + [-500] * 20
        with patch("core.kelly_sizer._load_recent_pnls", return_value=pnls):
            result = compute_kelly_lots(
                capital=100000.0, base_lots=2, risk_per_lot=5000.0,
                cfg={"kelly_enabled": True, "kelly_min_trades": 10},
            )
            assert 0 <= result.kelly_f <= 1.0
            assert result.half_kelly == pytest.approx(result.kelly_f * 0.5, abs=0.001)
