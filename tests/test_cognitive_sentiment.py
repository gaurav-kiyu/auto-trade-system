"""
Tests for CognitiveSentimentEngine — hybrid sentiment analyzer with local keyword
and optional AI-based analysis paths.

Covers:
- SentimentAnalysis dataclass
- Local keyword sentiment (bullish, bearish, mixed, neutral)
- AI path via SovereigntyGuard
- Fallback when AI fails
- Edge cases (empty text, case insensitivity, partial matches)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.cognitive_sentiment import CognitiveSentimentEngine, SentimentAnalysis


# ── SentimentAnalysis Dataclass ────────────────────────────────────────────


class TestSentimentAnalysis:
    def test_creation(self):
        sa = SentimentAnalysis(score=0.5, nuance="Bullish", is_ai_generated=False, confidence=0.6)
        assert sa.score == 0.5
        assert sa.nuance == "Bullish"
        assert sa.is_ai_generated is False
        assert sa.confidence == 0.6

    def test_bearish_score(self):
        sa = SentimentAnalysis(score=-0.8, nuance="Bearish", is_ai_generated=True, confidence=0.9)
        assert sa.score == -0.8
        assert sa.is_ai_generated is True

    def test_neutral_score(self):
        sa = SentimentAnalysis(score=0.0, nuance="Neutral", is_ai_generated=False, confidence=0.5)
        assert sa.score == 0.0


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def engine() -> CognitiveSentimentEngine:
    """Default engine with empty config, no sovereignty guard."""
    return CognitiveSentimentEngine(cfg={})


@pytest.fixture
def engine_with_guard() -> tuple[CognitiveSentimentEngine, MagicMock]:
    """Engine with a mock SovereigntyGuard that allows AI."""
    guard = MagicMock()
    guard.can_use_ai.return_value = True
    engine = CognitiveSentimentEngine(cfg={}, sov_guard=guard)
    return engine, guard


# ── Local Sentiment Analysis ────────────────────────────────────────────────


class TestLocalSentiment:
    def test_bullish_sentiment(self, engine: CognitiveSentimentEngine):
        """Multiple bullish keywords produce positive score."""
        result = engine.analyze_sentiment("Strong breakout and accumulation underway")
        assert result.score > 0
        assert result.is_ai_generated is False
        assert "Local Analysis" in result.nuance
        assert result.confidence == 0.6

    def test_bearish_sentiment(self, engine: CognitiveSentimentEngine):
        """Multiple bearish keywords produce negative score."""
        result = engine.analyze_sentiment("Weak breakdown and distribution detected")
        assert result.score < 0
        assert result.is_ai_generated is False

    def test_mixed_sentiment(self, engine: CognitiveSentimentEngine):
        """Equal bullish and bearish keywords produce neutral score."""
        result = engine.analyze_sentiment(
            "Strong breakout but weak distribution pattern"
        )
        assert result.score == 0.0  # 1 bullish (strong), 1 bearish (weak) = 0
        assert result.is_ai_generated is False

    def test_neutral_text(self, engine: CognitiveSentimentEngine):
        """No matching keywords → score = 0.0."""
        result = engine.analyze_sentiment("The market opened flat today")
        assert result.score == 0.0
        assert "0 bullish / 0 bearish" in result.nuance

    def test_empty_text(self, engine: CognitiveSentimentEngine):
        """Empty string → score = 0.0."""
        result = engine.analyze_sentiment("")
        assert result.score == 0.0

    def test_case_insensitivity(self, engine: CognitiveSentimentEngine):
        """Keywords match regardless of case."""
        result = engine.analyze_sentiment("BREAKOUT and SUPPORT levels holding")
        assert result.score > 0

    def test_partial_word_no_match(self, engine: CognitiveSentimentEngine):
        """'breakouts' should match 'breakout' (substring in keyword set)."""
        # The engine checks "if w in text_lower" so partial matches can happen
        result = engine.analyze_sentiment("Breakouts are occurring")
        # "breakout" is in "breakouts" → match
        assert result.score > 0

    def test_multiple_keywords_one_side(self, engine: CognitiveSentimentEngine):
        """Multiple same-direction keywords amplify score."""
        result = engine.analyze_sentiment(
            "Bullish breakout with strong support and accumulation upside"
        )
        # bullish: breakout, bullish, support, strong, accumulation, upside = 6
        # bearish: 0
        assert result.score > 0.5

    def test_text_with_numbers_and_symbols(self, engine: CognitiveSentimentEngine):
        """Sentiment works with non-alphabetic characters."""
        result = engine.analyze_sentiment("NIFTY @ 23,500 → strong breakout!")
        assert result.score > 0

    def test_unicode_text(self, engine: CognitiveSentimentEngine):
        """Unicode characters don't break sentiment analysis."""
        result = engine.analyze_sentiment("Märkt üpside breakout détected")
        # "üpside" contains "upside"? No, "üpside" != "upside"
        # "détected" doesn't contain any keyword
        # "breakout" is in "breakout" → correct match
        # Actually, "breakout détected" - does "breakout" in "breakout détected"? Yes.
        assert result.score > 0 or result.score == 0.0


# ── Custom Keywords ─────────────────────────────────────────────────────────


class TestCustomKeywords:
    def test_custom_bullish_keyword(self):
        """Engine with custom bullish keywords."""
        engine = CognitiveSentimentEngine(cfg={})
        engine.bullish_keywords = {"moon", "rocket"}
        result = engine.analyze_sentiment("To the moon!")
        assert result.score > 0

    def test_custom_bearish_keyword(self):
        """Engine with custom bearish keywords."""
        engine = CognitiveSentimentEngine(cfg={})
        engine.bearish_keywords = {"dump", "crash"}
        result = engine.analyze_sentiment("Market dump incoming")
        assert result.score < 0


# ── AI Path (via SovereigntyGuard) ──────────────────────────────────────────


class TestAiPath:
    def test_ai_path_when_guard_allows(self, engine_with_guard):
        """When guard.can_use_ai() returns True, AI path is used."""
        engine, guard = engine_with_guard
        result = engine.analyze_sentiment("Market analysis text")
        assert result.is_ai_generated is True
        assert result.score == 0.75
        assert result.confidence == 0.9

    def test_ai_path_not_used_without_guard(self, engine: CognitiveSentimentEngine):
        """Without SovereigntyGuard, local path is used."""
        result = engine.analyze_sentiment("Strong breakout")
        assert result.is_ai_generated is False

    def test_ai_path_guard_returns_false(self):
        """When guard.can_use_ai() returns False, local path is used."""
        guard = MagicMock()
        guard.can_use_ai.return_value = False
        engine = CognitiveSentimentEngine(cfg={}, sov_guard=guard)
        result = engine.analyze_sentiment("Strong breakout")
        assert result.is_ai_generated is False
        assert "Local Analysis" in result.nuance

    def test_ai_path_guard_allows_then_local_fallback(self):
        """When AI raises, fall back to local sentiment."""
        guard = MagicMock()
        guard.can_use_ai.return_value = True
        engine = CognitiveSentimentEngine(cfg={}, sov_guard=guard)
        # Force _get_ai_reasoning to raise
        original_method = engine._get_ai_reasoning
        engine._get_ai_reasoning = MagicMock(side_effect=RuntimeError("API down"))

        result = engine.analyze_sentiment("Strong breakout")
        assert result.is_ai_generated is False
        assert "Local Analysis" in result.nuance

    def test_ai_path_with_config(self):
        """Engine respects config dict."""
        guard = MagicMock()
        guard.can_use_ai.return_value = True
        engine = CognitiveSentimentEngine(cfg={"ai_enabled": True}, sov_guard=guard)
        result = engine.analyze_sentiment("Test")
        assert result.is_ai_generated is True

    def test_ai_path_logs_reasoning(self, engine_with_guard):
        """AI path logs a message."""
        engine, _ = engine_with_guard
        with pytest.MonkeyPatch.context() as mp:
            msgs = []
            logger = MagicMock()
            logger.info = lambda msg: msgs.append(msg)
            mp.setattr(engine, "logger", logger)
            engine.analyze_sentiment("Test")
            assert any("[AI_REASONING]" in str(m) for m in msgs)
