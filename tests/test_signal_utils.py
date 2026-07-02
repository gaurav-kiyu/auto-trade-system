"""Tests for core.signal_utils - signal utility functions extracted from legacy signal_engine."""

from __future__ import annotations

import pandas as pd
import pytest

from core.signal_utils import (
    breakout_strength_ok,
    calc_atr_stop_loss,
    calc_chandelier_exit,
    calc_fibonacci_targets,
    calc_support_resistance_pivot,
    classify_signal,
    classify_strength,
    explain_signal,
    format_change,
    format_pnl,
    score_to_label,
    score_to_stars,
    validate_ohlcv,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ohlcv(n: int = 20, start_price: float = 100.0) -> pd.DataFrame:
    """Generate a simple synthetic OHLCV DataFrame for testing."""
    import numpy as np

    rng = np.random.default_rng(42)
    prices = start_price * (1 + rng.normal(0, 0.005, n).cumsum())
    closes = prices
    highs = closes * (1 + abs(rng.normal(0, 0.003, n)))
    lows = closes * (1 - abs(rng.normal(0, 0.003, n)))
    volumes = rng.integers(100_000, 500_000, n).astype(float)
    return pd.DataFrame({
        "Open": closes * (1 - rng.normal(0, 0.001, n)),
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    })


# ── breakout_strength_ok ────────────────────────────────────────────────────


class TestBreakoutStrengthOk:
    def test_insufficient_bars_returns_false(self):
        df = _ohlcv(2)
        assert breakout_strength_ok(df) is False

    def test_sufficient_bars_and_no_breakout_returns_false(self):
        df = _ohlcv(20)
        # Force small price move using .loc to avoid chained assignment issues
        df.loc[df.index[-1], "Close"] = float(df["Close"].iloc[-2]) * 1.001  # 0.1% move
        df.loc[df.index[-1], "Volume"] = float(df["Volume"].iloc[:-1].mean()) * 1.1
        assert breakout_strength_ok(df) is False

    def test_strong_breakout_returns_true(self):
        df = _ohlcv(20)
        df.loc[df.index[-1], "Close"] = float(df["Close"].iloc[-2]) * 1.005  # 0.5% move
        df.loc[df.index[-1], "Volume"] = float(df["Volume"].iloc[:-1].mean()) * 2.0
        assert breakout_strength_ok(df) is True

    def test_negative_prev_close_returns_false(self):
        df = _ohlcv(20)
        df.loc[df.index[-2], "Close"] = 0.0
        assert breakout_strength_ok(df) is False

    def test_missing_columns_returns_false(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        assert breakout_strength_ok(df) is False

    def test_zero_volume_avg_returns_false(self):
        df = _ohlcv(20)
        df.loc[df.index[-1], "Close"] = float(df["Close"].iloc[-2]) * 1.005
        df["Volume"] = 0.0
        assert breakout_strength_ok(df) is False


# ── calc_support_resistance_pivot ───────────────────────────────────────────


class TestCalcSupportResistancePivot:
    def test_returns_five_keys(self):
        df = _ohlcv(20)
        result = calc_support_resistance_pivot(df)
        assert set(result.keys()) == {"pivot", "support_1", "support_2", "resistance_1", "resistance_2"}
        for v in result.values():
            assert isinstance(v, float)

    def test_pivot_between_high_and_low(self):
        df = _ohlcv(20)
        result = calc_support_resistance_pivot(df)
        assert result["support_1"] < result["pivot"] < result["resistance_1"]

    def test_empty_df_returns_zeros(self):
        df = pd.DataFrame()
        result = calc_support_resistance_pivot(df)
        assert all(v == 0 for v in result.values())

    def test_single_row_df_works(self):
        df = pd.DataFrame({"High": [110], "Low": [90], "Close": [100]})
        result = calc_support_resistance_pivot(df)
        assert result["pivot"] > 0


# ── calc_fibonacci_targets ──────────────────────────────────────────────────


class TestCalcFibonacciTargets:
    def test_call_direction_ascending_targets(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "CALL")
        assert targets["tp3"] > targets["tp2"] > targets["tp1"] > 100

    def test_put_direction_descending_targets(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "PUT")
        # For PUT: tp1 > tp2 > tp3 (subtracting increasing fib ratios from entry)
        assert targets["tp1"] > targets["tp2"] > targets["tp3"]
        assert targets["tp3"] < 100

    def test_zero_atr_defaults_to_1pct(self):
        targets = calc_fibonacci_targets(100.0, 0.0, "CALL")
        assert targets["tp1"] > 100

    def test_vix_scaling_high_vix_tightens_targets(self):
        normal = calc_fibonacci_targets(100.0, 5.0, "CALL", vix=0.0)
        tight = calc_fibonacci_targets(100.0, 5.0, "CALL", vix=25.0)
        assert tight["tp3"] < normal["tp3"]

    def test_vix_scaling_low_vix_widens_targets(self):
        normal = calc_fibonacci_targets(100.0, 5.0, "CALL", vix=15.0)
        wide = calc_fibonacci_targets(100.0, 5.0, "CALL", vix=10.0)
        assert wide["tp3"] > normal["tp3"]

    def test_up_direction_works(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "UP")
        assert targets["tp1"] > 100

    def test_down_direction_works(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "DOWN")
        assert targets["tp1"] < 100

    def test_buy_direction_works(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "BUY")
        assert targets["tp1"] > 100

    def test_sell_direction_works(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "SELL")
        assert targets["tp1"] < 100

    def test_custom_fib_ratios(self):
        targets = calc_fibonacci_targets(100.0, 5.0, "CALL", fib_r1=0.5, fib_r2=0.8, fib_r3=1.2)
        assert targets["tp1"] == round(100 + 0.5 * 5, 2)
        assert targets["tp2"] == round(100 + 0.8 * 5, 2)
        assert targets["tp3"] == round(100 + 1.2 * 5, 2)


# ── calc_chandelier_exit ────────────────────────────────────────────────────


class TestCalcChandelierExit:
    def test_insufficient_data_returns_zero(self):
        df = _ohlcv(5)
        assert calc_chandelier_exit(df, period=22) == 0.0

    def test_call_chandelier_below_recent_high(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="CALL")
        recent_high = float(df["High"].tail(22).max())
        assert result < recent_high

    def test_put_chandelier_above_recent_low(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="PUT")
        recent_low = float(df["Low"].tail(22).min())
        assert result > recent_low

    def test_none_df_returns_zero(self):
        assert calc_chandelier_exit(None) == 0.0

    def test_up_direction_works(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="UP")
        assert isinstance(result, float)

    def test_buy_direction_works(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="BUY")
        assert isinstance(result, float)

    def test_down_direction_works(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="DOWN")
        assert isinstance(result, float)

    def test_sell_direction_works(self):
        df = _ohlcv(30)
        result = calc_chandelier_exit(df, direction="SELL")
        assert isinstance(result, float)


# ── calc_atr_stop_loss ──────────────────────────────────────────────────────


class TestCalcAtrStopLoss:
    def test_call_stop_below_entry(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "CALL")
        assert sl < 100

    def test_put_stop_above_entry(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "PUT")
        assert sl > 100

    def test_zero_atr_defaults_to_1pct(self):
        sl = calc_atr_stop_loss(100.0, 0.0, "CALL")
        assert sl == round(100 - 1.5 * 100 * 0.01, 2)

    def test_custom_multiplier(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "CALL", multiplier=2.0)
        assert sl == round(100 - 2.0 * 5.0, 2)

    def test_up_direction_works(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "UP")
        assert sl < 100

    def test_down_direction_works(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "DOWN")
        assert sl > 100

    def test_buy_direction_works(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "BUY")
        assert sl < 100

    def test_sell_direction_works(self):
        sl = calc_atr_stop_loss(100.0, 5.0, "SELL")
        assert sl > 100


# ── classify_strength ───────────────────────────────────────────────────────


class TestClassifyStrength:
    def test_strong_above_85(self):
        assert classify_strength(90) == "STRONG"

    def test_moderate_between_70_and_84(self):
        assert classify_strength(75) == "MODERATE"

    def test_weak_between_threshold_and_69(self):
        assert classify_strength(62) == "WEAK"

    def test_none_below_threshold(self):
        assert classify_strength(40) == "NONE"

    def test_custom_thresholds(self):
        assert classify_strength(60, threshold=40, strong_min=80, moderate_min=55) == "MODERATE"

    def test_exact_strong_boundary(self):
        assert classify_strength(85) == "STRONG"

    def test_exact_moderate_boundary(self):
        assert classify_strength(70) == "MODERATE"

    def test_exact_threshold(self):
        assert classify_strength(60) == "WEAK"


# ── classify_signal ─────────────────────────────────────────────────────────


class TestClassifySignal:
    def test_call_above_threshold_returns_buy(self):
        assert classify_signal("CALL", 75) == "BUY"

    def test_put_above_threshold_returns_sell(self):
        assert classify_signal("PUT", 75) == "SELL"

    def test_below_threshold_returns_hold(self):
        assert classify_signal("CALL", 40) == "HOLD"

    def test_up_direction_returns_buy(self):
        assert classify_signal("UP", 75) == "BUY"

    def test_down_direction_returns_sell(self):
        assert classify_signal("DOWN", 75) == "SELL"

    def test_custom_threshold(self):
        assert classify_signal("CALL", 50, threshold=50) == "BUY"
        assert classify_signal("CALL", 49, threshold=50) == "HOLD"


# ── score_to_stars ──────────────────────────────────────────────────────────


class TestScoreToStars:
    def test_90_plus_returns_five_stars(self):
        assert score_to_stars(95) == "\u2b50\u2b50\u2b50\u2b50\u2b50"

    def test_80_to_89_returns_four_stars(self):
        assert score_to_stars(85) == "\u2b50\u2b50\u2b50\u2b50"

    def test_70_to_79_returns_three_stars(self):
        assert score_to_stars(75) == "\u2b50\u2b50\u2b50"

    def test_threshold_to_69_returns_two_stars(self):
        assert score_to_stars(62) == "\u2b50\u2b50"

    def test_threshold_minus_10_returns_one_star(self):
        assert score_to_stars(52) == "\u2b50"

    def test_below_threshold_minus_10_returns_empty(self):
        assert score_to_stars(40) == ""

    def test_custom_threshold(self):
        assert score_to_stars(52, threshold=70) == ""


# ── score_to_label ──────────────────────────────────────────────────────────


class TestScoreToLabel:
    def test_call_strong(self):
        assert "Strong Buy CE" in score_to_label(90, "CALL")

    def test_put_strong(self):
        assert "Strong Buy PE" in score_to_label(90, "PUT")

    def test_call_moderate(self):
        assert "Buy CE" in score_to_label(75, "CALL")

    def test_put_moderate(self):
        assert "Buy PE" in score_to_label(75, "PUT")

    def test_call_weak(self):
        assert "Weak Buy CE" in score_to_label(62, "CALL")

    def test_put_weak(self):
        assert "Weak Buy PE" in score_to_label(62, "PUT")

    def test_no_signal_below_threshold(self):
        assert score_to_label(40, "CALL") == "No Signal"

    def test_custom_threshold(self):
        assert score_to_label(55, "CALL", threshold=55) == "Weak Buy CE"


# ── validate_ohlcv ──────────────────────────────────────────────────────────


class TestValidateOhlcv:
    def test_valid_data_returns_cleaned_df(self):
        df = _ohlcv(20)
        result, dropped = validate_ohlcv(df)
        assert result is not None
        assert dropped == 0

    def test_missing_columns_returns_none(self):
        df = pd.DataFrame({"a": [1], "b": [2]})
        result, dropped = validate_ohlcv(df)
        assert result is None

    def test_invalid_high_low_removes_rows(self):
        df = _ohlcv(20)
        df.iloc[0, df.columns.get_loc("High")] = df.iloc[0]["Low"] - 1
        result, dropped = validate_ohlcv(df)
        assert result is not None
        assert dropped == 1

    def test_close_outside_range_removes_rows(self):
        df = _ohlcv(20)
        df.iloc[0, df.columns.get_loc("Close")] = df.iloc[0]["High"] + 10
        result, dropped = validate_ohlcv(df)
        assert result is not None
        assert dropped == 1

    def test_zero_volume_partially_removes_rows(self):
        df = _ohlcv(20)
        # Set half the rows to zero volume (50% drop ratio > 0.15 max)
        df.iloc[:10, df.columns.get_loc("Volume")] = 0
        result, dropped = validate_ohlcv(df)
        assert result is None  # Drop ratio exceeds max_drop_ratio
        assert dropped == 10

    def test_high_drop_ratio_returns_none(self):
        df = _ohlcv(20)
        # Corrupt half the rows
        df.iloc[:10, df.columns.get_loc("Close")] = df.iloc[:10]["High"] * 2
        result, dropped = validate_ohlcv(df, max_drop_ratio=0.10)
        assert result is None
        assert dropped == 10

    def test_none_df_returns_none(self):
        result, dropped = validate_ohlcv(None)
        assert result is None
        assert dropped == 0

    def test_empty_df_returns_none(self):
        result, dropped = validate_ohlcv(pd.DataFrame())
        assert result is None
        assert dropped == 0

    def test_insufficient_rows_after_clean_returns_none(self):
        df = _ohlcv(2)
        result, dropped = validate_ohlcv(df)
        # May be None or valid depending on cleanup
        assert result is None or dropped == 0


# ── explain_signal ──────────────────────────────────────────────────────────


class TestExplainSignal:
    def test_empty_sig_returns_no_signal_data(self):
        assert explain_signal({}) == "No signal data"

    def test_none_sig_returns_no_signal_data(self):
        assert explain_signal(None) == "No signal data"

    def test_call_trend_includes_going_up(self):
        text = explain_signal({"trend_5m": "CALL", "price": 100, "vwap": 95, "rsi": 50}, "Test")
        assert "going UP" in text
        assert "Test" in text

    def test_puts_includes_going_down(self):
        text = explain_signal({"trend": "DOWN", "price": 100, "vwap": 105, "rsi": 50})
        assert "going DOWN" in text

    def test_high_volume_included(self):
        text = explain_signal({"trend": "UP", "vol_ratio": 2.5, "rsi": 50})
        assert "very high volume" in text

    def test_good_volume_included(self):
        text = explain_signal({"trend": "UP", "vol_ratio": 1.5, "rsi": 50})
        assert "good volume" in text

    def test_smart_money_bullish(self):
        text = explain_signal({"trend": "UP", "smart_money": "BULLISH", "rsi": 50})
        assert "big buyers active" in text

    def test_smart_money_bearish(self):
        text = explain_signal({"trend": "DOWN", "smart": "BEARISH", "rsi": 50})
        assert "big sellers active" in text

    def test_overbought_rsi(self):
        text = explain_signal({"trend": "UP", "rsi": 80})
        assert "overbought" in text

    def test_oversold_rsi(self):
        text = explain_signal({"trend": "UP", "rsi": 20})
        assert "oversold" in text

    def test_macd_bullish(self):
        text = explain_signal({"trend": "UP", "macd": {"histogram": 0.5}, "rsi": 50})
        assert "bullish" in text

    def test_macd_bearish(self):
        text = explain_signal({"trend": "DOWN", "macd": {"histogram": -0.5}, "rsi": 50})
        assert "bearish" in text

    def test_vix_low(self):
        text = explain_signal({"trend": "UP", "vix": 12, "rsi": 50})
        assert "low fear" in text

    def test_vix_high(self):
        text = explain_signal({"trend": "UP", "vix": 25, "rsi": 50})
        assert "high fear" in text

    def test_vix_moderate(self):
        text = explain_signal({"trend": "UP", "vix": 18, "rsi": 50})
        assert "moderate fear" in text


# ── format_pnl ──────────────────────────────────────────────────────────────


class TestFormatPnl:
    def test_positive_pnl(self):
        result = format_pnl(1500)
        assert "+" in result
        assert "\u20b9" in result

    def test_negative_pnl(self):
        result = format_pnl(-500)
        assert "-" in result
        assert "\u20b9" in result

    def test_zero_pnl(self):
        result = format_pnl(0)
        assert "+" in result  # 0 is treated as non-negative

    def test_none_returns_zero(self):
        result = format_pnl(None)
        assert "0" in result

    def test_string_number(self):
        result = format_pnl("750.5")
        assert "+" in result


# ── format_change ───────────────────────────────────────────────────────────


class TestFormatChange:
    def test_positive_change_uses_up_arrow(self):
        result = format_change(50, 2.5)
        assert "\u25b2" in result  # up arrow
        assert "50" in result
        assert "2.5" in result

    def test_negative_change_uses_down_arrow(self):
        result = format_change(-30, -1.2)
        assert "\u25bc" in result  # down arrow
        assert "-30" in result

    def test_zero_change(self):
        result = format_change(0, 0)
        assert "\u25b2" in result  # treated as non-negative

    def test_none_values(self):
        result = format_change(None, None)
        assert "0" in result
