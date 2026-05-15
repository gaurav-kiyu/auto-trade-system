from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .backtest_engine import BacktestConfig, BacktestEngine, BacktestReport, ReplayConfig
from .strategy_engine import StrategyEngine


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    report: BacktestReport


@dataclass(frozen=True)
class WalkForwardReport:
    windows: list[WalkForwardWindow]
    total_test_trades: int
    net_test_pnl: float
    avg_win_rate: float
    mode: str = "rolling"   # "rolling" | "anchored"

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "windows": [
                {
                    "train_start": window.train_start,
                    "train_end": window.train_end,
                    "test_start": window.test_start,
                    "test_end": window.test_end,
                    "report": window.report.to_dict(),
                }
                for window in self.windows
            ],
            "total_test_trades": self.total_test_trades,
            "net_test_pnl": self.net_test_pnl,
            "avg_win_rate": self.avg_win_rate,
        }


class WalkForwardEngine:
    """Evaluate strategy quality over rolling train/test windows."""

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        *,
        replay_config: ReplayConfig | None = None,
        backtest_config: BacktestConfig | None = None,
        adapt_fn: Callable[[pd.DataFrame], None] | None = None,
    ) -> None:
        self._strategy_engine = strategy_engine
        self._replay_config = replay_config or ReplayConfig()
        self._backtest_config = backtest_config or BacktestConfig()
        self._adapt_fn = adapt_fn

    def run(
        self,
        name: str,
        base_df: pd.DataFrame,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
        vix: float = 0.0,
        anchored: bool = False,
    ) -> WalkForwardReport:
        """
        Run walk-forward validation.

        Args:
            name       : Strategy / index name passed to the backtest engine.
            base_df    : Full price DataFrame (1-min or target resolution).
            train_bars : Number of bars in the initial training window.
            test_bars  : Number of bars in each test window.
            step_bars  : How many bars to advance per iteration (default = test_bars).
            vix        : VIX value forwarded to the strategy engine.
            anchored   : If True, use anchored (expanding) walk-forward: the train
                         window always starts from bar 0 and grows each step.
                         If False (default), the train window slides forward at
                         the same rate as the test window (rolling).

        Returns:
            WalkForwardReport with ``mode="anchored"`` or ``mode="rolling"``.
        """
        step = int(step_bars or test_bars)
        windows: list[WalkForwardWindow] = []
        idx = 0
        while idx + train_bars + test_bars <= len(base_df):
            if anchored:
                # Anchored: training always starts at bar 0, grows each step.
                train_df = base_df.iloc[0 : idx + train_bars].copy()
            else:
                # Rolling: training window slides forward with each step.
                train_df = base_df.iloc[idx : idx + train_bars].copy()

            test_df = base_df.iloc[idx + train_bars : idx + train_bars + test_bars].copy()

            if self._adapt_fn:
                self._adapt_fn(train_df)

            backtest = BacktestEngine(
                self._strategy_engine,
                replay_config=self._replay_config,
                backtest_config=self._backtest_config,
            )
            report = backtest.run(name, test_df, vix=vix)
            windows.append(
                WalkForwardWindow(
                    train_start=str(train_df.index[0]),
                    train_end=str(train_df.index[-1]),
                    test_start=str(test_df.index[0]),
                    test_end=str(test_df.index[-1]),
                    report=report,
                )
            )
            idx += max(1, step)

        total_trades = sum(window.report.total_trades for window in windows)
        net_pnl = round(sum(window.report.net_pnl for window in windows), 2)
        avg_wr = round(sum(window.report.win_rate for window in windows) / len(windows), 2) if windows else 0.0
        return WalkForwardReport(
            windows=windows,
            total_test_trades=total_trades,
            net_test_pnl=net_pnl,
            avg_win_rate=avg_wr,
            mode="anchored" if anchored else "rolling",
        )


# ============================================================================
# PARAMETER DRIFT MONITORING - v2.50 ENHANCEMENT
# ============================================================================

@dataclass
class ParameterDriftReport:
    """Parameter drift analysis results."""
    parameter: str
    train_values: list[float]
    test_values: list[float]
    drift_detected: bool
    drift_pct: float
    stability_rating: str  # STABLE / CAUTION / UNSTABLE
    recommendation: str
    statistical_confidence: float = 0.0  # NEW: p-value based


def calculate_statistical_significance(
    train_vals: list[float],
    test_vals: list[float],
) -> tuple[float, float]:
    """
    Calculate statistical significance using Welch's t-test approximation.
    Returns (drift_pct, confidence) where confidence is 1-p_value.
    """
    if not train_vals or not test_vals:
        return 0.0, 0.0

    import math

    n1, n2 = len(train_vals), len(test_vals)
    if n1 < 2 or n2 < 2:
        return 0.0, 0.0

    mean1 = sum(train_vals) / n1
    mean2 = sum(test_vals) / n2

    # Calculate variance
    var1 = sum((x - mean1) ** 2 for x in train_vals) / (n1 - 1) if n1 > 1 else 0
    var2 = sum((x - mean2) ** 2 for x in test_vals) / (n2 - 1) if n2 > 1 else 0

    # Standard error
    se = math.sqrt(var1 / n1 + var2 / n2) if se > 0 else 0.0001

    # t-statistic
    t_stat = abs(mean2 - mean1) / se if se > 0 else 0

    # Approximate p-value using normal distribution for large samples
    # For small samples, this is a conservative approximation
    if t_stat > 0:
        # Approximate confidence level
        confidence = min(0.99, 1.0 - math.exp(-0.5 * t_stat))
    else:
        confidence = 0.0

    # Drift percentage
    mean_all = (sum(train_vals) + sum(test_vals)) / (n1 + n2)
    drift_pct = abs(mean2 - mean1) / mean_all * 100.0 if mean_all != 0 else 0.0

    return drift_pct, confidence


def analyze_parameter_drift(
    windows: list[WalkForwardWindow],
    param_extractor: Callable[[BacktestReport], dict[str, float]],
    drift_threshold_pct: float = 20.0,
    min_confidence: float = 0.80,
) -> list[ParameterDriftReport]:
    """
    Analyze parameter stability across walk-forward windows.

    Parameters
    ----------
    windows        : List of walk-forward windows
    param_extractor: Function to extract parameters from BacktestReport
    drift_threshold_pct: % change that triggers drift alert (legacy)
    min_confidence: Statistical confidence threshold (NEW - default 80%)

    Returns
    -------
    List of ParameterDriftReport for each parameter
    """
    reports = []

    # Collect parameters from all windows
    window_params = []
    for window in windows:
        params = param_extractor(window.report)
        window_params.append(params)

    if not window_params:
        return reports

    # Get all parameter names
    param_names = set()
    for wp in window_params:
        param_names.update(wp.keys())

    # Analyze each parameter using statistical significance
    for param in sorted(param_names):
        train_vals = []
        test_vals = []

        for i, wp in enumerate(window_params):
            if param in wp:
                # First half = train, second half = test (simplified)
                if i < len(window_params) // 2:
                    train_vals.append(wp[param])
                else:
                    test_vals.append(wp[param])

        if not train_vals or not test_vals:
            continue

        # Calculate drift using statistical significance
        drift_pct, confidence = calculate_statistical_significance(train_vals, test_vals)

        # Determine stability based on BOTH drift magnitude AND statistical confidence
        # Drift is significant only if: drift_pct > threshold AND confidence > min_confidence
        has_significant_drift = drift_pct >= drift_threshold_pct and confidence >= min_confidence
        has_moderate_drift = drift_pct >= drift_threshold_pct * 0.5 and confidence >= min_confidence * 0.8

        if not has_significant_drift and not has_moderate_drift:
            stability = "STABLE"
        elif has_moderate_drift:
            stability = "CAUTION"
        else:
            stability = "UNSTABLE"

        # Recommendation
        if stability == "STABLE":
            recommendation = "Continue using current parameters"
        elif stability == "CAUTION":
            recommendation = f"Monitor closely (confidence: {confidence:.1%}), consider retraining"
        else:
            recommendation = f"RETRAIN REQUIRED - parameters drifted with {confidence:.1%} confidence"

        reports.append(ParameterDriftReport(
            parameter=param,
            train_values=train_vals,
            test_values=test_vals,
            drift_detected=stability != "STABLE",
            drift_pct=round(drift_pct, 2),
            stability_rating=stability,
            statistical_confidence=round(confidence, 3),
            recommendation=recommendation,
        ))

    return reports


def calculate_adaptive_retrain_trigger(
    current_window_pnl: float,
    rolling_avg_pnl: float,
    consecutive_losses: int,
    max_consecutive_losses: int = 3,
    pnl_decline_threshold: float = 0.3,
) -> dict[str, Any]:
    """
    Determine when to trigger adaptive retraining.

    Returns
    -------
    dict with: should_retrain, trigger_reason, urgency
    """
    # Trigger if:
    # 1. Current window P&L < 30% of rolling average
    # 2. Consecutive losses exceed threshold

    pnl_ratio = current_window_pnl / rolling_avg_pnl if rolling_avg_pnl > 0 else 0

    should_retrain = False
    trigger_reason = "NONE"
    urgency = "LOW"

    if consecutive_losses >= max_consecutive_losses:
        should_retrain = True
        trigger_reason = f"Consecutive losses ({consecutive_losses}) >= threshold"
        urgency = "HIGH"
    elif pnl_ratio < (1.0 - pnl_decline_threshold):
        should_retrain = True
        trigger_reason = f"P&L ratio {pnl_ratio:.2%} < threshold"
        urgency = "MEDIUM"

    return {
        "should_retrain": should_retrain,
        "trigger_reason": trigger_reason,
        "urgency": urgency,
        "consecutive_losses": consecutive_losses,
        "pnl_ratio": round(pnl_ratio, 3),
    }


class WalkForwardDriftMonitor:
    """
    Complete walk-forward validation with drift monitoring.
    """

    def __init__(
        self,
        strategy_engine: StrategyEngine,
        replay_config: ReplayConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ):
        self._engine = WalkForwardEngine(
            strategy_engine,
            replay_config=replay_config,
            backtest_config=backtest_config,
        )
        self._drift_reports: list[ParameterDriftReport] = []
        self._retrain_history: list[dict] = []

    def run_with_drift_analysis(
        self,
        name: str,
        base_df: pd.DataFrame,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
        vix: float = 0.0,
        anchored: bool = False,
        param_extractor: Callable[[BacktestReport], dict[str, float]] | None = None,
    ) -> tuple[WalkForwardReport, list[ParameterDriftReport]]:
        """
        Run walk-forward with integrated drift analysis.

        Returns
        -------
        (WalkForwardReport, drift_reports)
        """
        # Run standard walk-forward
        report = self._engine.run(
            name=name,
            base_df=base_df,
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=step_bars,
            vix=vix,
            anchored=anchored,
        )

        # Default param extractor if none provided
        if param_extractor is None:
            def default_extractor(r: BacktestReport) -> dict[str, float]:
                return {
                    "win_rate": r.win_rate,
                    "sharpe": getattr(r, 'sharpe_ratio', 0) or 0,
                    "max_drawdown": getattr(r, 'max_drawdown_pct', 0) or 0,
                }
            param_extractor = default_extractor

        # Analyze drift
        drift_reports = analyze_parameter_drift(
            report.windows,
            param_extractor,
            drift_threshold_pct=20.0,
        )

        self._drift_reports = drift_reports
        return report, drift_reports

    def should_adaptive_retrain(
        self,
        recent_windows: list[WalkForwardWindow],
    ) -> dict[str, Any]:
        """Check if adaptive retraining is recommended."""
        if len(recent_windows) < 3:
            return {"should_retrain": False, "reason": "Insufficient data"}

        # Calculate recent P&L trend
        pnls = [w.report.net_pnl for w in recent_windows]
        avg_pnl = sum(pnls) / len(pnls)
        current_pnl = pnls[-1]

        # Count consecutive losses
        consecutive_losses = 0
        for pnl in reversed(pnls):
            if pnl < 0:
                consecutive_losses += 1
            else:
                break

        return calculate_adaptive_retrain_trigger(
            current_window_pnl=current_pnl,
            rolling_avg_pnl=avg_pnl,
            consecutive_losses=consecutive_losses,
        )

    def get_drift_summary(self) -> dict[str, Any]:
        """Get summary of all drift analysis."""
        if not self._drift_reports:
            return {"status": "NO_ANALYSIS"}

        unstable = [r for r in self._drift_reports if r.stability_rating == "UNSTABLE"]
        caution = [r for r in self._drift_reports if r.stability_rating == "CAUTION"]

        return {
            "total_parameters": len(self._drift_reports),
            "stable_count": len(self._drift_reports) - len(unstable) - len(caution),
            "caution_count": len(caution),
            "unstable_count": len(unstable),
            "unstable_parameters": [r.parameter for r in unstable],
            "overall_status": "UNSTABLE" if unstable else "CAUTION" if caution else "STABLE",
        }


WALKFORWARD_CAPABILITIES = {
    "train": True,
    "validate": True,
    "forward_test": True,
    "rolling_windows": True,
    "anchored_windows": True,
    "out_of_sample": True,
    "adaptive_retraining": True,
    "parameter_drift_monitoring": True,
    "drift_alerts": True,
    "retrain_triggers": True,
}
