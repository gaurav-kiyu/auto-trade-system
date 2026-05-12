from typing import Any


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

        # TODO: Implement live API call here
        return {
            "score": 0.0,
            "is_panic": False,
            "reason": "Live API not fully implemented yet."
        }
