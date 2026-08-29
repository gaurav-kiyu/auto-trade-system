"""Empirical Quantitative Validation & Calibration Audit Engine (v6.0 Production).

Computes:
- Brier Score for Stage A (Direction) and Stage B (Conditional Outcomes)
- Expected Calibration Error (ECE) across 10 probability buckets
- Reliability table comparing predicted confidence vs observed frequency
- v5 (Flat Scoring) vs v6 (6-Layer Hierarchical) Head-to-Head Benchmark Matrix
- Cost-adjusted Net Expectancy, Profit Factor, Sharpe, Sortino, and Drawdown
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class ProbabilityBucket:
    bucket_range: str
    sample_count: int
    mean_predicted_confidence: float
    observed_actual_frequency: float
    calibration_error: float


@dataclass
class CalibrationAuditReport:
    total_signals_evaluated: int
    brier_score_t1: float
    brier_score_direction: float
    expected_calibration_error_ece: float
    reliability_buckets: list[ProbabilityBucket]
    calibration_status: str


@dataclass
class PerformanceMetrics:
    total_opportunities: int
    actionable_signals: int
    actionable_rate_pct: float
    win_rate_pct: float
    t1_hit_rate_pct: float
    t2_hit_rate_pct: float
    sl_hit_rate_pct: float
    timeout_rate_pct: float
    profit_factor: float
    net_expectancy_r: float
    average_win_r: float
    average_loss_r: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    total_net_pnl_r: float


@dataclass
class HeadToHeadComparisonReport:
    v5_baseline: PerformanceMetrics
    v6_candidate: PerformanceMetrics
    expectancy_improvement_pct: float
    profit_factor_improvement_pct: float
    drawdown_reduction_pct: float
    formal_gate_recommendation: str


class EmpiricalCalibrationValidator:
    """Institutional Empirical Calibration & Comparative Benchmark Validator."""

    def compute_brier_score(self, predictions: list[float], actuals: list[int]) -> float:
        """Calculate Brier Score: Mean squared error between probabilities and binary outcomes."""
        if not predictions or len(predictions) != len(actuals):
            return 0.0
        n = len(predictions)
        return round(sum((p - y) ** 2 for p, y in zip(predictions, actuals)) / n, 4)

    def compute_ece_and_reliability(
        self,
        predictions: list[float],
        actuals: list[int],
        num_bins: int = 5,
    ) -> tuple[float, list[ProbabilityBucket]]:
        """Compute Expected Calibration Error (ECE) and Reliability Table."""
        if not predictions or len(predictions) != len(actuals):
            return 0.0, []

        bin_size = 1.0 / num_bins
        buckets: list[ProbabilityBucket] = []
        n_total = len(predictions)
        weighted_ece = 0.0

        for i in range(num_bins):
            bin_low = i * bin_size
            bin_high = (i + 1) * bin_size

            # Filter samples in bin
            bin_preds = []
            bin_acts = []
            for p, y in zip(predictions, actuals):
                if (i == 0 and bin_low <= p <= bin_high) or (bin_low < p <= bin_high):
                    bin_preds.append(p)
                    bin_acts.append(y)

            count = len(bin_preds)
            if count > 0:
                mean_conf = sum(bin_preds) / count
                obs_freq = sum(bin_acts) / count
                cal_err = abs(obs_freq - mean_conf)
                weighted_ece += (count / n_total) * cal_err

                buckets.append(
                    ProbabilityBucket(
                        bucket_range=f"{bin_low*100:.0f}%–{bin_high*100:.0f}%",
                        sample_count=count,
                        mean_predicted_confidence=round(mean_conf, 4),
                        observed_actual_frequency=round(obs_freq, 4),
                        calibration_error=round(cal_err, 4),
                    )
                )

        return round(weighted_ece, 4), buckets

    def evaluate_performance(
        self,
        outcomes: list[dict[str, Any]],
    ) -> PerformanceMetrics:
        """Calculate complete institutional trading and risk-adjusted metrics."""
        total_opps = len(outcomes)
        actionable_trades = [t for t in outcomes if t.get("is_actionable", True)]
        n_act = len(actionable_trades)

        if n_act == 0:
            return PerformanceMetrics(
                total_opportunities=total_opps, actionable_signals=0, actionable_rate_pct=0.0,
                win_rate_pct=0.0, t1_hit_rate_pct=0.0, t2_hit_rate_pct=0.0, sl_hit_rate_pct=0.0,
                timeout_rate_pct=0.0, profit_factor=0.0, net_expectancy_r=0.0, average_win_r=0.0,
                average_loss_r=0.0, max_drawdown_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
                total_net_pnl_r=0.0,
            )

        t1_hits = sum(1 for t in actionable_trades if t.get("outcome") in ("T1", "T2"))
        t2_hits = sum(1 for t in actionable_trades if t.get("outcome") == "T2")
        sl_hits = sum(1 for t in actionable_trades if t.get("outcome") == "SL")
        timeout_hits = sum(1 for t in actionable_trades if t.get("outcome") == "TIMEOUT")

        wins = [t["net_pnl_r"] for t in actionable_trades if t.get("net_pnl_r", 0.0) > 0.0]
        losses = [abs(t["net_pnl_r"]) for t in actionable_trades if t.get("net_pnl_r", 0.0) < 0.0]

        total_wins_r = sum(wins)
        total_losses_r = sum(losses)
        pf = round(total_wins_r / total_losses_r, 2) if total_losses_r > 0 else 9.99

        pnl_series = [t.get("net_pnl_r", 0.0) for t in actionable_trades]
        total_net_pnl = sum(pnl_series)
        net_exp = round(total_net_pnl / n_act, 3)

        avg_win = round(sum(wins) / len(wins), 2) if wins else 0.0
        avg_loss = round(sum(losses) / len(losses), 2) if losses else 0.0

        # Drawdown calculation
        peak = 0.0
        running = 0.0
        max_dd = 0.0
        for pnl in pnl_series:
            running += pnl
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        # Sharpe & Sortino (assuming zero risk-free rate per trade)
        mean_ret = total_net_pnl / n_act
        variance = sum((r - mean_ret) ** 2 for r in pnl_series) / n_act if n_act > 1 else 0.01
        std_dev = math.sqrt(variance) if variance > 0 else 0.01
        sharpe = round((mean_ret / std_dev) * math.sqrt(252), 2)

        downside_variance = sum((min(0.0, r) - 0.0) ** 2 for r in pnl_series) / n_act if n_act > 1 else 0.01
        downside_std = math.sqrt(downside_variance) if downside_variance > 0 else 0.01
        sortino = round((mean_ret / downside_std) * math.sqrt(252), 2)

        return PerformanceMetrics(
            total_opportunities=total_opps,
            actionable_signals=n_act,
            actionable_rate_pct=round((n_act / total_opps) * 100.0, 1),
            win_rate_pct=round((len(wins) / n_act) * 100.0, 1),
            t1_hit_rate_pct=round((t1_hits / n_act) * 100.0, 1),
            t2_hit_rate_pct=round((t2_hits / n_act) * 100.0, 1),
            sl_hit_rate_pct=round((sl_hits / n_act) * 100.0, 1),
            timeout_rate_pct=round((timeout_hits / n_act) * 100.0, 1),
            profit_factor=pf,
            net_expectancy_r=net_exp,
            average_win_r=avg_win,
            average_loss_r=avg_loss,
            max_drawdown_pct=round(max_dd, 2),
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            total_net_pnl_r=round(total_net_pnl, 2),
        )

    def run_head_to_head_comparison(
        self,
        v5_trade_outcomes: list[dict[str, Any]],
        v6_trade_outcomes: list[dict[str, Any]],
    ) -> HeadToHeadComparisonReport:
        """Run head-to-head empirical validation between v5 and v6."""
        m5 = self.evaluate_performance(v5_trade_outcomes)
        m6 = self.evaluate_performance(v6_trade_outcomes)

        exp_imp = round(((m6.net_expectancy_r - m5.net_expectancy_r) / abs(m5.net_expectancy_r or 0.1)) * 100.0, 1)
        pf_imp = round(((m6.profit_factor - m5.profit_factor) / (m5.profit_factor or 1.0)) * 100.0, 1)
        dd_red = round(((m5.max_drawdown_pct - m6.max_drawdown_pct) / (m5.max_drawdown_pct or 1.0)) * 100.0, 1)

        if m6.profit_factor >= 1.5 and m6.net_expectancy_r >= 0.20 and m6.profit_factor >= m5.profit_factor:
            gate = "GO — Institutional Signal Quality Established"
        elif m6.net_expectancy_r > 0.0:
            gate = "CAUTION — Positive Edge but Further Calibration Recommended"
        else:
            gate = "NO_GO — Inadequate Edge after Transaction Costs"

        return HeadToHeadComparisonReport(
            v5_baseline=m5,
            v6_candidate=m6,
            expectancy_improvement_pct=exp_imp,
            profit_factor_improvement_pct=pf_imp,
            drawdown_reduction_pct=dd_red,
            formal_gate_recommendation=gate,
        )
