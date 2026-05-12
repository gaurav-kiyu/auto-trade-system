"""Tests for Item 5 — TimeframeAgreement in core/adaptive_signal.py."""
import pytest
from core.adaptive_signal import TimeframeAgreement, compute_timeframe_agreement


def _cfg(enabled=True, block=False):
    return {
        "timeframe_divergence_block_enabled": block,
        "timeframe_divergence_bonus": 5,
    }


def _make_frame(direction: str = "UP", vol_ratio: float = 1.5):
    """Minimal frame dict for timeframe agreement check."""
    return {"direction": direction, "vol_ratio": vol_ratio}


# ── basic construction ────────────────────────────────────────────────────────

def test_timeframe_agreement_fields():
    ta = TimeframeAgreement(
        agreement_score=1.0, bullish_count=3,
        bearish_count=0, divergence_detail="all UP",
    )
    assert ta.agreement_score == 1.0
    assert ta.bullish_count == 3


def test_all_bullish_agreement():
    ta = compute_timeframe_agreement("UP", "UP", "UP", _cfg())
    assert ta.bullish_count == 3
    assert ta.bearish_count == 0
    assert ta.agreement_score == 1.0


def test_all_bearish_agreement():
    ta = compute_timeframe_agreement("DOWN", "DOWN", "DOWN", _cfg())
    assert ta.bullish_count == 0
    assert ta.bearish_count == 3
    assert ta.agreement_score == 1.0


def test_split_2_1_partial():
    # 2 bullish, 1 bearish
    ta = compute_timeframe_agreement("UP", "UP", "DOWN", _cfg())
    assert ta.bullish_count == 2
    assert ta.bearish_count == 1
    assert 0.0 < ta.agreement_score < 1.0


def test_full_divergence_1_1():
    # 1m=UP, 5m=DOWN, 15m=FLAT
    ta = compute_timeframe_agreement("UP", "DOWN", "FLAT", _cfg())
    assert ta.bullish_count == 1
    assert ta.bearish_count == 1


def test_divergence_detail_string():
    ta = compute_timeframe_agreement("UP", "DOWN", "FLAT", _cfg())
    assert isinstance(ta.divergence_detail, str)
    assert len(ta.divergence_detail) > 0


def test_all_flat_neutral():
    ta = compute_timeframe_agreement("FLAT", "FLAT", "FLAT", _cfg())
    assert ta.bullish_count == 0
    assert ta.bearish_count == 0


def test_agreement_score_range():
    for d1m, d5m, d15m in [
        ("UP", "UP", "UP"),
        ("UP", "DOWN", "FLAT"),
        ("DOWN", "DOWN", "UP"),
        ("FLAT", "FLAT", "FLAT"),
    ]:
        ta = compute_timeframe_agreement(d1m, d5m, d15m, _cfg())
        assert 0.0 <= ta.agreement_score <= 1.0


def test_returns_timeframe_agreement_instance():
    result = compute_timeframe_agreement("UP", "UP", "DOWN", _cfg())
    assert isinstance(result, TimeframeAgreement)
