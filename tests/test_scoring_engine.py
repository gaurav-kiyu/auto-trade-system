"""Tests for core/scoring_engine.py — multi-strategy signal score aggregation."""

from __future__ import annotations

from core.scoring_engine import ScoringEngine


def _bullish_features() -> dict:
    return {
        "close": 19500, "high": 19600, "low": 19400,
        "volume": 100000, "rsi": 55,
        "macd": {"histogram": 1.5, "macd": 1.0, "signal": 0.5},
        "adx": 25, "atr": 100, "vwap": 19480,
        "sma_20": 19400, "sma_50": 19200,
        "bb_upper": 19600, "bb_lower": 19200, "bb_mid": 19400,
        "trend_5m": "UP", "timeframe_aligned": True,
        "regime": "TRENDING", "vwap_position": "above",
        "vol_ratio": 1.5, "pcr": 1.1, "smart_money": "BULLISH",
        "price": 19500,
    }


class TestInit:
    def test_initializes_strategies(self) -> None:
        engine = ScoringEngine({})
        assert len(engine.strategies) == 8

    def test_strategy_names(self) -> None:
        engine = ScoringEngine({})
        names = [s.name for s in engine.strategies]
        assert "Trend" in names
        assert "VWAP" in names
        assert "Volume" in names
        assert "ATR" in names
        assert "MACD" in names
        assert "RSI" in names
        assert "SmartMoney" in names
        assert "MeanReversion" in names


class TestScore:
    def test_returns_required_keys(self) -> None:
        engine = ScoringEngine({})
        features = _bullish_features()
        result = engine.score(features, "CALL")
        assert "total_score" in result
        assert "direction" in result
        assert "components" in result
        assert "reasons" in result

    def test_score_clamped_0_100(self) -> None:
        engine = ScoringEngine({})
        result = engine.score(_bullish_features(), "CALL")
        assert 0 <= result["total_score"] <= 100

    def test_components_have_structure(self) -> None:
        engine = ScoringEngine({})
        result = engine.score(_bullish_features(), "CALL")
        for comp in result["components"]:
            assert "name" in comp
            assert "score" in comp
        for reason in result["reasons"]:
            assert "name" in reason
            assert "status" in reason
            assert "msg" in reason

    def test_direction_preserved(self) -> None:
        engine = ScoringEngine({})
        assert engine.score(_bullish_features(), "CALL")["direction"] == "CALL"
        assert engine.score(_bullish_features(), "PUT")["direction"] == "PUT"

    def test_different_features_produce_different_scores(self) -> None:
        engine = ScoringEngine({})

        bullish = _bullish_features()
        bearish = {
            "close": 19000, "high": 19200, "low": 18900,
            "volume": 50000, "rsi": 30,
            "macd": {"histogram": -2.0, "macd": -1.0, "signal": 1.0},
            "adx": 15, "atr": 150, "vwap": 19500,
            "sma_20": 19600, "sma_50": 19700,
            "bb_upper": 20000, "bb_lower": 19200, "bb_mid": 19600,
            "trend_5m": "DOWN", "timeframe_aligned": False,
            "regime": "CHOPPY", "vwap_position": "below",
            "vol_ratio": 0.5, "pcr": 0.7, "smart_money": "BEARISH",
            "price": 19000,
        }

        bullish_score = engine.score(bullish, "CALL")["total_score"]
        bearish_score = engine.score(bearish, "CALL")["total_score"]
        assert bullish_score != bearish_score
