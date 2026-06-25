from typing import Any


__all__ = [
    "SentimentEngine",
]

class SentimentEngine:
    """
    Simulated LLM / News Sentiment Engine.
    In a live environment, this would hit an API (e.g. NewsAPI, AlphaVantage)
    to parse real-time headlines and use an LLM for sentiment extraction.
    """
    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def get_sentiment(self, symbol: str) -> dict[str, Any]:
        """
        Returns a dictionary with sentiment score (-1.0 to 1.0) and a panic flag.
        """
        if not self.api_key:
            return {
                "score": 0.0,
                "is_panic": False,
                "reason": "Sentiment API disabled/not configured."
            }

        try:
            # NOTE: This uses Google News RSS (unofficial/best-effort endpoint).
            # The RSS endpoint is undocumented and may change without notice.
            # On failure, we fall back to returning a neutral (score=0) result.
            import urllib.parse
            import urllib.request
            import xml.etree.ElementTree as ET

            # Use Google News RSS for the symbol
            query = f"{symbol} stock NSE India"
            url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()

            root = ET.fromstring(xml_data)
            items = root.findall('.//item')

            # Simple keyword-based sentiment analysis
            positive_words = {'bullish', 'surge', 'rally', 'gain', 'upgrade', 'buy',
                             'positive', 'growth', 'profit', 'strong', 'breakout'}
            negative_words = {'bearish', 'crash', 'fall', 'decline', 'downgrade', 'sell',
                            'negative', 'loss', 'weak', 'risk', 'caution', 'ban'}

            total_score = 0.0
            article_count = 0

            for item in items[:10]:  # Analyze top 10 articles
                title = (item.findtext('title') or '').lower()
                desc = (item.findtext('description') or '').lower()
                text = f"{title} {desc}"

                pos_count = sum(1 for w in positive_words if w in text)
                neg_count = sum(1 for w in negative_words if w in text)

                if pos_count > 0 or neg_count > 0:
                    article_score = (pos_count - neg_count) / max(pos_count + neg_count, 1)
                    total_score += article_score
                    article_count += 1

            if article_count > 0:
                avg_score = total_score / article_count
                is_panic = any(w in text for w in {'crash', 'ban', 'crisis', 'scam', 'fraud'}
                             for text in [(item.findtext('title') or '').lower() for item in items[:10]])
                return {
                    "score": round(avg_score, 3),
                    "is_panic": is_panic,
                    "reason": f"Analyzed {article_count} news articles via RSS",
                    "articles_found": len(items),
                }
        except (ImportError, urllib.error.URLError, ET.ParseError, Exception) as _sent_ex:
            logger = __import__('logging').getLogger(__name__)
            logger.debug("SentimentEngine RSS fetch failed: %s", _sent_ex)

        return {
            "score": 0.0,
            "is_panic": False,
            "reason": "Live API unavailable (RSS fetch failed or disabled).",
            "articles_found": 0,
        }
