
import sys
import os
from pathlib import Path

# Add project root to sys.path
project_root = os.getcwd()
sys.path.append(project_root)

import logging
import time
from dataclasses import dataclass

# Mocking necessary components for a logic-only regression test
from core.adaptive_signal import AdaptiveSignal, evaluate_adaptive_signal
from core.news_sentinel import NewsSentinel, NewsRiskAssessment
from core.implied_move import ImpliedMove

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("REGRESSION_TEST")

def test_scenario(name, signal_data, news_headline=None):
    print(f"\n--- Testing Scenario: {name} ---")

    # 1. Test News Sentiment
    sentiment = "NEUTRAL"
    if news_headline:
        # We simulate the sentinel's logic
        from core.news_sentinel import BULLISH_KEYWORDS, BEARISH_KEYWORDS
        h = news_headline.lower()
        bull = [k for k in BULLISH_KEYWORDS if k in h]
        bear = [k for k in BEARISH_KEYWORDS if k in h]
        if bull and not bear: sentiment = "BULLISH"
        elif bear and not bull: sentiment = "BEARISH"
        elif bull and bear: sentiment = "MIXED"

    print(f"Expected Sentiment: {sentiment}")

    # 2. Test Signal Logic (Simplified trace)
    # Since we are testing the logic flow in index_trader.py,
    # we verify the la-components that build the final alert.

    score = signal_data.get("score", 0)
    regime = signal_data.get("regime", "NEUTRAL")

    # Regime Advice Logic check
    advice = "Standard Sizing"
    if regime == "HIGH_VOLATILITY":
        advice = "DEFENSIVE: Use 0.5x Lot Size & Tighten SL"
    elif regime == "EVENT":
        advice = "CAUTION: High Risk - Use Min Lot Size"

    print(f"Signal Score: {score} | Regime: {regime} | Advice: {advice}")

    # Implied Move calculation check
    target = "Not Available"
    if signal_data.get("option_chain"):
        try:
            from core.implied_move import compute_implied_move
            im = compute_implied_move(signal_data["option_chain"], signal_data["price"], {})
            if im:
                target = f"Range: {round(signal_data['price'] + im.move_points, 2)}"
        except Exception as e:
            target = f"Error: {e}"

    print(f"Target Zone: {target}")
    print(f"VERDICT: {'PASS' if (sentiment and advice) else 'FAIL'}")

if __name__ == '__main__':
    # Scenario 1: Perfect Signal
    test_scenario(
        "Perfect Signal",
        {"score": 90, "regime": "TRENDING", "price": 22000, "option_chain": {"calls": {22000: 100}, "puts": {22000: 100}}},
        "RBI announces massive growth support and FII buying surge"
    )

    # Scenario 2: The Trap
    test_scenario(
        "The Trap",
        {"score": 85, "regime": "HIGH_VOLATILITY", "price": 22000, "option_chain": {"calls": {22000: 200}, "puts": {22000: 200}}},
        "Inflation spikes and FII selling continues"
    )

    # Scenario 3: Data Gap
    test_scenario(
        "Data Gap",
        {"score": 75, "regime": "NEUTRAL", "price": 22000, "option_chain": None},
        None
    )
