"""Tests for core/sentiment_engine.py — simulated news sentiment engine."""

from __future__ import annotations

from core.sentiment_engine import SentimentEngine


class TestInit:
    def test_default_api_key(self) -> None:
        engine = SentimentEngine()
        assert engine.api_key == ""

    def test_custom_api_key(self) -> None:
        engine = SentimentEngine(api_key="test123")
        assert engine.api_key == "test123"


class TestGetSentimentNoApiKey:
    def test_returns_neutral_when_no_key(self) -> None:
        engine = SentimentEngine(api_key="")
        result = engine.get_sentiment("NIFTY")
        assert result["score"] == 0.0
        assert result["is_panic"] is False
        assert "disabled" in result["reason"].lower()

    def test_returns_neutral_structure_when_no_key(self) -> None:
        engine = SentimentEngine(api_key="")
        result = engine.get_sentiment("BANKNIFTY")
        assert "score" in result
        assert "is_panic" in result
        assert "reason" in result


class TestGetSentimentWithApiKey:
    def test_rss_failure_returns_fallback(self) -> None:
        engine = SentimentEngine(api_key="some_key")
        # Can't test real RSS, but verify the fallback path exists
        result = engine.get_sentiment("FAKE_SYMBOL_XYZ")
        # Will try RSS and fail → returns fallback
        assert "score" in result
        assert "is_panic" in result


class TestResultStructure:
    def test_structure_has_required_keys(self) -> None:
        engine = SentimentEngine(api_key="")
        result = engine.get_sentiment("NIFTY")
        assert "score" in result
        assert "is_panic" in result
        assert "reason" in result

    def test_score_is_float(self) -> None:
        engine = SentimentEngine()
        result = engine.get_sentiment("NIFTY")
        assert isinstance(result["score"], float)

    def test_is_panic_is_bool(self) -> None:
        engine = SentimentEngine()
        result = engine.get_sentiment("NIFTY")
        assert isinstance(result["is_panic"], bool)
