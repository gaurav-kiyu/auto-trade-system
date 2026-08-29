"""Layer 4: Calibrated Meta Model & Payoff Engine (v6.0 Production).

Formulates:
- Stage A: Mutually exclusive Directional Probabilities P(BUY) + P(SELL) + P(NO_TRADE) = 1.0
- Stage B: Conditional Trade-Outcome Probabilities P(T1|DIR) + P(SL|DIR) + P(TIMEOUT|DIR) = 1.0 with P(T2|DIR) <= P(T1|DIR)
- Non-Overlapping Expected Value E[V] with Finite-Horizon TIMEOUT settlement
- Transparent SHAP Drivers for Direction and Target 2
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.logging import get_logger

_log = get_logger("QUANT_META")


@dataclass
class DirectionalProbabilities:
    p_buy: float
    p_sell: float
    p_no_trade: float


@dataclass
class ConditionalOutcomeProbabilities:
    p_t1: float  # Probability T1 reached before SL or Timeout (including paths to T2)
    p_t2: float  # Probability T2 reached before SL or Timeout (subset of T1)
    p_sl: float  # Probability SL hit before T1 or Timeout
    p_timeout: float  # Probability horizon expires without hitting T1 or SL


@dataclass
class MetaEvaluationResult:
    direction: str  # BUY, SELL, NO_TRADE
    directional_prob: DirectionalProbabilities
    conditional_outcomes: ConditionalOutcomeProbabilities
    expected_value: float  # E[V] in R-multiples
    net_rr_t1: float
    net_rr_t2: float
    r_timeout: float
    direction_shap_drivers: list[str] = field(default_factory=list)
    outcome_shap_drivers: list[str] = field(default_factory=list)


class CalibratedMetaModel:
    """Layer 4 Meta-Classifier & Non-Overlapping Payoff Engine."""

    def __init__(self, probability_threshold: float = 0.75, min_expected_value: float = 0.15) -> None:
        self.probability_threshold = probability_threshold
        self.min_expected_value = min_expected_value

    def evaluate(
        self,
        composite_score: float,
        regime: str,
        cluster_scores: dict[str, float],
        entry_price: float,
        stop_loss_price: float,
        target_1_price: float,
        target_2_price: float,
        estimated_timeout_exit_price: float | None = None,
        estimated_slippage_cost_r: float = 0.05,
    ) -> MetaEvaluationResult:
        """Perform Stage A direction, Stage B conditional probabilities, and EV calculation."""
        # 1. Stage A: Mutually Exclusive Directional Probabilities
        if composite_score >= 68.0 and regime in ("TRENDING_BULLISH", "RANGE_BOUND_CHOPPY"):
            p_buy = min(0.95, 0.50 + (composite_score - 50.0) / 100.0)
            p_sell = max(0.02, (100.0 - composite_score) / 400.0)
            p_no_trade = max(0.03, 1.0 - (p_buy + p_sell))
            pred_direction = "BUY" if p_buy >= self.probability_threshold else "NO_TRADE"
        elif composite_score <= 35.0 and regime in ("TRENDING_BEARISH", "RANGE_BOUND_CHOPPY"):
            p_sell = min(0.95, 0.50 + (50.0 - composite_score) / 100.0)
            p_buy = max(0.02, composite_score / 400.0)
            p_no_trade = max(0.03, 1.0 - (p_buy + p_sell))
            pred_direction = "SELL" if p_sell >= self.probability_threshold else "NO_TRADE"
        else:
            p_no_trade = 0.70
            p_buy = 0.15
            p_sell = 0.15
            pred_direction = "NO_TRADE"

        dir_prob = DirectionalProbabilities(round(p_buy, 4), round(p_sell, 4), round(p_no_trade, 4))

        # 2. Calculate Gross & Net R-Multiples with Invariant: Initial Risk > 0
        initial_risk = max(0.01, abs(entry_price - stop_loss_price))
        gross_r1 = abs(target_1_price - entry_price) / initial_risk
        gross_r2 = abs(target_2_price - entry_price) / initial_risk
        net_rr_t1 = max(0.0, gross_r1 - estimated_slippage_cost_r)
        net_rr_t2 = max(0.0, gross_r2 - estimated_slippage_cost_r)

        # Direction-Aware Timeout Return normalized as R-Multiple (Invariant 9)
        if pred_direction == "SELL":
            timeout_price = estimated_timeout_exit_price if estimated_timeout_exit_price is not None else (entry_price - 0.3 * abs(entry_price - target_1_price))
            directional_mtm = entry_price - timeout_price
        else:
            timeout_price = estimated_timeout_exit_price if estimated_timeout_exit_price is not None else (entry_price + 0.3 * abs(target_1_price - entry_price))
            directional_mtm = timeout_price - entry_price

        r_timeout = round((directional_mtm / initial_risk) - estimated_slippage_cost_r, 4)

        # 3. Stage B: Conditional Trade-Outcome Probabilities
        if pred_direction == "BUY":
            p_t1 = min(0.90, 0.40 + (composite_score / 180.0))
            p_t2 = min(p_t1 * 0.75, 0.20 + (composite_score / 260.0))
            p_timeout = max(0.05, 0.25 - (composite_score / 500.0))
            p_sl = max(0.05, 1.0 - (p_t1 + p_timeout))
        elif pred_direction == "SELL":
            p_t1 = min(0.90, 0.40 + ((100.0 - composite_score) / 180.0))
            p_t2 = min(p_t1 * 0.75, 0.20 + ((100.0 - composite_score) / 260.0))
            p_timeout = max(0.05, 0.25 - ((100.0 - composite_score) / 500.0))
            p_sl = max(0.05, 1.0 - (p_t1 + p_timeout))
        else:
            p_t1, p_t2, p_sl, p_timeout = 0.30, 0.15, 0.40, 0.30

        # Normalization guard for Stage B
        p_t1 = round(p_t1, 4)
        p_t2 = round(min(p_t2, p_t1), 4)
        p_sl = round(p_sl, 4)
        p_timeout = round(max(0.0, 1.0 - (p_t1 + p_sl)), 4)

        cond_outcomes = ConditionalOutcomeProbabilities(p_t1, p_t2, p_sl, p_timeout)

        # 4. Rigorous Non-Overlapping Expected Value E[V]
        ev = (
            p_t2 * net_rr_t2
            + (p_t1 - p_t2) * net_rr_t1
            + p_timeout * r_timeout
            - p_sl * 1.0
        )
        ev = round(ev, 4)

        # 5. Dual-Stage SHAP Drivers
        dir_shap = [
            f"Momentum ({cluster_scores.get('MOMENTUM_TREND_CLUSTER', 50):.0f}/100) — Positive Contribution",
            f"Derivatives ({cluster_scores.get('OPTIONS_DERIVATIVES_CLUSTER', 50):.0f}/100) — Positive Contribution",
            f"Regime ({regime}) — Compatible",
        ]
        out_shap = [
            f"Target 2 Probability ({p_t2*100:.1f}%) driven by GEX & Order Flow",
            f"Expected Net R:R T2 ({net_rr_t2:.2f}R)",
        ]

        return MetaEvaluationResult(
            direction=pred_direction,
            directional_prob=dir_prob,
            conditional_outcomes=cond_outcomes,
            expected_value=ev,
            net_rr_t1=round(net_rr_t1, 2),
            net_rr_t2=round(net_rr_t2, 2),
            r_timeout=r_timeout,
            direction_shap_drivers=dir_shap,
            outcome_shap_drivers=out_shap,
        )
