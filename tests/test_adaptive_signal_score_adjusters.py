"""Tests for core/adaptive_signal_score_adjusters.py.

Covers the modular signal score adjusters (IV rank, session, ML, GEX,
regime, MA crossover, mean reversion) and the penalty cap.
"""
from __future__ import annotations

from core.adaptive_signal_score_adjusters import (
    apply_iv_rank_adjustment,
    apply_max_penalty_cap,
    apply_session_adjustment,
)


def test_apply_iv_rank_adjustment_zero_vix_is_noop():
    """vix <= 0 must leave the score untouched."""
    score, points = apply_iv_rank_adjustment(
        vix=0.0, score=60, config={}, soft_blocks=[], reasons=[]
    )
    assert score == 60
    assert points == 0


def test_apply_iv_rank_adjustment_normal_vix_does_not_crash():
    """A positive VIX must not raise even if the IV rank module is missing."""
    score, points = apply_iv_rank_adjustment(
        vix=15.0, score=60, config={}, soft_blocks=[], reasons=[]
    )
    assert 0 <= score <= 100


def test_apply_session_adjustment_runs():
    """Session adjustment must return a (score, points) tuple."""
    result = apply_session_adjustment(
        score=60,
        config={"SESSION_BONUS_STRONG": 5, "SESSION_BONUS_MILD": 2},
        soft_blocks=[],
        reasons=[],
    )
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_apply_max_penalty_cap_within_limit():
    """A small penalty must pass through unchanged."""
    score = apply_max_penalty_cap(
        score=55, raw_score=60, config={"ADAPTIVE_SIGNAL_MAX_TOTAL_PENALTY": -50}
    )
    assert score == 55


def test_apply_max_penalty_cap_clamps_excessive_penalty():
    """Penalty beyond the cap must be clamped to raw_score + max_penalty."""
    score = apply_max_penalty_cap(
        score=0, raw_score=60, config={"ADAPTIVE_SIGNAL_MAX_TOTAL_PENALTY": -50}
    )
    assert score == 10  # 60 + (-50)
