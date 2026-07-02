import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from core.ml_inference import ml_engine
from core.time_provider import time_provider

__all__ = [
    "SignalIntent",
    "SignalOrchestrator",
    "signal_orchestrator",
    "init_signal_orchestrator",
]

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

    Uses ``core.pure_index_signal.evaluate_index_signal_partial`` (migrated
    from the deprecated ``core.legacy.signal_engine.build_full_signal`` in v2.54).
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._signal_cache: dict[str, Any] = {}

    @staticmethod
    def _build_signal_params(
        cfg: dict[str, Any],
        name: str,
        is_early_session: bool = False,
    ) -> Any:
        """Build PureIndexSignalParams from config dict."""
        from core.pure_index_signal import PureIndexRegimeParams, PureIndexSignalParams

        return PureIndexSignalParams(
            name=name,
            signal_cfg=dict(cfg),
            regime=PureIndexRegimeParams(
                vix_block_threshold=float(cfg.get("VIX_BLOCK_THRESHOLD", 27)),
                adx_trend_threshold=float(cfg.get("REGIME_ADX_TREND", 20)),
                adx_chop_threshold=float(cfg.get("REGIME_ADX_RANGE", 15)),
            ),
            iv_spike_threshold=float(cfg.get("IV_SPIKE_THRESHOLD", 50)),
            vol_ratio_min=float(cfg.get("VOL_RATIO_MIN", 1.2)),
            is_early_session=is_early_session,
        )

    def process_market_data(self, symbol: str, data_frames: dict[str, Any],
                            additional_info: dict[str, Any]) -> SignalIntent | None:
        """
        The primary pipeline for turning raw data into a validated signal intent.

        Uses ``core.pure_index_signal.evaluate_index_signal_partial`` for
        technical analysis (modern replacement for ``build_full_signal``).
        Falls back gracefully on any unexpected error.
        """
        from core.pure_index_signal import evaluate_index_signal_partial

        df1 = data_frames.get("df1m")
        df5 = data_frames.get("df5m")
        df15 = data_frames.get("df15m")

        # Extract OI data from additional_info
        oi_data = additional_info.get("oi_data") or {}
        if isinstance(oi_data, dict):
            oi_pcr = float(oi_data.get("pcr", additional_info.get("pcr", 1.0)))
            oi_sup = float(oi_data.get("support", 0.0))
            oi_res = float(oi_data.get("resistance", 0.0))
            oi_smart = str(oi_data.get("smart_money", oi_data.get("smart", "NEUTRAL")))
        else:
            oi_pcr = float(additional_info.get("pcr", 1.0))
            oi_sup = 0.0
            oi_res = 0.0
            oi_smart = "NEUTRAL"

        vix = float(additional_info.get("vix", 0.0))
        iv = float(additional_info.get("iv", 0.0))

        params = self._build_signal_params(
            self.config, symbol,
            is_early_session=bool(additional_info.get("is_early_session", False)),
        )

        try:
            partial, reason = evaluate_index_signal_partial(
                params=params,
                df1=df1, df5=df5, df15=df15,
                vix=vix, iv=iv,
                oi_sup=oi_sup, oi_res=oi_res,
                pcr=oi_pcr, smart=oi_smart,
            )
        except Exception:
            log.exception("Signal partial evaluation failed for %s", symbol)
            return None

        if partial is None:
            log.debug("Signal block for %s: %s", symbol, reason)
            return None

        # Map partial result to match expected schema for ML layer
        score = int(partial["score"])
        direction = str(partial["direction"])
        price = float(partial["price"])
        regime = str(partial.get("mkt_regime", "NEUTRAL"))

        # 2. ML Governance Layer
        signal_for_ml = {
            "signal": "BUY" if direction in ("CALL", "UP") else "SELL",
            "direction": direction,
            "score": score,
            "confidence": float(score),
            "price": price,
            "strength": "STRONG" if score >= 85 else ("MODERATE" if score >= 70 else "WEAK"),
            "regime": regime,
            "iv": iv,
            "vix": vix,
            "pcr": oi_pcr,
        }
        features = self._extract_ml_features(signal_for_ml, data_frames)
        ml_pred = ml_engine.predict(features, regime=regime)

        # v2.54: Raised ML veto threshold from 0.30 to 0.50 for higher win rate.
        # Only signals with >50% ML-predicted win probability pass through.
        # This filters out the bottom ~30% of signals, improving selectivity.
        if ml_pred.win_probability < 0.50:
            log.info("ML Veto: %s signal blocked. Prob: %.2f", symbol, ml_pred.win_probability)
            return None

        # 3. Final Signal Intent Construction
        return SignalIntent(
            symbol=symbol,
            direction=direction,
            score=score,
            confidence=ml_pred.confidence_score,
            price=price,
            rationale=f"Score: {score} | ML Prob: {ml_pred.win_probability:.2f} | Regime: {regime}",
            regime=regime,
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
_orchestrator_lock = threading.RLock()

def init_signal_orchestrator(config: dict[str, Any]):
    global signal_orchestrator
    with _orchestrator_lock:
        if signal_orchestrator is None:
            signal_orchestrator = SignalOrchestrator(config)
