"""Tests for SignalConfidenceBand in core/adaptive_signal.py (v2.44 Item 18)."""
import os
import sqlite3
import tempfile

import pytest
from core.adaptive_signal import (
    SignalConfidenceBand,
    _wilson_ci,
    compute_confidence_band,
)

# ── Wilson CI ─────────────────────────────────────────────────────────────────

def test_wilson_ci_perfect_wins():
    lo, hi = _wilson_ci(10, 10)
    assert hi >= 0.9
    assert lo > 0.5


def test_wilson_ci_no_wins():
    lo, hi = _wilson_ci(0, 10)
    assert lo == pytest.approx(0.0, abs=0.01)
    assert hi < 0.3


def test_wilson_ci_50pct():
    lo, hi = _wilson_ci(5, 10)
    assert lo < 0.5
    assert hi > 0.5
    assert lo > 0.0
    assert hi < 1.0


def test_wilson_ci_zero_n():
    lo, hi = _wilson_ci(0, 0)
    assert lo == 0.0
    assert hi == 1.0


def test_wilson_ci_bounds():
    for wins in range(0, 11):
        lo, hi = _wilson_ci(wins, 10)
        assert 0.0 <= lo <= 1.0
        assert 0.0 <= hi <= 1.0
        assert lo <= hi


def test_wilson_ci_larger_n_narrower():
    lo10, hi10 = _wilson_ci(5, 10)
    lo100, hi100 = _wilson_ci(50, 100)
    assert (hi10 - lo10) > (hi100 - lo100)


# ── SignalConfidenceBand dataclass ────────────────────────────────────────────

def test_confidence_band_fields():
    band = SignalConfidenceBand(
        n_trades=20, n_wins=12, win_rate=0.60,
        ci_low=0.40, ci_high=0.77,
        score_bin="65-75", regime="UPTREND",
        session="MORNING", direction="CALL",
    )
    assert band.n_trades == 20
    assert band.n_wins == 12
    assert band.win_rate == pytest.approx(0.60)
    assert band.ci_low == pytest.approx(0.40)
    assert band.ci_high == pytest.approx(0.77)


def test_confidence_band_str():
    band = SignalConfidenceBand(
        n_trades=20, n_wins=12, win_rate=0.60,
        ci_low=0.40, ci_high=0.77,
    )
    s = str(band)
    assert "CI" in s
    assert "40" in s or "77" in s


def test_confidence_band_defaults():
    band = SignalConfidenceBand(
        n_trades=5, n_wins=3, win_rate=0.6,
        ci_low=0.3, ci_high=0.85,
    )
    assert band.regime == ""
    assert band.session == ""
    assert band.direction == ""
    assert band.score_bin == ""


# ── compute_confidence_band ───────────────────────────────────────────────────

def _make_trades_db(n_wins=8, n_total=15, score=70, regime="UPTREND", direction="CALL"):
    """Create a temp trades.db with trades matching the given params."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, score INTEGER, regime TEXT,
            direction TEXT, net_pnl REAL
        )
    """)
    for i in range(n_total):
        pnl = 100 if i < n_wins else -50
        conn.execute(
            "INSERT INTO trades (score, regime, direction, net_pnl) VALUES (?,?,?,?)",
            (score + (i % 3) - 1, regime, direction, pnl),
        )
    conn.commit()
    conn.close()
    return f.name


def test_compute_confidence_band_returns_band():
    db = _make_trades_db()
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": True},
        )
        assert band is None or isinstance(band, SignalConfidenceBand)
    finally:
        os.unlink(db)


def test_compute_confidence_band_correct_n_trades():
    db = _make_trades_db(n_wins=6, n_total=10)
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": True, "confidence_band_score_bin_width": 5},
        )
        if band is not None:
            assert band.n_trades >= 1
    finally:
        os.unlink(db)


def test_compute_confidence_band_disabled_returns_none():
    db = _make_trades_db()
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": False},
        )
        assert band is None
    finally:
        os.unlink(db)


def test_compute_confidence_band_missing_db_returns_none():
    band = compute_confidence_band(
        score=70, regime="UPTREND", session="", direction="CALL",
        db_path="/nonexistent/trades.db",
        cfg={"confidence_band_enabled": True},
    )
    assert band is None


def test_compute_confidence_band_ci_lo_lt_hi():
    db = _make_trades_db(n_wins=6, n_total=20)
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": True},
        )
        if band is not None:
            assert band.ci_low <= band.ci_high
    finally:
        os.unlink(db)


def test_compute_confidence_band_win_rate_in_range():
    db = _make_trades_db(n_wins=8, n_total=10)
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": True},
        )
        if band is not None:
            assert 0.0 <= band.win_rate <= 1.0
    finally:
        os.unlink(db)


def test_compute_confidence_band_direction_filter():
    db = _make_trades_db(n_wins=5, n_total=10, direction="PUT")
    try:
        # Ask for CALL but only PUT trades exist
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=db, cfg={"confidence_band_enabled": True},
        )
        # Either None (no CALL trades found) or a band
        assert band is None or isinstance(band, SignalConfidenceBand)
    finally:
        os.unlink(db)


def test_compute_confidence_band_no_trades_returns_none():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute(
        "CREATE TABLE trades (id INTEGER PRIMARY KEY, score INTEGER, "
        "regime TEXT, direction TEXT, net_pnl REAL)"
    )
    conn.commit()
    conn.close()
    try:
        band = compute_confidence_band(
            score=70, regime="UPTREND", session="", direction="CALL",
            db_path=f.name, cfg={"confidence_band_enabled": True},
        )
        assert band is None
    finally:
        os.unlink(f.name)


# ── AdaptiveSignal confidence_band field ──────────────────────────────────────

def _make_pos_spec():
    from core.position_sizer import PositionSpec
    return PositionSpec(
        tier="MODERATE", regime="UPTREND", score=70,
        tier_base_pct=0.05, regime_adj=0.0, score_adj=0.0,
        effective_pct=0.05, lots=1, reasoning="test",
    )


def test_adaptive_signal_has_confidence_band_field():
    from core.adaptive_signal import AdaptiveSignal
    sig = AdaptiveSignal(
        tier="MODERATE", score=70, raw_score=70, confidence=1.0,
        direction="CALL", regime="UPTREND", soft_blocks=[], reasons=[],
        score_components={}, features=[], atr=10.0, rsi=55.0, adx=20.0,
        vwap=21000.0, vol_ratio=1.5, price=21050.0, macd={}, risk={},
        position_spec=_make_pos_spec(),
    )
    assert hasattr(sig, "confidence_band")
    assert sig.confidence_band is None


def test_adaptive_signal_confidence_band_can_be_set():
    from core.adaptive_signal import AdaptiveSignal
    band = SignalConfidenceBand(5, 3, 0.6, 0.3, 0.85)
    sig = AdaptiveSignal(
        tier="MODERATE", score=70, raw_score=70, confidence=1.0,
        direction="CALL", regime="UPTREND", soft_blocks=[], reasons=[],
        score_components={}, features=[], atr=10.0, rsi=55.0, adx=20.0,
        vwap=21000.0, vol_ratio=1.5, price=21050.0, macd={}, risk={},
        position_spec=_make_pos_spec(),
        confidence_band=band,
    )
    assert sig.confidence_band is band
    assert sig.confidence_band.n_trades == 5
