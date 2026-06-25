"""
AD-KIYU Strategy implementations - used by ScoringEngine.
"""
from __future__ import annotations

from typing import Any


class BaseStrategy:
    def __init__(self, name: str, config: dict[str, Any]):
        self.name = name
        self.config = config

    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        raise NotImplementedError


class TrendAlignmentStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        trend = features.get("trend_5m", "FLAT")
        aligned = features.get("timeframe_aligned", False)
        regime = features.get("regime", "TRENDING")
        if trend == "FLAT":
            return {"score": 0, "status": False, "reason": "Trend is FLAT"}
        is_bullish = trend == "UP"
        if (direction == "CALL" and is_bullish) or (direction == "PUT" and not is_bullish):
            if regime == "CHOPPY":
                return {"score": 5, "status": True, "reason": "Trend valid but market CHOPPY"}
            if aligned:
                return {"score": 20, "status": True, "reason": f"Timeframes aligned ({trend})"}
            return {"score": 10, "status": True, "reason": f"5m Trend {trend} (15m unaligned)"}
        return {"score": 0, "status": False, "reason": f"Trend {trend} contradicts {direction}"}


class MeanReversionStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        regime = features.get("regime", "TRENDING")
        rsi = features.get("rsi", 50.0)
        price = features.get("price", 0.0)
        vwap = features.get("vwap", 0.0)
        if regime != "CHOPPY":
            return {"score": 0, "status": False, "reason": "Not a choppy regime"}
        dist_pct = abs(price - vwap) / vwap if vwap > 0 else 0
        is_stretched = dist_pct > 0.005
        if direction == "CALL" and price < vwap and rsi < 45 and is_stretched:
            return {"score": 25, "status": True, "reason": "Mean Reversion Bounce (Oversold under VWAP)"}
        if direction == "PUT" and price > vwap and rsi > 55 and is_stretched:
            return {"score": 25, "status": True, "reason": "Mean Reversion Reject (Overbought above VWAP)"}
        return {"score": 0, "status": False, "reason": "No Mean Reversion Setup"}


class VWAPStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        vwap_pos = features.get("vwap_position")
        regime = features.get("regime", "TRENDING")
        if regime == "CHOPPY":
            return {"score": 0, "status": False, "reason": "VWAP logic disabled in CHOPPY regime"}
        if direction == "CALL" and vwap_pos == "above":
            return {"score": 15, "status": True, "reason": "Price > VWAP"}
        if direction == "PUT" and vwap_pos == "below":
            return {"score": 15, "status": True, "reason": "Price < VWAP"}
        return {"score": 0, "status": False, "reason": f"Price {vwap_pos} VWAP against {direction}"}


class VolumeStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        vol_ratio = features.get("vol_ratio", 1.0)
        min_vol = self.config.get("vol_ratio_min", 1.2)
        if vol_ratio >= min_vol:
            return {"score": 10, "status": True, "reason": f"Volume Surge ({vol_ratio}x)"}
        return {"score": 0, "status": False, "reason": f"Low Volume ({vol_ratio}x < {min_vol})"}


class ATRStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        atr = features.get("atr", 0.0)
        min_atr = self.config.get("atr_min_threshold", 0.5)
        if atr > min_atr:
            return {"score": 5, "status": True, "reason": f"Healthy ATR ({atr} > {min_atr})"}
        return {"score": 0, "status": False, "reason": f"Low ATR ({atr} <= {min_atr})"}


class MomentumStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        macd = features.get("macd", {})
        hist = macd.get("histogram", 0)
        m_line = macd.get("macd", 0)
        s_line = macd.get("signal", 0)
        bonus = self.config.get("macd_bonus", 5)
        if direction == "CALL" and hist > 0 and m_line > s_line:
            return {"score": bonus, "status": True, "reason": f"MACD Bullish ({hist:.2f})"}
        if direction == "PUT" and hist < 0 and m_line < s_line:
            return {"score": bonus, "status": True, "reason": f"MACD Bearish ({hist:.2f})"}
        return {"score": 0, "status": False, "reason": "MACD Neutral/Contradictory"}


__all__ = [
    "BaseStrategy",
    "TrendAlignmentStrategy",
    "MeanReversionStrategy",
    "VWAPStrategy",
    "VolumeStrategy",
    "ATRStrategy",
    "MomentumStrategy",
    "RSIStrategy",
    "SmartMoneyStrategy",
]


class RSIStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        rsi = features.get("rsi", 50.0)
        ob = self.config.get("rsi_overbought", 70)
        os_v = self.config.get("rsi_oversold", 30)
        regime = features.get("regime", "TRENDING")
        if regime == "TRENDING":
            if direction == "CALL" and rsi > ob:
                return {"score": -10, "status": False, "reason": f"RSI Overbought ({rsi})"}
            if direction == "PUT" and rsi < os_v:
                return {"score": -10, "status": False, "reason": f"RSI Oversold ({rsi})"}
        if direction == "CALL" and 40 <= rsi <= ob:
            return {"score": 8, "status": True, "reason": f"RSI Healthy ({rsi})"}
        if direction == "PUT" and os_v <= rsi <= 50:
            return {"score": 8, "status": True, "reason": f"RSI Healthy ({rsi})"}
        return {"score": 0, "status": False, "reason": f"RSI Neutral ({rsi})"}


class SmartMoneyStrategy(BaseStrategy):
    def evaluate(self, features: dict[str, Any], direction: str) -> dict[str, Any]:
        smart = features.get("smart_money", "NEUTRAL")
        pcr = features.get("pcr", 1.0)
        pcr_bull = self.config.get("pcr_bullish", 1.2)
        pcr_bear = self.config.get("pcr_bearish", 0.8)
        score = 0; reasons = []; status = False
        if (direction == "CALL" and smart == "BULLISH") or (direction == "PUT" and smart == "BEARISH"):
            score += 10; reasons.append(f"OI {smart}"); status = True
        else:
            reasons.append("OI Neutral/Contradicts")
        if (direction == "CALL" and pcr > pcr_bull) or (direction == "PUT" and pcr < pcr_bear):
            score += 5; reasons.append(f"PCR Supports ({pcr:.2f})"); status = True
        else:
            reasons.append(f"PCR Neutral ({pcr:.2f})")
        return {"score": score, "status": status, "reason": " | ".join(reasons)}
