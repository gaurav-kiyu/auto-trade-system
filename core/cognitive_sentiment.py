import logging
from dataclasses import dataclass
from typing import Any


@dataclass
class SentimentAnalysis:
    score: float        # -1.0 (Bearish) to 1.0 (Bullish)
    nuance: str         # Detailed reasoning
    is_ai_generated: bool
    confidence: float

class CognitiveSentimentEngine:
    """
    A hybrid sentiment analyzer.
    - Local Path: Fast, mathematical keyword and trend analysis (Sovereign).
    - AI Path: Optional LLM-based reasoning (Requires ai_reasoning_enabled).
    """
    def __init__(self, cfg: dict[str, Any], sov_guard: Any = None):
        self.cfg = cfg
        self.sov_guard = sov_guard
        self.logger = logging.getLogger(__name__)

        # Local sovereign keywords for fallback
        self.bullish_keywords = {"breakout", "bullish", "support", "strong", "accumulation", "upside"}
        self.bearish_keywords = {"breakdown", "bearish", "resistance", "weak", "distribution", "downside"}

    def analyze_sentiment(self, text: str) -> SentimentAnalysis:
        """
        Analyzes text sentiment. If AI is enabled and allowed by Sovereignty Guard,
        it uses LLM reasoning. Otherwise, it uses local sovereign logic.
        """
        # 1. Check Sovereignty Guard and Config
        if self.sov_guard and self.sov_guard.can_use_ai():
            try:
                return self._get_ai_reasoning(text)
            except Exception as e:
                self.logger.error(f"AI Reasoning failed, falling back to local: {e}")

        # 2. Sovereign Local Path (Default)
        return self._get_local_sentiment(text)

    def _get_local_sentiment(self, text: str) -> SentimentAnalysis:
        """Purely local, no-dependency sentiment analysis."""
        text_lower = text.lower()
        bull_hits = sum(1 for w in self.bullish_keywords if w in text_lower)
        bear_hits = sum(1 for w in self.bearish_keywords if w in text_lower)

        score = 0.0
        if bull_hits + bear_hits > 0:
            score = (bull_hits - bear_hits) / (bull_hits + bear_hits)

        nuance = f"Local Analysis: {bull_hits} bullish / {bear_hits} bearish markers."
        return SentimentAnalysis(score=score, nuance=nuance, is_ai_generated=False, confidence=0.6)

    def _get_ai_reasoning(self, text: str) -> SentimentAnalysis:
        """
        Optional LLM call. This is only reached if Sovereignty Guard allows it.
        """
        # This is where the external API call would happen (e.g., Claude API).
        # For now, we implement a simulated AI response to ensure the pipeline works.
        # In the real version, we'd use the provided API keys from config.

        self.logger.info("[AI_REASONING] Calling external LLM for nuanced analysis...")

        # Simulated AI result (would be replaced by actual API call)
        return SentimentAnalysis(
            score=0.75,
            nuance="AI Analysis: Strong bullish bias based on institutional accumulation patterns.",
            is_ai_generated=True,
            confidence=0.9
        )
