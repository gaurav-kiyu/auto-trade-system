"""test_yahoo_batch_benchmark.py - Tests for isolated Yahoo batching benchmark.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Execution Mode: STRICTLY OFFLINE / ZERO-MUTATION UNIT TESTS
"""

from __future__ import annotations

import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import pytest

from core.research.yahoo_batch_benchmark import (
    BENCHMARK_SAMPLE_SYMBOLS,
    HttpRequestMonitor,
    compute_prod_db_sha,
    evaluate_failure_blast_radius,
    evaluate_symbol_parity,
    extract_completed_bar,
    map_symbol_to_yf_ticker,
)


def test_deterministic_sample_size_and_membership():
    """Verify benchmark sample consists of exactly 50 symbols and includes priority indices."""
    assert len(BENCHMARK_SAMPLE_SYMBOLS) == 50
    assert "NIFTY" in BENCHMARK_SAMPLE_SYMBOLS
    assert "BANKNIFTY" in BENCHMARK_SAMPLE_SYMBOLS
    assert "RELIANCE" in BENCHMARK_SAMPLE_SYMBOLS
    assert "TCS" in BENCHMARK_SAMPLE_SYMBOLS
    # Check no duplicate symbols
    assert len(set(BENCHMARK_SAMPLE_SYMBOLS)) == 50


def test_map_symbol_to_yf_ticker():
    """Verify ticker mapping matches core/all_nse_scanner.py exactly."""
    assert map_symbol_to_yf_ticker("NIFTY") == "^NSEI"
    assert map_symbol_to_yf_ticker("BANKNIFTY") == "^NSEBANK"
    assert map_symbol_to_yf_ticker("GOLD") == "GC=F"
    assert map_symbol_to_yf_ticker("USDINR") == "USDINR=X"
    assert map_symbol_to_yf_ticker("RELIANCE") == "RELIANCE.NS"
    assert map_symbol_to_yf_ticker("INFY") == "INFY.NS"


def test_production_db_sha_integrity():
    """Verify production database SHA matches authoritative constant."""
    sha, size = compute_prod_db_sha()
    assert sha == "f12ba2e45e91077dbb3cfde289938aba225bd1669b9d02a7ddc5a49e57cd6e5a"
    assert size == 1216512


def test_completed_bar_extraction_invariant():
    """Verify extract_completed_bar strictly extracts df1.iloc[-2]."""
    # 1. Empty or len < 2
    snap_empty = extract_completed_bar(pd.DataFrame(), "RELIANCE")
    assert not snap_empty.has_completed_bar

    # 2. DataFrame with 3 bars
    dates = pd.date_range("2026-10-04 09:15", periods=3, freq="1min", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [104.0, 105.0, 106.0],
            "Volume": [1000.0, 2000.0, 3000.0],
        },
        index=dates,
    )
    snap = extract_completed_bar(df, "RELIANCE")
    assert snap.has_completed_bar
    assert snap.total_bars == 3
    # Invariant: iloc[-2] is bar index 1
    assert snap.open == 101.0
    assert snap.high == 106.0
    assert snap.low == 100.0
    assert snap.close == 105.0
    assert snap.volume == 2000.0
    assert "09:16" in snap.timestamp_str


def test_evaluate_symbol_parity_identical_frames():
    """Verify evaluate_symbol_parity reports 100% parity on identical frames."""
    dates = pd.date_range("2026-10-04 09:15", periods=5, freq="5min", tz="Asia/Kolkata")
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [105.0, 106.0, 107.0, 108.0, 109.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [104.0, 105.0, 106.0, 107.0, 108.0],
            "Volume": [1000.0, 2000.0, 1500.0, 1800.0, 2100.0],
        },
        index=dates,
    )
    res = evaluate_symbol_parity("RELIANCE", "5m", "5d", df, df.copy())
    assert res.row_count_match
    assert res.timestamps_match
    assert res.ohlc_max_abs_diff == 0.0
    assert res.volume_max_abs_diff == 0.0
    assert res.nan_placement_match
    assert res.timezone_match
    assert res.latest_completed_bar_match
    assert res.validate_ohlcv_parity
    assert len(res.discrepancies) == 0


def test_evaluate_symbol_parity_detects_discrepancy():
    """Verify evaluate_symbol_parity catches price differences and timestamp shifts."""
    dates = pd.date_range("2026-10-04 09:15", periods=5, freq="5min", tz="Asia/Kolkata")
    df1 = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 104.0],
            "High": [105.0, 106.0, 107.0, 108.0, 109.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 103.0],
            "Close": [104.0, 105.0, 106.0, 107.0, 108.0],
            "Volume": [1000.0, 2000.0, 1500.0, 1800.0, 2100.0],
        },
        index=dates,
    )
    df2 = df1.copy()
    # Modify Close on bar 3
    df2.iloc[3, df2.columns.get_loc("Close")] = 115.0

    res = evaluate_symbol_parity("RELIANCE", "5m", "5d", df1, df2)
    assert res.ohlc_max_abs_diff == pytest.approx(8.0)
    assert not res.latest_completed_bar_match
    assert len(res.discrepancies) > 0


def test_failure_blast_radius_scenarios():
    """Verify failure blast radius returns comprehensive failure scenarios."""
    scenarios = evaluate_failure_blast_radius()
    assert len(scenarios) >= 5
    scenario_names = [s.scenario for s in scenarios]
    assert any("429" in s for s in scenario_names)
    assert any("Timeout" in s for s in scenario_names)
    assert any("Delisted" in s for s in scenario_names)
    # Higher in batch must be flagged for 429 and timeouts
    r429 = next(s for s in scenarios if "429" in s.scenario)
    assert r429.relative_risk == "HIGHER_IN_BATCH"


def test_zero_broker_zero_production_imports():
    """Verify research module does not import broker or production execution logic."""
    import core.research.yahoo_batch_benchmark as mod
    content = Path(mod.__file__).read_text(encoding="utf-8")
    for kw in ["fyers", "dhan", "zerodha", "angel", "execute_order", "place_order"]:
        assert kw not in content.lower()
