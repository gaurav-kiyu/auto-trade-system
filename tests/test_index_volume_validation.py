"""Regression tests for index zero-volume validation (v2.59.4).

Verifies the surgical fix allowing cash/index benchmarks (NIFTY, BANKNIFTY,
FINNIFTY) to legitimately contain Volume == 0 while preserving strict
positive-volume validation for traded equities.

Covers:
- TEST A: INDEX ZERO VOLUME ACCEPTED
- TEST B: EQUITY ZERO VOLUME REJECTED
- TEST C: NEGATIVE VOLUME REJECTED
- TEST D: INVALID OHLC REMAINS REJECTED
- TEST E: INDEX REACHES SIGNAL EVALUATION
- TEST F: NO REGRESSION FOR EQUITIES
"""

from __future__ import annotations

from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import pytest

from core.signal_utils import validate_ohlcv
from index_app.domains.signal.evaluator import SignalEvaluator


def _make_frame(n: int = 50, zero_volume: bool = False, base_price: float = 23000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data with realistic datetime index."""
    now = datetime(2026, 9, 16, 11, 30, 0)
    times = [now - timedelta(minutes=n - i) for i in range(n)]
    prices = [base_price + i * 2.0 for i in range(n)]
    
    df = pd.DataFrame({
        "Open": [p - 1.0 for p in prices],
        "High": [p + 3.0 for p in prices],
        "Low": [p - 2.0 for p in prices],
        "Close": prices,
        "Volume": [0 if zero_volume else 1000 + i * 10 for i in range(n)],
    }, index=pd.DatetimeIndex(times))
    return df


class TestIndexVolumeValidation:
    """Tests A through F required by OPB v2.59.4 index validation specification."""

    def test_a_index_zero_volume_accepted(self):
        """TEST A: A valid NIFTY/BANKNIFTY/FINNIFTY frame with Volume == 0 must NOT fail."""
        for symbol in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            df = _make_frame(n=50, zero_volume=True)
            assert (df["Volume"] == 0).all()
            
            clean_df, dropped = validate_ohlcv(df, allow_zero_volume=True)
            assert clean_df is not None, f"Expected clean_df for {symbol} with zero volume"
            assert dropped == 0, f"Expected 0 dropped rows for {symbol}"
            assert len(clean_df) == 50

    def test_b_equity_zero_volume_rejected(self):
        """TEST B: A traded equity frame with Volume == 0 must remain invalid/rejected."""
        df_equity = _make_frame(n=50, zero_volume=True)
        assert (df_equity["Volume"] == 0).all()
        
        # Default allow_zero_volume=False (equity behavior)
        clean_df, dropped = validate_ohlcv(df_equity, allow_zero_volume=False)
        assert clean_df is None, "Traded equity with zero volume must be rejected"
        assert dropped == 50, "All zero-volume equity rows must be dropped"

    def test_c_negative_volume_rejected(self):
        """TEST C: Negative volume remains invalid everywhere (index and equity)."""
        df_neg_index = _make_frame(n=50, zero_volume=True)
        df_neg_index.iloc[5, df_neg_index.columns.get_loc("Volume")] = -50
        
        # In index mode (allow_zero_volume=True), negative volume is still dropped
        clean_df, dropped = validate_ohlcv(df_neg_index, allow_zero_volume=True)
        assert clean_df is not None
        assert dropped == 1
        assert len(clean_df) == 49

        # In equity mode (allow_zero_volume=False), negative volume is also dropped
        df_neg_equity = _make_frame(n=50, zero_volume=False)
        df_neg_equity.iloc[5, df_neg_equity.columns.get_loc("Volume")] = -50
        clean_df_eq, dropped_eq = validate_ohlcv(df_neg_equity, allow_zero_volume=False)
        assert clean_df_eq is not None
        assert dropped_eq == 1
        assert len(clean_df_eq) == 49

    def test_d_invalid_ohlc_remains_rejected(self):
        """TEST D: Malformed/invalid OHLC data must still fail validation even with allow_zero_volume=True."""
        # 1. High < Low
        df_bad_hl = _make_frame(n=50, zero_volume=True)
        df_bad_hl.iloc[0, df_bad_hl.columns.get_loc("High")] = df_bad_hl.iloc[0]["Low"] - 5.0
        clean_df, dropped = validate_ohlcv(df_bad_hl, allow_zero_volume=True)
        assert clean_df is not None
        assert dropped == 1

        # 2. Close > High
        df_bad_close = _make_frame(n=50, zero_volume=True)
        df_bad_close.iloc[0, df_bad_close.columns.get_loc("Close")] = df_bad_close.iloc[0]["High"] + 10.0
        clean_df, dropped = validate_ohlcv(df_bad_close, allow_zero_volume=True)
        assert clean_df is not None
        assert dropped == 1

        # 3. Excessive corruption (>15% drop) returns None
        df_corrupt = _make_frame(n=50, zero_volume=True)
        for i in range(10):  # 20% of rows corrupt > 15% max_drop_ratio
            df_corrupt.iloc[i, df_corrupt.columns.get_loc("High")] = df_corrupt.iloc[i]["Low"] - 1.0
        clean_df, dropped = validate_ohlcv(df_corrupt, allow_zero_volume=True)
        assert clean_df is None
        assert dropped == 10

    def test_e_index_reaches_signal_evaluation(self):
        """TEST E: Using live-shaped index frames, zero-volume condition does NOT cause df1m_invalid_ohlcv."""
        cfg = {"AI_THRESHOLD": 60, "EXECUTION_MODE": "PAPER"}
        evaluator = SignalEvaluator(cfg=cfg)
        
        # Construct 1m, 5m, 15m frames with zero volume (matching live Yahoo Finance index data)
        df1m = _make_frame(n=60, zero_volume=True, base_price=23200.0)
        df5m = _make_frame(n=25, zero_volume=True, base_price=23200.0)
        df15m = _make_frame(n=20, zero_volume=True, base_price=23200.0)
        
        frames = {"df1m": df1m, "df5m": df5m, "df15m": df15m}
        
        for index_name in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            result, reason = evaluator.evaluate(name=index_name, frames=frames, vix=13.5)
            # The test must demonstrate that validation NO LONGER blocks the index with df1m_invalid_ohlcv
            assert reason != "df1m_invalid_ohlcv", f"{index_name} failed with df1m_invalid_ohlcv"
            assert reason != "df5m_invalid_ohlcv", f"{index_name} failed with df5m_invalid_ohlcv"
            assert reason != "df15m_invalid_ohlcv", f"{index_name} failed with df15m_invalid_ohlcv"

    def test_f_no_regression_for_equities(self):
        """TEST F: Existing equity validation behavior remains strictly unchanged."""
        cfg = {"AI_THRESHOLD": 60, "EXECUTION_MODE": "PAPER"}
        evaluator = SignalEvaluator(cfg=cfg)
        
        # Traded equity with zero volume must fail closed with invalid_ohlcv
        df1m_zero = _make_frame(n=60, zero_volume=True, base_price=2500.0)
        df5m_zero = _make_frame(n=25, zero_volume=True, base_price=2500.0)
        df15m_zero = _make_frame(n=20, zero_volume=True, base_price=2500.0)
        
        frames_zero = {"df1m": df1m_zero, "df5m": df5m_zero, "df15m": df15m_zero}
        result_eq, reason_eq = evaluator.evaluate(name="RELIANCE", frames=frames_zero, vix=13.5)
        assert result_eq is None
        assert reason_eq == "df1m_invalid_ohlcv", f"Equity with zero volume must fail with df1m_invalid_ohlcv, got: {reason_eq}"
        
        # Traded equity with positive volume must NOT fail with invalid_ohlcv
        df1m_pos = _make_frame(n=60, zero_volume=False, base_price=2500.0)
        df5m_pos = _make_frame(n=25, zero_volume=False, base_price=2500.0)
        df15m_pos = _make_frame(n=20, zero_volume=False, base_price=2500.0)
        
        frames_pos = {"df1m": df1m_pos, "df5m": df5m_pos, "df15m": df15m_pos}
        result_pos, reason_pos = evaluator.evaluate(name="RELIANCE", frames=frames_pos, vix=13.5)
        assert reason_pos != "df1m_invalid_ohlcv"
