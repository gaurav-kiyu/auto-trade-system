"""Tests for core.order_flow_analyzer - volume-price relationship analysis."""

from __future__ import annotations

import pandas as pd
from core.order_flow_analyzer import OrderFlowAnalyzer


def _make_df(close_values: list[float], volume_values: list[float]) -> pd.DataFrame:
    """Create a minimal OHLCV DataFrame from close and volume arrays."""
    return pd.DataFrame({
        "Open": close_values,
        "High": [c * 1.01 for c in close_values],
        "Low": [c * 0.99 for c in close_values],
        "Close": close_values,
        "Volume": volume_values,
    })


class TestOrderFlowAnalyzer:
    """Tests for OrderFlowAnalyzer - institutional absorption and exhaustion detection."""

    def setup_method(self) -> None:
        self.analyzer = OrderFlowAnalyzer({})

    def test_insufficient_data_returns_ok(self) -> None:
        df = _make_df([100.0] * 5, [1000] * 5)
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "OK"
        assert result.is_blocked is False

    def test_normal_trend_returns_ok(self) -> None:
        """Normal uptrend with healthy volume should pass."""
        closes = [100.0 + i * 0.5 for i in range(20)]
        volumes = [1000 + i * 10 for i in range(20)]
        df = _make_df(closes, volumes)
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "OK"
        assert result.is_blocked is False
        assert result.confidence == 1.0

    def test_institutional_absorption_detected(self) -> None:
        """High volume + stagnant price = absorption."""
        closes = [100.0] * 20  # No price movement
        volumes = [1000] * 17 + [5000, 5200, 5100]  # Volume spike last 3
        df = _make_df(closes, volumes)
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "ABSORPTION"
        assert result.is_blocked is True
        assert result.confidence >= 0.8

    def test_absorption_not_triggered_without_volume_spike(self) -> None:
        """Stable price + stable volume should NOT trigger absorption."""
        closes = [100.0] * 20
        volumes = [1000] * 20  # No spike
        df = _make_df(closes, volumes)
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "OK"

    def test_bull_exhaustion_detected(self) -> None:
        """Price rising on declining volume = bull trap."""
        closes = [100.0 + i * 0.3 for i in range(20)]  # Rising price
        volumes = [2000 - i * 50 for i in range(20)]  # Continuously declining volume
        df = _make_df(closes, volumes)
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "EXHAUSTION"
        assert result.is_blocked is True

    def test_bear_exhaustion_detected(self) -> None:
        """Price falling on declining volume = bear trap."""
        closes = [100.0 - i * 0.3 for i in range(20)]  # Falling price
        volumes = [2000 - i * 50 for i in range(20)]  # Continuously declining volume
        df = _make_df(closes, volumes)
        result = self.analyzer.analyze("NIFTY", "PUT", df)
        assert result.status == "EXHAUSTION"
        assert result.is_blocked is True

    def test_exhaustion_not_triggered_for_opposite_direction(self) -> None:
        """Bull exhaustion should only trigger for CALL direction."""
        closes = [100.0 + i * 0.3 for i in range(20)]
        volumes = [2000, 1800, 1600, 1400, 1200] + [1000] * 15
        df = _make_df(closes, volumes)
        # PUT with rising price should NOT trigger exhaustion
        result = self.analyzer.analyze("NIFTY", "PUT", df)
        assert result.status == "OK"

    def test_custom_config_thresholds(self) -> None:
        """Custom config should override defaults."""
        analyzer = OrderFlowAnalyzer({
            "order_flow_vol_spike_mult": 1.5,
            "order_flow_stagnation_pct": 0.005,
        })
        closes = [100.0] * 20
        volumes = [1000] * 17 + [2000, 2100, 1900]  # ~2x spike with lower threshold
        df = _make_df(closes, volumes)
        result = analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "ABSORPTION"

    def test_none_dataframe_returns_ok(self) -> None:
        result = self.analyzer.analyze("NIFTY", "CALL", None)
        assert result.status == "OK"
        assert result.is_blocked is False

    def test_very_small_dataframe_returns_ok(self) -> None:
        df = _make_df([100.0], [1000])
        result = self.analyzer.analyze("NIFTY", "CALL", df)
        assert result.status == "OK"
        assert result.is_blocked is False
