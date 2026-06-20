"""Tests for core/implied_move.py - Implied Move Calculator.

Covers:
- ImpliedMove frozen dataclass
- compute_implied_move() with various option chain states
- check_implied_move_gate() pass/fail logic
- get_implied_move_score_adj() bonus/penalty
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.implied_move import (
    ImpliedMove,
    check_implied_move_gate,
    compute_implied_move,
    get_implied_move_score_adj,
)


class TestImpliedMove:
    """ImpliedMove frozen dataclass."""

    def test_fields(self):
        im = ImpliedMove(
            move_pct=1.5, move_points=350.0, weekly_move_pct=1.5,
            daily_move_pct=0.67, atm_call_premium=150.0,
            atm_put_premium=200.0, atm_strike=23500,
        )
        assert im.move_pct == 1.5
        assert im.move_points == 350.0
        assert im.weekly_move_pct == 1.5
        assert im.daily_move_pct == 0.67
        assert im.atm_call_premium == 150.0
        assert im.atm_put_premium == 200.0
        assert im.atm_strike == 23500

    def test_frozen(self):
        im = ImpliedMove(
            move_pct=1.0, move_points=100.0, weekly_move_pct=1.0,
            daily_move_pct=0.5, atm_call_premium=50.0,
            atm_put_premium=50.0, atm_strike=10000,
        )
        with pytest.raises((AttributeError, TypeError)):
            im.move_pct = 2.0


class TestComputeImpliedMove:
    """compute_implied_move()."""

    def test_disabled_returns_none(self):
        result = compute_implied_move({"calls": {}, "puts": {}}, 23500.0, {"implied_move_enabled": False})
        assert result is None

    def test_none_chain_returns_none(self):
        result = compute_implied_move(None, 23500.0, {"implied_move_enabled": True})
        assert result is None

    def test_empty_chain_returns_none(self):
        result = compute_implied_move({"calls": {}, "puts": {}}, 23500.0, {"implied_move_enabled": True})
        assert result is None

    def test_no_common_strikes(self):
        chain = {"calls": {23500: 150.0}, "puts": {23600: 200.0}}
        result = compute_implied_move(chain, 23500.0, {"implied_move_enabled": True})
        assert result is None

    def test_zero_spot(self):
        chain = {"calls": {23500: 150.0}, "puts": {23500: 200.0}}
        result = compute_implied_move(chain, 0.0, {"implied_move_enabled": True})
        assert result is None

    def test_computes_implied_move(self):
        chain = {"calls": {23500: 150.0}, "puts": {23500: 200.0}}
        result = compute_implied_move(chain, 23500.0, {"implied_move_enabled": True})
        assert result is not None
        assert result.atm_strike == 23500
        assert result.atm_call_premium == 150.0
        assert result.atm_put_premium == 200.0
        # Straddle = 150 + 200 = 350, move_pct = 350/23500*100 = 1.489%
        assert result.move_pct == pytest.approx(1.489, abs=0.01)
        assert result.daily_move_pct == pytest.approx(1.489 / 2.236, abs=0.01)  # / sqrt(5)

    def test_finds_atm_strike(self):
        chain = {
            "calls": {23400: 300.0, 23600: 100.0},
            "puts": {23400: 100.0, 23600: 350.0},
        }
        result = compute_implied_move(chain, 23550.0, {"implied_move_enabled": True})
        assert result is not None
        assert result.atm_strike == 23600  # 23600 is closest to 23550 (50 away vs 150)

    def test_type_error_logged(self):
        chain = {"calls": {23500: "invalid"}, "puts": {23500: 200.0}}
        result = compute_implied_move(chain, 23500.0, {"implied_move_enabled": True})
        assert result is None


class TestCheckImpliedMoveGate:
    """check_implied_move_gate()."""

    def make_move(self, weekly=1.5):
        return ImpliedMove(
            move_pct=weekly, move_points=350.0, weekly_move_pct=weekly,
            daily_move_pct=weekly / 2.236, atm_call_premium=150.0,
            atm_put_premium=200.0, atm_strike=23500,
        )

    def test_disabled_passes(self):
        im = self.make_move()
        passed, reason = check_implied_move_gate(im, 2.0, "CALL", {"implied_move_enabled": False})
        assert passed is True
        assert reason == ""

    def test_none_implied_move_passes(self):
        passed, reason = check_implied_move_gate(None, 2.0, "CALL", {"implied_move_enabled": True})
        assert passed is True
        assert reason == ""

    def test_signal_exceeds_required(self):
        im = self.make_move(weekly=1.5)
        cfg = {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2}
        # Required = 1.5 * 1.2 = 1.8%, signal = 2.0% -> PASS
        passed, reason = check_implied_move_gate(im, 2.0, "CALL", cfg)
        assert passed is True

    def test_signal_below_required(self):
        im = self.make_move(weekly=1.5)
        cfg = {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2}
        # Required = 1.5 * 1.2 = 1.8%, signal = 1.5% -> FAIL
        passed, reason = check_implied_move_gate(im, 1.5, "CALL", cfg)
        assert passed is False
        assert "implied_move_gate" in reason
        assert "1.80%" in reason

    def test_custom_multiplier(self):
        im = self.make_move(weekly=2.0)
        cfg = {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.5}
        # Required = 2.0 * 1.5 = 3.0%, signal = 2.5% -> FAIL
        passed, reason = check_implied_move_gate(im, 2.5, "PUT", cfg)
        assert passed is False
        assert "3.00%" in reason


class TestGetImpliedMoveScoreAdj:
    """get_implied_move_score_adj()."""

    def make_move(self, weekly=1.5):
        return ImpliedMove(
            move_pct=weekly, move_points=350.0, weekly_move_pct=weekly,
            daily_move_pct=weekly / 2.236, atm_call_premium=150.0,
            atm_put_premium=200.0, atm_strike=23500,
        )

    def test_disabled_returns_zero(self):
        im = self.make_move()
        assert get_implied_move_score_adj(im, 2.0, {"implied_move_enabled": False}) == 0

    def test_passes_returns_zero(self):
        im = self.make_move(weekly=1.0)
        cfg = {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.2}
        assert get_implied_move_score_adj(im, 2.0, cfg) == 0  # 2.0 >= 1.2

    def test_fails_returns_minus_5(self):
        im = self.make_move(weekly=2.0)
        cfg = {"implied_move_enabled": True, "implied_move_min_edge_mult": 1.5}
        # Required = 3.0%, signal = 2.0% -> FAIL
        assert get_implied_move_score_adj(im, 2.0, cfg) == -5

    def test_none_implied_move_returns_zero(self):
        assert get_implied_move_score_adj(None, 2.0, {"implied_move_enabled": True}) == 0
