import logging
from dataclasses import dataclass, field
from typing import Any

from core.ml_inference import ml_engine
from core.time_provider import time_provider

log = logging.getLogger("signal_orchestrator")

@dataclass
class SignalIntent:
    symbol: str
    direction: str
    score: int
    confidence: float
    price: float
    rationale: str
    regime: str
    timestamp: str = field(default_factory=lambda: time_provider.format_ts())

class SignalOrchestrator:
    """
    Orchestrates the signal generation pipeline.
    Decouples the 'Scanning' logic from the 'Trading' logic.
    
    Flow: Market Data -> Technical Analysis -> ML Validation -> Risk Gating -> Signal Intent
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._signal_cache: dict[str, Any] = {}

    def process_market_data(self, symbol: str, data_frames: dict[str, Any],
                            additional_info: dict[str, Any]) -> SignalIntent | None:
        """
        The primary pipeline for turning raw data into a validated signal intent.
        """
        # 1. Technical Analysis (Delegated to signal_engine.py)
        # In a full refactor, we would move signal_engine.py logic into a Strategy class
        from signal_engine import build_full_signal

        signal = build_full_signal(
            symbol=symbol,
            df1m=data_frames.get("df1m"),
            df5m=data_frames.get("df5m"),
            df15m=data_frames.get("df15m"),
            asset_type=additional_info.get("asset_type", "index"),
            oi_data=additional_info.get("oi_data"),
            iv=additional_info.get("iv", 0.0),
            vix=additional_info.get("vix", 0.0),
            sector=additional_info.get("sector", ""),
            category=additional_info.get("category", ""),
            threshold=self.config.get("AI_THRESHOLD", 60),
            config=self.config
        )

        if not signal or signal.get("signal") == "HOLD":
            return None

        # 2. ML Governance Layer
        # We use the Hardened ML Inference Engine to validate the technical signal
        features = self._extract_ml_features(signal, data_frames)
        ml_pred = ml_engine.predict(features, regime=signal.get("regime", "NEUTRAL"))

        # ML Veto: If ML probability is extremely low, we block the signal
        if ml_pred.win_probability < 0.3:
            log.info(f"ML Veto: {symbol} signal blocked. Prob: {ml_pred.win_probability:.2f}")
            return None

        # 3. Final Signal Intent Construction
        return SignalIntent(
            symbol=symbol,
            direction=signal["direction"],
            score=signal["score"],
            confidence=ml_pred.confidence_score,
            price=signal["price"],
            rationale=f"Score: {signal['score']} | ML Prob: {ml_pred.win_probability:.2f}",
            regime=signal.get("regime", "NEUTRAL")
        )

    def _extract_ml_features(self, signal: dict[str, Any], data_frames: dict[str, Any]) -> dict[str, Any]:
        """
        Maps the signal and data to the 14-feature vector required by the ML model.
        """
        # This is a simplified mapping; in production, this uses the FeatureEngine
        return {
            "score": signal.get("score", 0),
            "confidence": signal.get("confidence", 0),
            "direction_call": 1 if signal.get("direction") == "CALL" else 0,
            "is_strong": 1 if signal.get("strength") == "STRONG" else 0,
            "is_moderate": 1 if signal.get("strength") == "MODERATE" else 0,
            "is_weak": 1 if signal.get("strength") == "WEAK" else 0,
            "has_soft_blocks": 0,
            "day_of_week": time_provider.now().weekday(),
            "hour_of_entry": time_provider.now().hour,
            "iv_rank": signal.get("iv", 0),
            "vix": signal.get("vix", 0),
            "pcr": signal.get("pcr", 0),
            "regime_code": 1 if signal.get("regime") == "TREND" else 0,
            "session_code": 1 # Simplified
        }

# Singleton instance
signal_orchestrator: SignalOrchestrator | None = None

def init_signal_orchestrator(config: dict[str, Any]):
    global signal_orchestrator
    signal_orchestrator = SignalOrchestrator(config)
