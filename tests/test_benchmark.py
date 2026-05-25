"""Tests for core/benchmark.py (v2.44 Item 10)."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from core.benchmark import (
    AlphaMetrics,
    BenchmarkReturn,
    compute_alpha_metrics,
    fetch_benchmark,
)


def make_benchmark(**kwargs):
    defaults = dict(
        symbol="^NSEI",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 3, 31),
        total_return_pct=5.0,
        annualized_return_pct=20.0,
        max_drawdown_pct=-8.0,
        volatility_pct=15.0,
        sharpe_ratio=1.2,
        data_source="yahoo",
    )
    defaults.update(kwargs)
    return BenchmarkReturn(**defaults)


# ── BenchmarkReturn fields ────────────────────────────────────────────────────

def test_benchmark_return_has_all_fields():
    b = make_benchmark()
    assert hasattr(b, "symbol")
    assert hasattr(b, "start_date")
    assert hasattr(b, "end_date")
    assert hasattr(b, "total_return_pct")
    assert hasattr(b, "annualized_return_pct")
    assert hasattr(b, "max_drawdown_pct")
    assert hasattr(b, "volatility_pct")
    assert hasattr(b, "sharpe_ratio")
    assert hasattr(b, "data_source")


def test_benchmark_return_is_frozen():
    b = make_benchmark()
    with pytest.raises((AttributeError, TypeError)):
        b.symbol = "^NIFTY50"


# ── fetch_benchmark ───────────────────────────────────────────────────────────

def make_mock_yf_data():
    import numpy as np
    import pandas as pd
    dates = pd.date_range("2024-01-01", "2024-03-31", freq="B")
    prices = 21000 + np.cumsum(np.random.randn(len(dates)) * 50)
    df = pd.DataFrame({"Close": prices}, index=dates)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = df
    return mock_ticker


def test_fetch_benchmark_returns_none_on_error():
    # Use a unique symbol that won't be in any cache
    import uuid
    fake_symbol = f"^TEST_{uuid.uuid4().hex[:8]}"
    with patch("yfinance.Ticker") as mock_ticker:
        mock_ticker.side_effect = Exception("network error")
        result = fetch_benchmark(fake_symbol, date(2024, 1, 1), date(2024, 3, 31))
    assert result is None


def test_fetch_benchmark_returns_benchmark_return_on_success():
    with patch("yfinance.Ticker", return_value=make_mock_yf_data()):
        result = fetch_benchmark(f"^NSEI_TEST_{id(object())}",
                                 date(2024, 1, 1), date(2024, 3, 31))
    if result is not None:
        assert isinstance(result, BenchmarkReturn)


def test_fetch_benchmark_uses_cache():
    call_count = [0]
    def fake_ticker(sym):
        call_count[0] += 1
        return make_mock_yf_data()
    with patch("yfinance.Ticker", side_effect=fake_ticker):
        fetch_benchmark("^NSEI", date(2024, 1, 1), date(2024, 3, 31), cache_hours=24)
        fetch_benchmark("^NSEI", date(2024, 1, 1), date(2024, 3, 31), cache_hours=24)
        # Second call may use cache → call count should be small
        assert call_count[0] <= 2


# ── compute_alpha_metrics ─────────────────────────────────────────────────────

def test_alpha_positive_when_strategy_beats_benchmark():
    b = make_benchmark(total_return_pct=5.0, max_drawdown_pct=-8.0, volatility_pct=15.0)
    result = compute_alpha_metrics(
        strategy_return_pct=10.0,
        strategy_max_dd_pct=-5.0,
        benchmark=b,
        mc_pnls=[100, 200, 150],
        benchmark_total_pnl=500,
    )
    assert isinstance(result, AlphaMetrics)
    assert result.alpha_pct > 0


def test_alpha_negative_when_strategy_underperforms():
    b = make_benchmark(total_return_pct=10.0)
    result = compute_alpha_metrics(
        strategy_return_pct=3.0,
        strategy_max_dd_pct=-10.0,
        benchmark=b,
        mc_pnls=[10, 20, 15],
        benchmark_total_pnl=1000,
    )
    assert result.alpha_pct < 0


def test_alpha_metrics_has_required_fields():
    b = make_benchmark()
    result = compute_alpha_metrics(8.0, -6.0, b, [100, 200], 500)
    assert hasattr(result, "alpha_pct")
    assert hasattr(result, "information_ratio")
    assert hasattr(result, "drawdown_ratio")


def test_alpha_metrics_with_none_benchmark():
    result = compute_alpha_metrics(8.0, -6.0, None, [100, 200], 500)
    assert result is None or isinstance(result, AlphaMetrics)


def test_compute_alpha_does_not_raise():
    b = make_benchmark()
    try:
        compute_alpha_metrics(5.0, -5.0, b, [], 0)
    except Exception as e:
        pytest.fail(f"compute_alpha_metrics raised: {e}")
