"""
DEPRECATED MODULE - Archived to core/legacy/.

This module has been superseded by core/services/risk_service.py
and core/tier_engine.py for decision logic.

Will be removed in a future release.
"""
"""
Decision Engine - maps signal score to class, eligibility, and tier.

Threshold alignment (mirrors tier_engine.py):
    STRONG   ≥ 80  → full execution eligible, tier=STRONG
    MODERATE 70-79 → Telegram + conditional execution, tier=MODERATE
    EARLY    60-69 → Telegram alert only (no auto-exec), tier=WEAK
    WATCH    < 60  → not eligible (dashboard only)

The 'strong' threshold (config.thresholds.strong) defaults to TIER_STRONG_MIN (80).
The 'early'  threshold (config.thresholds.early) defaults to TIER_WEAK_MIN (60).
"""

import logging
from typing import Any

from core.tier_engine import (
    TIER_MODERATE_MIN,
    TIER_STRONG_MIN,
    TIER_WEAK_MIN,
    classify_tier,
)

log = logging.getLogger(__name__)


class DecisionEngine:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def evaluate_decision(self, score_data: dict[str, Any]) -> dict[str, Any]:
        """
        Map signal score to class, tier, eligibility, and confidence.

        Returns a decision dict consumed by SignalRouter.
        """
        score     = score_data.get("total_score", score_data.get("score", 0))
        direction = score_data.get("direction", "CALL")

        # Thresholds: config overrides first, then tier_engine constants as defaults
        thresholds = self.config.get("thresholds", {})
        strong_thr   = int(thresholds.get("strong",   self.config.get("TIER_STRONG_MIN",   TIER_STRONG_MIN)))
        moderate_thr = int(thresholds.get("moderate", self.config.get("TIER_MODERATE_MIN", TIER_MODERATE_MIN)))
        early_thr    = int(thresholds.get("early",    self.config.get("TIER_WEAK_MIN",     TIER_WEAK_MIN)))
        # Guard: thresholds must be monotonically non-increasing; fix and warn if misconfigured
        if not (strong_thr >= moderate_thr >= early_thr > 0):
            log.warning(
                "[DECISION] Thresholds not monotonic (strong=%d moderate=%d early=%d) - clamping to safe defaults",
                strong_thr, moderate_thr, early_thr,
            )
            strong_thr   = max(strong_thr,   TIER_STRONG_MIN)
            moderate_thr = min(strong_thr - 1, max(moderate_thr, TIER_MODERATE_MIN))
            early_thr    = min(moderate_thr - 1, max(early_thr,  TIER_WEAK_MIN))

        # Classify into signal class (for routing logic)
        if score >= strong_thr:
            signal_class = "STRONG"
            signal_type  = f"STRONG_{'BUY' if direction in ('CALL', 'UP') else 'SELL'}"
            eligible     = True
        elif score >= moderate_thr:
            signal_class = "MODERATE"
            signal_type  = f"MODERATE_{'BUY' if direction in ('CALL', 'UP') else 'SELL'}"
            eligible     = True
        elif score >= early_thr:
            signal_class = "EARLY"
            signal_type  = f"EARLY_{'BUY' if direction in ('CALL', 'UP') else 'SELL'}"
            eligible     = True
        else:
            signal_class = "WEAK"
            signal_type  = "WATCH"
            eligible     = False

        # Tier (from canonical tier_engine - single source of truth)
        tier = classify_tier(int(score))

        # Confidence: normalise score relative to tier minimum (0-1 within tier band)
        if tier == "STRONG":
            confidence_norm = min(1.0, (score - strong_thr) / max(1, 100 - strong_thr))
        elif tier == "MODERATE":
            confidence_norm = (score - moderate_thr) / max(1, strong_thr - moderate_thr)
        elif tier == "WEAK":
            confidence_norm = (score - early_thr) / max(1, moderate_thr - early_thr)
        else:
            confidence_norm = 0.0
        confidence_norm = max(0.0, min(1.0, confidence_norm))

        return {
            "signal_type":    signal_type,
            "confidence":     int(score),        # raw score for backward compat
            "confidence_pct": round(confidence_norm * 100, 1),  # 0-100 within tier
            "class":          signal_class,
            "tier":           tier,
            "eligible":       eligible,
            "score_breakdown": score_data.get("components", []),
            "reasons":        score_data.get("reasons", []),
            "regime":         score_data.get("mkt_regime") or score_data.get("regime", "NEUTRAL"),
        }
