"""
Tests for core/services/signal_orchestrator.py - SignalOrchestrator.

Covers:
  - SignalIntent dataclass defaults
  - SignalOrchestrator initialization with config
  - process_market_data (signal generated, ML validates, ML veto, returns None)
  - _extract_ml_features mapping
  - Singleton init_signal_orchestrator
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from core.services.signal_orchestrator import (
    SignalIntent,
    SignalOrchestrator,
    init_signal_orchestrator,
)

# ═══════════════════════════════════════════════════════════════════════
#  SignalIntent
# ═══════════════════════════════════════════════════════════════════════


class TestSignalIntent:
    def test_required_fields(self):
        intent = SignalIntent(
            symbol="NIFTY", direction="CALL", score=75,
            confidence=0.85, price=23500.0, rationale="Strong signal",
            regime="TREND",
        )
        assert intent.symbol == "NIFTY"
        assert intent.direction == "CALL"
        assert intent.score == 75
        assert intent.confidence == 0.85
        assert intent.price == 23500.0
        assert intent.rationale == "Strong signal"
        assert intent.regime == "TREND"

    def test_timestamp_auto_generated(self):
        intent = SignalIntent(
            symbol="NIFTY", direction="CALL", score=75,
            confidence=0.85, price=23500.0, rationale="Test",
            regime="NEUTRAL",
        )
        assert intent.timestamp is not None
        assert len(intent.timestamp) > 0


# ═══════════════════════════════════════════════════════════════════════
#  SignalOrchestrator initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_stores_config(self):
        cfg = {"AI_THRESHOLD": 50, "some_key": "value"}
        orch = SignalOrchestrator(cfg)
        assert orch.config == cfg

    def test_initializes_signal_cache(self):
        orch = SignalOrchestrator({"key": "val"})
        assert orch._signal_cache == {}


# ═══════════════════════════════════════════════════════════════════════
#  process_market_data
# ═══════════════════════════════════════════════════════════════════════


class TestProcessMarketData:
    @pytest.fixture
    def orch(self):
        return SignalOrchestrator({"AI_THRESHOLD": 60})

    @staticmethod
    def _make_mock_df():
        """Create a minimal mock DataFrame that passes evaluate_index_signal_partial checks."""
        import numpy as np
        idx = pd.date_range("2026-06-30 09:15", periods=60, freq="1min")
        df = pd.DataFrame({
            "Open": np.random.uniform(23500, 23600, 60),
            "High": np.random.uniform(23600, 23700, 60),
            "Low": np.random.uniform(23400, 23500, 60),
            "Close": np.random.uniform(23500, 23600, 60),
            "Volume": np.random.randint(10000, 50000, 60),
        }, index=idx)
        return df

    def test_signal_hold_returns_none(self, orch: SignalOrchestrator):
        """When evaluate_index_signal_partial returns None, process returns None."""
        df = self._make_mock_df()
        with patch(
            "core.pure_index_signal.evaluate_index_signal_partial",
            return_value=(None, "tf_mismatch"),
        ):
            result = orch.process_market_data(
                "NIFTY",
                {"df1m": df, "df5m": df, "df15m": df},
                {"asset_type": "index", "iv": 15.0, "vix": 12.0},
            )
            assert result is None

    def test_signal_none_returns_none(self, orch: SignalOrchestrator):
        """When evaluate_index_signal_partial raises, process returns None gracefully."""
        df = self._make_mock_df()
        with patch(
            "core.pure_index_signal.evaluate_index_signal_partial",
            side_effect=Exception("Simulated partial failure"),
        ):
            result = orch.process_market_data(
                "NIFTY",
                {"df1m": df, "df5m": df, "df15m": df},
                {"asset_type": "index", "iv": 15.0, "vix": 12.0},
            )
            assert result is None

    def test_ml_veto_blocks_signal(self, orch: SignalOrchestrator):
        """When ML probability < 0.3, signal is vetoed."""
        df = self._make_mock_df()
        mock_partial = {
            "score": 75, "direction": "CALL", "price": 23500.0,
            "mkt_regime": "TREND",
        }
        with patch(
            "core.pure_index_signal.evaluate_index_signal_partial",
            return_value=(mock_partial, ""),
        ):
            with patch("core.services.signal_orchestrator.ml_engine") as mock_ml:
                mock_ml.predict.return_value.win_probability = 0.2
                mock_ml.predict.return_value.confidence_score = 0.5
                result = orch.process_market_data(
                    "NIFTY",
                    {"df1m": df, "df5m": df, "df15m": df},
                    {"asset_type": "index", "iv": 15.0, "vix": 12.0},
                )
                assert result is None

    def test_successful_signal_returns_intent(self, orch: SignalOrchestrator):
        """When signal is valid and ML probability is sufficient, returns SignalIntent."""
        df = self._make_mock_df()
        mock_partial = {
            "score": 75, "direction": "CALL", "price": 23500.0,
            "mkt_regime": "TREND",
        }
        with patch(
            "core.pure_index_signal.evaluate_index_signal_partial",
            return_value=(mock_partial, ""),
        ):
            with patch("core.services.signal_orchestrator.ml_engine") as mock_ml:
                mock_ml.predict.return_value.win_probability = 0.85
                mock_ml.predict.return_value.confidence_score = 0.75
                result = orch.process_market_data(
                    "NIFTY",
                    {"df1m": df, "df5m": df, "df15m": df},
                    {"asset_type": "index", "iv": 15.0, "vix": 12.0},
                )
                assert isinstance(result, SignalIntent)
                assert result.symbol == "NIFTY"
                assert result.direction == "CALL"
                assert result.score == 75
                assert result.confidence == 0.75
                assert result.regime == "TREND"

    def test_passes_additional_info(self, orch: SignalOrchestrator):
        """Additional info (oi_data, iv, vix) is passed through."""
        df = self._make_mock_df()
        oi_data = {"pcr": 0.8, "smart_money": "BEARISH", "support": 23400.0, "resistance": 23700.0}
        mock_partial = {
            "score": 70, "direction": "PUT", "price": 23500.0,
            "mkt_regime": "RANGE",
        }
        with patch(
            "core.pure_index_signal.evaluate_index_signal_partial",
            return_value=(mock_partial, ""),
        ):
            with patch("core.services.signal_orchestrator.ml_engine") as mock_ml:
                mock_ml.predict.return_value.win_probability = 0.9
                mock_ml.predict.return_value.confidence_score = 0.8
                result = orch.process_market_data(
                    "BANKNIFTY",
                    {"df1m": df, "df5m": df, "df15m": df},
                    {
                        "asset_type": "index",
                        "oi_data": oi_data,
                        "iv": 20.0,
                        "vix": 15.0,
                        "sector": "BANKING",
                        "category": "INDEX",
                    },
                )
                assert isinstance(result, SignalIntent)
                assert result.symbol == "BANKNIFTY"
                assert result.direction == "PUT"
                assert result.score == 70
                assert result.confidence == 0.8
                assert result.regime == "RANGE"


# ═══════════════════════════════════════════════════════════════════════
#  _extract_ml_features
# ═══════════════════════════════════════════════════════════════════════


class TestExtractMlFeatures:
    def test_maps_signal_to_feature_vector(self):
        orch = SignalOrchestrator({})
        features = orch._extract_ml_features(
            {
                "score": 80, "confidence": 0.9, "direction": "CALL",
                "strength": "STRONG", "iv": 15.0, "vix": 12.0,
                "pcr": 1.2, "regime": "TREND",
            },
            {},
        )
        assert features["score"] == 80
        assert features["confidence"] == 0.9
        assert features["direction_call"] == 1
        assert features["is_strong"] == 1
        assert features["is_moderate"] == 0
        assert features["is_weak"] == 0
        assert features["iv_rank"] == 15.0
        assert features["vix"] == 12.0
        assert features["pcr"] == 1.2
        assert features["regime_code"] == 1  # TREND

    def test_default_values_for_missing_keys(self):
        orch = SignalOrchestrator({})
        features = orch._extract_ml_features({}, {})
        assert features["score"] == 0
        assert features["direction_call"] == 0  # No direction means PUT/SELL
        assert features["is_strong"] == 0
        assert features["regime_code"] == 0  # Not TREND


# ═══════════════════════════════════════════════════════════════════════
#  Singleton init_signal_orchestrator
# ═══════════════════════════════════════════════════════════════════════


class TestInitSignalOrchestrator:
    def teardown_method(self):
        """Reset singleton after each test."""
        import core.services.signal_orchestrator as so
        so.signal_orchestrator = None

    def test_initializes_singleton(self):
        init_signal_orchestrator({"AI_THRESHOLD": 60})
        import core.services.signal_orchestrator as so
        assert so.signal_orchestrator is not None
        assert isinstance(so.signal_orchestrator, SignalOrchestrator)

    def test_called_twice_returns_same_instance(self):
        init_signal_orchestrator({"key": "first"})
        import core.services.signal_orchestrator as so
        first = so.signal_orchestrator
        init_signal_orchestrator({"key": "second"})
        assert so.signal_orchestrator is first  # Same instance, not re-created
