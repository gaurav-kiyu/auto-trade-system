"""Unit test suite for Outcome Analytics: Expectancy, MFE/MAE, Duration, and Segmentation.

Tests empirical outcome calculations without mutating production parameters.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.signals.signal_outcome_tracker import SignalOutcomeTracker
from core.signals.signal_tracker import SignalTracker


@pytest.fixture
def temp_tracker(tmp_path: Path) -> SignalOutcomeTracker:
    db_file = tmp_path / "test_expectancy_signals.db"
    # SignalTracker initializes system_signals table
    _ = SignalTracker(db_path=db_file)
    tracker = SignalOutcomeTracker(db_path=db_file)
    return tracker


def test_outcome_expectancy_and_loss_rate(temp_tracker: SignalOutcomeTracker):
    """Verify exact mathematical expectancy, win rate, and loss rate calculation."""
    conn = temp_tracker._get_conn()
    cur = conn.cursor()

    # Insert 2 wins, 1 loss, 1 expired, 1 ambiguous
    signals = [
        ("SIG-W1", "2026-09-17T10:00:00", "2026-09-17T10:30:00", "TARGET_1_HIT", "T1", 4.0, "BUY", 85, "TIER_1", "EQUITY", "RELIANCE", 100.0, 95.0, 104.0, 108.0),
        ("SIG-W2", "2026-09-17T10:00:00", "2026-09-17T11:00:00", "TARGET_2_HIT", "T2", 5.0, "BUY", 82, "TIER_1", "EQUITY", "INFY", 100.0, 95.0, 105.0, 110.0),
        ("SIG-L1", "2026-09-17T10:00:00", "2026-09-17T10:15:00", "SL_HIT", "SL", -3.0, "SELL", 72, "TIER_2", "EQUITY", "TCS", 100.0, 103.0, 95.0, 90.0),
        ("SIG-E1", "2026-09-17T10:00:00", "2026-09-17T15:30:00", "EXPIRED", "EXPIRED", 0.0, "BUY", 65, "TIER_3", "FNO", "NIFTY", 100.0, 95.0, 105.0, 110.0),
        ("SIG-A1", "2026-09-17T10:00:00", "2026-09-17T10:05:00", "AMBIGUOUS", "AMBIGUOUS", 0.0, "SELL", 78, "TIER_2", "FNO", "BANKNIFTY", 100.0, 105.0, 95.0, 90.0),
    ]

    for sig_id, ts, ft_ts, status, ft, pnl, direction, score, tier, cat, sym, ep, sl, t1, t2 in signals:
        cur.execute(
            """INSERT INTO system_signals (
                signal_id, timestamp, created_date, created_week, created_month, created_year,
                symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
                current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
            ) VALUES (?, ?, '2026-09-17', '2026-W38', '2026-09', '2026', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'EXACT_OBSERVATION')""",
            (sig_id, ts, sym, cat, direction, score, tier, ep, sl, t1, t2, ep, status, pnl, ft, ft_ts, ep),
        )
    conn.commit()
    conn.close()

    stats = temp_tracker.get_outcome_statistics(timeframe="all")

    # Total = 5, Resolved = 3 (2 T1 + 1 SL)
    assert stats["total_signals"] == 5
    assert stats["resolved_signals"] == 3
    assert stats["t1_hits"] == 2
    assert stats["sl_hits"] == 1
    assert stats["expired"] == 1
    assert stats["ambiguous"] == 1

    # Win rate = 2/3 = 66.67%, Loss rate = 1/3 = 33.33%
    assert stats["win_rate_pct"] == 66.67
    assert stats["loss_rate_pct"] == 33.33

    # Avg win = (4.0 + 5.0) / 2 = 4.50
    # Avg loss = 3.0 / 1 = 3.00
    assert stats["avg_win_pnl"] == 4.50
    assert stats["avg_loss_pnl"] == 3.00

    # Mathematical expectancy = (2/3 * 4.5) - (1/3 * 3.0) = 3.0 - 1.0 = 2.00
    assert stats["expectancy_pct"] == 2.00
    assert stats["expectancy_display"] == "+2.00%"


def test_zero_resolved_signals_expectancy(temp_tracker: SignalOutcomeTracker):
    """Verify behavior when no signals are resolved yet."""
    conn = temp_tracker._get_conn()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, outcome_confidence
        ) VALUES ('SIG-OPEN-1', '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                  'RELIANCE', 'EQUITY', 'BUY', 85, 'TIER_1', 100.0, 95.0, 104.0, 108.0, 100.0, 'OPEN', 0.0, '', 'POLLING')"""
    )
    conn.commit()
    conn.close()

    stats = temp_tracker.get_outcome_statistics(timeframe="all")
    assert stats["total_signals"] == 1
    assert stats["resolved_signals"] == 0
    assert stats["win_rate_pct"] is None
    assert stats["loss_rate_pct"] == 0.0
    assert stats["expectancy_pct"] is None
    assert "N/A" in stats["expectancy_display"]


def test_mfe_and_mae_tracking(temp_tracker: SignalOutcomeTracker):
    """Verify MFE and MAE excursion tracking with historical events."""
    conn = temp_tracker._get_conn()
    cur = conn.cursor()

    # Buy trade: entry = 100.0. Events: 104.0 (fav +4%), 98.0 (adv 2%) -> MFE = 4.0%, MAE = 2.0%
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
        ) VALUES ('SIG-MFE-1', '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                  'TATAMOTORS', 'EQUITY', 'BUY', 85, 'TIER_1', 100.0, 95.0, 104.0, 108.0, 104.0, 'TARGET_1_HIT', 4.0, 'T1', '2026-09-17T10:30:00', 104.0, 'EXACT_OBSERVATION')"""
    )
    cur.execute(
        "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) VALUES ('SIG-MFE-1', '2026-09-17T10:10:00', 98.0, 0, 0, 0)"
    )
    cur.execute(
        "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) VALUES ('SIG-MFE-1', '2026-09-17T10:30:00', 104.0, 0, 1, 0)"
    )

    # Sell trade: entry = 200.0. Events: 190.0 (fav +5%), 204.0 (adv 2%) -> MFE = 5.0%, MAE = 2.0%
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
        ) VALUES ('SIG-MFE-2', '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                  'SBIN', 'EQUITY', 'SELL', 80, 'TIER_1', 200.0, 206.0, 190.0, 180.0, 190.0, 'TARGET_1_HIT', 5.0, 'T1', '2026-09-17T10:45:00', 190.0, 'EXACT_OBSERVATION')"""
    )
    cur.execute(
        "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) VALUES ('SIG-MFE-2', '2026-09-17T10:15:00', 204.0, 0, 0, 0)"
    )
    cur.execute(
        "INSERT INTO signal_outcome_events (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2) VALUES ('SIG-MFE-2', '2026-09-17T10:45:00', 190.0, 0, 1, 0)"
    )

    conn.commit()
    conn.close()

    stats = temp_tracker.get_outcome_statistics(timeframe="all")

    # Signal 1: MFE = 4.0%, MAE = 2.0%
    # Signal 2: MFE = 5.0%, MAE = 2.0%
    # Avg MFE = 4.5%, Max MFE = 5.0%
    # Avg MAE = 2.0%, Max MAE = 2.0%
    assert stats["avg_mfe_pct"] == 4.50
    assert stats["max_mfe_pct"] == 5.00
    assert stats["avg_mae_pct"] == 2.00
    assert stats["max_mae_pct"] == 2.00
    assert stats["mfe_stats"]["samples"] == 2


def test_duration_to_first_touch(temp_tracker: SignalOutcomeTracker):
    """Verify average duration to first touch metrics."""
    conn = temp_tracker._get_conn()
    cur = conn.cursor()

    # Win: 30 minutes duration (10:00 -> 10:30)
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
        ) VALUES ('SIG-DUR-1', '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                  'TCS', 'EQUITY', 'BUY', 85, 'TIER_1', 100.0, 95.0, 104.0, 108.0, 104.0, 'TARGET_1_HIT', 4.0, 'T1', '2026-09-17T10:30:00', 104.0, 'EXACT_OBSERVATION')"""
    )
    # Loss: 15 minutes duration (10:00 -> 10:15)
    cur.execute(
        """INSERT INTO system_signals (
            signal_id, timestamp, created_date, created_week, created_month, created_year,
            symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
            current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
        ) VALUES ('SIG-DUR-2', '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                  'INFY', 'EQUITY', 'BUY', 75, 'TIER_2', 100.0, 95.0, 104.0, 108.0, 95.0, 'SL_HIT', -5.0, 'SL', '2026-09-17T10:15:00', 95.0, 'EXACT_OBSERVATION')"""
    )

    conn.commit()
    conn.close()

    stats = temp_tracker.get_outcome_statistics(timeframe="all")
    assert stats["avg_duration_to_first_touch_mins"] == 22.5
    assert stats["avg_duration_to_win_mins"] == 30.0
    assert stats["avg_duration_to_loss_mins"] == 15.0


def test_segmentation_with_sample_size_warnings(temp_tracker: SignalOutcomeTracker):
    """Verify multi-dimensional segmentation and sample size warnings (<5 samples)."""
    conn = temp_tracker._get_conn()
    cur = conn.cursor()

    # Insert 6 signals for BUY direction (sample >= 5) and 2 for SELL (sample < 5)
    for i in range(1, 7):
        cur.execute(
            """INSERT INTO system_signals (
                signal_id, timestamp, created_date, created_week, created_month, created_year,
                symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
                current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
            ) VALUES (?, '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                      'RELIANCE', 'EQUITY', 'BUY', 85, 'TIER_1', 100.0, 95.0, 104.0, 108.0, 104.0, 'TARGET_1_HIT', 4.0, 'T1', '2026-09-17T10:30:00', 104.0, 'EXACT_OBSERVATION')""",
            (f"SIG-SEG-BUY-{i}",),
        )

    for i in range(1, 3):
        cur.execute(
            """INSERT INTO system_signals (
                signal_id, timestamp, created_date, created_week, created_month, created_year,
                symbol, category, direction, score, tier, entry_price, stop_loss, target_1, target_2,
                current_price, status, pnl_pct, first_touch, first_touch_at, first_touch_price, outcome_confidence
            ) VALUES (?, '2026-09-17T10:00:00', '2026-09-17', '2026-W38', '2026-09', '2026',
                      'TCS', 'EQUITY', 'SELL', 75, 'TIER_2', 100.0, 105.0, 96.0, 92.0, 105.0, 'SL_HIT', -5.0, 'SL', '2026-09-17T10:20:00', 105.0, 'EXACT_OBSERVATION')""",
            (f"SIG-SEG-SELL-{i}",),
        )

    conn.commit()
    conn.close()

    stats = temp_tracker.get_outcome_statistics(timeframe="all")
    assert stats["total_signals"] == 8
    assert stats["sample_size_warning"] is False

    seg = stats["segmentation"]
    assert "by_direction" in seg
    assert "by_tier" in seg
    assert "by_category" in seg
    assert "by_score_band" in seg
    assert "by_symbol" in seg

    # BUY segment has 6 samples -> sample_size_warning is False
    buy_metrics = seg["by_direction"]["BUY"]
    assert buy_metrics["total_signals"] == 6
    assert buy_metrics["sample_size_warning"] is False
    assert buy_metrics["warning"] is None
    assert buy_metrics["win_rate_pct"] == 100.0

    # SELL segment has 2 samples -> sample_size_warning is True
    sell_metrics = seg["by_direction"]["SELL"]
    assert sell_metrics["total_signals"] == 2
    assert sell_metrics["sample_size_warning"] is True
    assert "Low sample size" in sell_metrics["warning"]
    assert sell_metrics["loss_rate_pct"] == 100.0
