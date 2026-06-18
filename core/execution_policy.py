"""
Execution Policy Layer - decides WHETHER to trade, HOW MUCH, and at WHAT risk params.

This sits between signal generation and broker execution. It is the single
authoritative source for execution decisions, replacing hardcoded class=="STRONG"
checks scattered across the codebase.

Decision hierarchy (applied in order, first matching rule wins):
  1. Hard veto rules  - always SKIP regardless of tier
  2. Regime gates     - certain regime+tier combinations → SKIP
  3. Quality filters  - configurable score/feature rules → SKIP
  4. Position sizing  - tier × regime × score-within-tier → lots
  5. Risk adjustments - SL/TP multipliers per tier

All rules are configurable via config["execution_policy"] section.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from core.services.risk_service import PositionSizer, PositionSpec  # consolidated
from core.tier_engine import (
    TIER_WEAK_MIN,
    classify_tier,
    get_tier_rules,
)

log = logging.getLogger("execution_policy")


# ── Regime constant aliases ───────────────────────────────────────────────────
_REGIME_TRENDING    = "TRENDING"
_REGIME_SIDEWAYS    = "SIDEWAYS"
_REGIME_CHOPPY      = "CHOPPY"
_REGIME_HIGH_VOL    = "HIGH_VOLATILITY"
_REGIME_EVENT       = "EVENT"
_REGIME_NEUTRAL     = "NEUTRAL"

# Regimes in which all WEAK-tier trades are blocked
_WEAK_SKIP_REGIMES = {_REGIME_SIDEWAYS, _REGIME_CHOPPY, _REGIME_EVENT}

# Regimes in which MODERATE is allowed but at 70% of computed size
_MODERATE_SIZE_CUT_REGIMES = {_REGIME_HIGH_VOL, _REGIME_SIDEWAYS}


# ── Result dataclass ──────────────────────────────────────────────────────────
@dataclass
class ExecutionDecision:
    trade: bool                       # place order?
    tier: str                         # STRONG / MODERATE / WEAK / IGNORE
    position_spec: PositionSpec | None

    # Risk param adjustments (on top of base SimConfig / signal values)
    sl_mult: float   = 1.0            # multiply base SL distance
    tp_mult: float   = 1.0            # multiply base TP distance
    trail_enabled: bool       = True
    trail_activate_pct: float = 0.30
    trail_from_peak_pct: float = 0.20
    partial_exit_enabled: bool = False
    partial_exit_pct: float    = 0.0
    max_bars_mult: float       = 1.0

    mode: str = "SKIP"                # FULL / PARTIAL / REDUCED / SKIP
    reasons: list[str] = field(default_factory=list)
    quality_score: float = 0.0        # 0.0-1.0 composite signal quality

    @property
    def lots(self) -> int:
        return self.position_spec.lots if self.position_spec else 0

    @property
    def position_pct(self) -> float:
        return self.position_spec.effective_pct if self.position_spec else 0.0


# ── Quality scoring ───────────────────────────────────────────────────────────
def _quality_score(signal: Mapping[str, Any]) -> float:
    """
    Composite 0-1 quality score from signal features.
    Higher = more reliable setup.
    """
    score     = int(signal.get("score", 0))
    breakout  = bool(signal.get("breakout_ok", False))
    vol_ratio = float(signal.get("vol_ratio", 0.0))
    adx       = float(signal.get("adx", 0.0))
    rsi       = float(signal.get("rsi", 50.0))
    regime    = str(signal.get("mkt_regime") or signal.get("regime", "NEUTRAL"))

    q = 0.0
    # Score contribution (normalised to 0-1 relative to WEAK_MIN baseline)
    q += min(1.0, max(0.0, (score - TIER_WEAK_MIN) / (100 - TIER_WEAK_MIN))) * 0.40

    # Breakout presence = strong confirming signal
    q += 0.20 if breakout else 0.0

    # Volume confirmation (vol_ratio ≥ 1.5 = full marks)
    q += min(0.15, (vol_ratio - 1.0) / 2.0 * 0.15) if vol_ratio >= 1.0 else 0.0

    # ADX strength (≥20 = trending, ≥30 = full marks)
    q += min(0.15, (adx - 10.0) / 20.0 * 0.15) if adx >= 10.0 else 0.0

    # RSI in healthy continuation zone (40-70 for CALL, 30-60 for PUT)
    direction = str(signal.get("direction", "CALL"))
    if direction == "CALL" and 40 <= rsi <= 70:
        q += 0.10
    elif direction == "PUT" and 30 <= rsi <= 60:
        q += 0.10

    # Regime bonus/penalty
    regime_adj = {
        _REGIME_TRENDING:  +0.05,
        _REGIME_NEUTRAL:    0.00,
        _REGIME_SIDEWAYS:  -0.10,
        _REGIME_CHOPPY:    -0.15,
        _REGIME_HIGH_VOL:  -0.05,
        _REGIME_EVENT:     -0.20,
    }
    q += regime_adj.get(regime, 0.0)

    return round(max(0.0, min(1.0, q)), 3)


# ── Main policy class ─────────────────────────────────────────────────────────
class ExecutionPolicy:
    """
    Stateless execution policy engine.

    Usage:
        decision = ExecutionPolicy.apply(signal, config, regime)
        if decision.trade:
            place_order(lots=decision.lots, sl_mult=decision.sl_mult, ...)
    """

    @staticmethod
    def apply(
        signal: Mapping[str, Any],
        config: Mapping[str, Any],
        regime: str,
        max_lots: int = 1,
        capital: float = 100_000.0,
    ) -> ExecutionDecision:
        """
        Evaluate a signal and return a full execution decision.

        Args:
            signal:    The signal dict from evaluate_index_signal_partial / adaptive_signal
            config:    config.json dict (or subset)
            regime:    Market regime string
            max_lots:  Maximum configured lots
            capital:   Available capital

        Returns:
            ExecutionDecision with trade=True/False and full risk params
        """
        pol = (config or {}).get("execution_policy", {})
        score = int(signal.get("score", 0))
        tier  = classify_tier(score)

        def _skip(reason: str, q: float = 0.0) -> ExecutionDecision:
            return ExecutionDecision(
                trade=False, tier=tier, position_spec=None,
                mode="SKIP", reasons=[reason], quality_score=q,
            )

        # ── 1. Hard veto: IGNORE tier ─────────────────────────────────────
        if tier == "IGNORE":
            return _skip(f"score {score} below WEAK_MIN {TIER_WEAK_MIN} - IGNORE tier")

        # ── 2. WEAK tier gate ─────────────────────────────────────────────
        trade_weak = bool(pol.get("trade_weak", config.get("TIER_TRADE_WEAK", False)))
        if tier == "WEAK" and not trade_weak:
            return _skip("WEAK tier disabled (trade_weak=False)")

        if tier == "WEAK" and regime in _WEAK_SKIP_REGIMES:
            return _skip(f"WEAK signal blocked in {regime} regime")

        # ── 3. Quality filter rules ───────────────────────────────────────
        # Rule: score < quality_min_score AND no breakout → skip
        q_min     = int(pol.get("quality_min_score", config.get("QUALITY_MIN_SCORE", 68)))
        breakout  = bool(signal.get("breakout_ok", False))
        if score < q_min and not breakout:
            return _skip(
                f"Quality filter: score {score} < {q_min} with no breakout confirmation"
            )

        # Rule: MODERATE + choppy → skip (too risky, too little conviction)
        if tier == "MODERATE" and regime == _REGIME_CHOPPY:
            return _skip("MODERATE signal in CHOPPY regime - insufficient conviction")

        # Rule: custom configurable rules from config
        for rule in pol.get("custom_skip_rules", []):
            if _eval_skip_rule(signal, regime, rule):
                return _skip(f"Custom rule: {rule.get('name', 'unnamed')}")

        # ── 4. Compute quality score ──────────────────────────────────────
        quality = _quality_score(signal)

        # ── 5. Position sizing ────────────────────────────────────────────
        spec = PositionSizer.calculate(
            score=score,
            tier=tier,
            regime=regime,
            max_lots=max_lots,
            atr=float(signal.get("atr", 0.0)),
            capital=capital,
        )

        # Additional cut for HIGH_VOL + MODERATE: cap at 70% of computed size
        if tier == "MODERATE" and regime in _MODERATE_SIZE_CUT_REGIMES:
            spec = PositionSpec(
                tier=spec.tier, regime=spec.regime, score=spec.score,
                tier_base_pct=spec.tier_base_pct,
                regime_adj=spec.regime_adj,
                score_adj=spec.score_adj,
                effective_pct=round(spec.effective_pct * 0.70, 4),
                lots=max(1, int(spec.lots * 0.70)),
                reasoning=spec.reasoning + " [HIGH_VOL cut ×0.70]",
            )

        # ── 6. SL / TP / trail adjustments from TierRules ────────────────
        rules = get_tier_rules(score)

        # Regime-level fast-exit: HIGH_VOL → tighten TP to capture faster
        tp_mult = rules.tp_mult_adj
        sl_mult = rules.sl_mult_adj
        if regime == _REGIME_HIGH_VOL:
            tp_mult = min(tp_mult, 0.75)   # take profit at 75% of normal TP
            sl_mult = min(sl_mult, 0.85)   # tighten SL

        # Determine execution mode
        if tier == "STRONG" and not signal.get("soft_blocks"):
            mode = "FULL"
        elif tier == "MODERATE":
            mode = "PARTIAL" if rules.partial_exit_enabled else "FULL"
        else:
            mode = "REDUCED"

        reasons = [
            f"tier={tier} score={score} regime={regime}",
            f"position={spec.effective_pct:.0%} ({spec.lots}/{max_lots} lots)",
            f"quality={quality:.2f}",
        ]
        soft = list(signal.get("soft_blocks", []))
        if soft:
            reasons.append(f"soft_blocks={soft}")

        return ExecutionDecision(
            trade=True,
            tier=tier,
            position_spec=spec,
            sl_mult=sl_mult,
            tp_mult=tp_mult,
            trail_enabled=rules.trail_enabled,
            trail_activate_pct=rules.trail_activate_pct,
            trail_from_peak_pct=rules.trail_from_peak_pct,
            partial_exit_enabled=rules.partial_exit_enabled,
            partial_exit_pct=rules.partial_exit_pct,
            max_bars_mult=rules.max_bars_mult,
            mode=mode,
            reasons=reasons,
            quality_score=quality,
        )


def _eval_skip_rule(
    signal: Mapping[str, Any],
    regime: str,
    rule: Mapping[str, Any],
) -> bool:
    """
    Evaluate a single config-driven skip rule.

    Rule schema:
        {"name": "low_score_no_vol", "score_max": 68, "require_breakout": true}
        {"name": "flat_regime", "regimes": ["SIDEWAYS", "CHOPPY"], "tier_max": "WEAK"}
    """
    score    = int(signal.get("score", 0))
    breakout = bool(signal.get("breakout_ok", False))
    float(signal.get("vol_ratio", 0.0))
    tier     = classify_tier(score)

    tier_order = {"IGNORE": 0, "WEAK": 1, "MODERATE": 2, "STRONG": 3}

    # score_max: skip if score <= value
    if "score_max" in rule and score > int(rule["score_max"]):
        return False

    # require_breakout: skip if breakout absent
    if rule.get("require_breakout") and not breakout:
        pass  # condition met, continue checking other predicates
    elif "require_breakout" in rule:
        return False  # breakout present, rule not triggered

    # regimes: skip only in listed regimes
    if "regimes" in rule and regime not in rule["regimes"]:
        return False

    # tier_max: skip only if tier <= value
    if "tier_max" in rule:
        if tier_order.get(tier, 0) > tier_order.get(rule["tier_max"], 0):
            return False

    return True


# ── Convenience: enrich signal dict with execution decision ───────────────────
def enrich_signal_with_policy(
    signal: dict,
    config: Mapping[str, Any],
    max_lots: int = 1,
    capital: float = 100_000.0,
) -> dict:
    """
    Return a copy of signal with execution_policy fields merged in.
    Useful for Telegram formatting and logging.
    """
    regime = str(signal.get("mkt_regime") or signal.get("regime") or "NEUTRAL")
    decision = ExecutionPolicy.apply(
        signal=signal,
        config=config,
        regime=regime,
        max_lots=max_lots,
        capital=capital,
    )
    return {
        **signal,
        "exec_tier":        decision.tier,
        "exec_trade":       decision.trade,
        "exec_mode":        decision.mode,
        "exec_lots":        decision.lots,
        "exec_position_pct": round(decision.position_pct * 100, 1),
        "exec_quality":     decision.quality_score,
        "exec_sl_mult":     decision.sl_mult,
        "exec_tp_mult":     decision.tp_mult,
        "exec_reasons":     decision.reasons,
    }
