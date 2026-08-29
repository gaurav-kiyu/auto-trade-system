import json
import logging
import os
from dataclasses import dataclass

_log = logging.getLogger(__name__)

@dataclass
class SentimentResult:
    score: float  # -100 to +100
    confidence: float # 0 to 1
    reasoning: str
    weight_impact_cap: float = 2.5 # Max 2.5% portfolio weight drift allowed for safety

class AgenticSentimentEngine:
    """
    Ingests live news, earnings transcripts, and RBI circulars.
    Uses LLM to quantify sentiment into actionable quantitative alpha.
    """
    def __init__(self):
        self.api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
        self.is_active = bool(self.api_key) and not self.api_key.startswith("your_") and len(self.api_key) > 20

        if self.is_active:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel("gemini-1.5-flash")
            except Exception:
                _log.warning("google.generativeai not configured. Sentiment Engine running in local heuristic mode.")
                self.is_active = False

    def analyze_news(self, symbol: str, news_text: str) -> SentimentResult:
        key = (os.getenv("GEMINI_API_KEY") or "").strip()
        if not key or key.startswith("your_") or len(key) < 20 or not news_text:
            return self._fallback_analysis(symbol, news_text)

        prompt = f"""
        You are a quantitative hedge fund macro-analyst.
        Analyze the following news event for the stock: {symbol}

        News: "{news_text}"

        Return ONLY a JSON object with these exactly keys:
        - "score": A float between -100.0 (extremely bearish) and +100.0 (extremely bullish).
        - "confidence": A float between 0.0 and 1.0 indicating how sure you are this will impact the stock price.
        - "reasoning": A 1-sentence explanation of your score.
        """

        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.model.generate_content, prompt)
                response = future.result(timeout=0.8)
            # Clean output in case it contains markdown formatting
            raw_text = response.text.replace("```json", "").replace("```", "").strip()
            data = json.loads(raw_text)

            # Dynamic Cap based on VIX
            try:
                from core.ai.live_indicators import get_live_indicator_engine
                vix = get_live_indicator_engine().fetch_india_vix()
            except ImportError:
                vix = 15.0

            if vix > 20.0:
                dynamic_cap = 0.5 # High panic: Trust math, restrict LLM to 0.5% impact
            elif vix < 15.0:
                dynamic_cap = 2.5 # Calm: Allow LLM higher influence up to 2.5%
            else:
                dynamic_cap = 1.5

            return SentimentResult(
                score=float(data.get("score", 0.0)),
                confidence=float(data.get("confidence", 0.5)),
                reasoning=data.get("reasoning", "Agent analyzed the news event."),
                weight_impact_cap=dynamic_cap
            )
        except Exception as e:
            _log.error(f"Agentic Sentiment LLM failed: {e}")
            return self._fallback_analysis(symbol, news_text)

    def _fallback_analysis(self, symbol: str, news_text: str) -> SentimentResult:
        """Simple heuristic fallback if LLM is unavailable."""
        news_lower = str(news_text).lower()
        bull_words = ["profit", "growth", "jump", "surge", "approved", "dividend"]
        bear_words = ["loss", "fall", "crash", "declines", "resigns", "scandal"]

        score = 0.0
        for w in bull_words:
            if w in news_lower:
                score += 20.0
        for w in bear_words:
            if w in news_lower:
                score -= 20.0

        score = max(min(score, 100.0), -100.0)

        return SentimentResult(
            score=score,
            confidence=0.6,
            reasoning="Fallback heuristic sentiment mapping applied."
        )

_agentic_engine = AgenticSentimentEngine()

def get_agentic_sentiment() -> AgenticSentimentEngine:
    return _agentic_engine
