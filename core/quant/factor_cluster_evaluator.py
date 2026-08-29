"""Layer 2 & 3: Strategy Evidence Clusters & 2-Level Hierarchical Weighting (v6.0 Production).

Structure:
- 14 Trading Strategies partitioned across 4 distinct factor clusters
- Level 1: Cluster Weight W_c(Asset, Regime) where sum(W_c) = 1.0
- Level 2: Strategy Weight W_s|c within Cluster where sum(W_s|c) = 1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.logging import get_logger

_log = get_logger("QUANT_CLUSTERS")


@dataclass
class ClusterEvidence:
    cluster_name: str
    cluster_score: float  # 0 to 100
    cluster_weight: float  # 0.0 to 1.0
    strategy_scores: dict[str, float] = field(default_factory=dict)
    strategy_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class AggregatedFactorEvidence:
    composite_score: float  # 0 to 100
    cluster_evidences: dict[str, ClusterEvidence] = field(default_factory=dict)
    resolved_weights_matrix: dict[str, Any] = field(default_factory=dict)


class FactorClusterEvaluator:
    """Evaluates the 14 Trading Strategies across 4 Factor Clusters using a 2-Level Weighting Tree."""

    # Baseline Strategy Weights within each Cluster (Level 2: sum to 1.0 per cluster)
    DEFAULT_STRATEGY_SUB_WEIGHTS: dict[str, dict[str, float]] = {
        "MOMENTUM_TREND_CLUSTER": {
            "OPB": 0.40,
            "SUPERTREND": 0.35,
            "VOLATILITY_SQUEEZE": 0.25,
        },
        "OPTIONS_DERIVATIVES_CLUSTER": {
            "CVD_ORDERFLOW": 0.35,
            "GEX": 0.35,
            "GREEKS_TAIL_RISK": 0.15,
            "0DTE_HARVESTER": 0.15,
        },
        "MEAN_REVERSION_CLUSTER": {
            "VWAP_PULLBACK": 0.35,
            "RSI_EXTREME": 0.25,
            "GAP_FADE": 0.20,
            "LIQUIDITY_HUNT": 0.20,
        },
        "CONTEXT_MACRO_CLUSTER": {
            "SECTOR_RELATIVE_STRENGTH": 0.40,
            "FII_DII_FLOW": 0.35,
            "DCF_MARGIN_OF_SAFETY": 0.25,
        },
    }

    # Baseline Cluster Weights by Asset Class (Level 1: sum to 1.0)
    ASSET_CLUSTER_WEIGHTS: dict[str, dict[str, float]] = {
        "INDEX_OPTION": {
            "MOMENTUM_TREND_CLUSTER": 0.25,
            "OPTIONS_DERIVATIVES_CLUSTER": 0.55,
            "MEAN_REVERSION_CLUSTER": 0.15,
            "CONTEXT_MACRO_CLUSTER": 0.05,
        },
        "EQUITY_INTRADAY": {
            "MOMENTUM_TREND_CLUSTER": 0.35,
            "OPTIONS_DERIVATIVES_CLUSTER": 0.25,
            "MEAN_REVERSION_CLUSTER": 0.20,
            "CONTEXT_MACRO_CLUSTER": 0.20,
        },
        "EQUITY_POSITIONAL": {
            "MOMENTUM_TREND_CLUSTER": 0.20,
            "OPTIONS_DERIVATIVES_CLUSTER": 0.10,
            "MEAN_REVERSION_CLUSTER": 0.20,
            "CONTEXT_MACRO_CLUSTER": 0.50,
        },
    }

    def evaluate(
        self,
        asset_class: str,
        regime: str,
        raw_strategy_scores: dict[str, float],
    ) -> AggregatedFactorEvidence:
        """Calculate the 2-level hierarchical composite score."""
        asset_key = "INDEX_OPTION" if "OPTION" in asset_class.upper() else (
            "EQUITY_POSITIONAL" if "POSITIONAL" in asset_class.upper() else "EQUITY_INTRADAY"
        )
        cluster_weights = dict(self.ASSET_CLUSTER_WEIGHTS.get(asset_key, self.ASSET_CLUSTER_WEIGHTS["EQUITY_INTRADAY"]))

        # Regime-based adaptation of cluster weights
        if regime in ("TRENDING_BULLISH", "TRENDING_BEARISH"):
            cluster_weights["MOMENTUM_TREND_CLUSTER"] = min(0.60, cluster_weights["MOMENTUM_TREND_CLUSTER"] + 0.10)
            cluster_weights["MEAN_REVERSION_CLUSTER"] = max(0.05, cluster_weights["MEAN_REVERSION_CLUSTER"] - 0.10)
        elif regime == "RANGE_BOUND_CHOPPY":
            cluster_weights["MEAN_REVERSION_CLUSTER"] = min(0.50, cluster_weights["MEAN_REVERSION_CLUSTER"] + 0.15)
            cluster_weights["MOMENTUM_TREND_CLUSTER"] = max(0.10, cluster_weights["MOMENTUM_TREND_CLUSTER"] - 0.15)

        # Normalize cluster weights to sum to 1.0
        total_cw = sum(cluster_weights.values())
        for c in cluster_weights:
            cluster_weights[c] /= total_cw

        # Evaluate each cluster
        cluster_evidences: dict[str, ClusterEvidence] = {}
        composite_score = 0.0
        resolved_matrix: dict[str, Any] = {"cluster_weights": cluster_weights, "strategy_weights": {}}

        for cluster_name, c_weight in cluster_weights.items():
            sub_weights = dict(self.DEFAULT_STRATEGY_SUB_WEIGHTS[cluster_name])

            # Explicit Zero-Weight DCF Strategy for Intraday Options
            if asset_key == "INDEX_OPTION" and cluster_name == "CONTEXT_MACRO_CLUSTER":
                sub_weights["DCF_MARGIN_OF_SAFETY"] = 0.0
                # Re-normalize remaining sub-strategies in Context cluster
                sub_total = sum(sub_weights.values())
                if sub_total > 0:
                    for k in sub_weights:
                        sub_weights[k] /= sub_total

            # Calculate cluster score
            c_score = 0.0
            strat_scores = {}
            for strat_name, s_weight in sub_weights.items():
                s_score = float(raw_strategy_scores.get(strat_name, 50.0))
                strat_scores[strat_name] = s_score
                c_score += s_weight * s_score

            cluster_evidences[cluster_name] = ClusterEvidence(
                cluster_name=cluster_name,
                cluster_score=c_score,
                cluster_weight=c_weight,
                strategy_scores=strat_scores,
                strategy_weights=sub_weights,
            )
            resolved_matrix["strategy_weights"][cluster_name] = sub_weights
            composite_score += c_weight * c_score

        return AggregatedFactorEvidence(
            composite_score=round(composite_score, 2),
            cluster_evidences=cluster_evidences,
            resolved_weights_matrix=resolved_matrix,
        )
