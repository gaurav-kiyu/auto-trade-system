"""Monte Carlo Tail Risk Analysis — worst-case scenario simulation.

Extends the ``core.monte_carlo`` module with tail-risk-specific metrics:

- **CVaR** (Conditional Value at Risk): Expected loss in the worst ``alpha``% of outcomes
- **Tail Ratio**: Expected gain in best 5% / expected loss in worst 5%
- **Max Drawdown at 99th percentile**: Extreme drawdown estimate
- **Skewness & Kurtosis** of final P&L distribution: tail shape descriptors

Usage:
    from core.monte_carlo_tail_risk import run_tail_risk_simulation

    result = run_tail_risk_simulation([100, -50, 200, -30, 150])
    print(result.summary())
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from core.datetime_ist import now_ist as _now_ist


# ── Helpers ────────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Return the pct-th percentile (0-1) of a sorted list."""
    if not sorted_vals:
        return 0.0
    idx = pct * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: list[float]) -> float:
    n = len(vals)
    if n < 2:
        return 0.0
    m = _mean(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))


def _skewness(vals: list[float]) -> float:
    """Compute sample skewness of a list."""
    n = len(vals)
    if n < 3:
        return 0.0
    m = _mean(vals)
    s = _std(vals)
    if s == 0:
        return 0.0
    return (n / ((n - 1) * (n - 2))) * sum(((v - m) / s) ** 3 for v in vals)


def _kurtosis(vals: list[float]) -> float:
    """Compute excess kurtosis (Fisher) of a list."""
    n = len(vals)
    if n < 4:
        return 0.0
    m = _mean(vals)
    s = _std(vals)
    if s == 0:
        return 0.0
    numerator = (n * (n + 1)) / ((n - 1) * (n - 2) * (n - 3)) * sum(((v - m) / s) ** 4 for v in vals)
    denominator = (3 * (n - 1) ** 2) / ((n - 2) * (n - 3))
    return numerator - denominator


def _equity_curve(pnls: list[float]) -> list[float]:
    out: list[float] = []
    running = 0.0
    for p in pnls:
        running += p
        out.append(running)
    return out


def _max_drawdown(equity: list[float]) -> float:
    peak = 0.0
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = peak - v
        if dd > max_dd:
            max_dd = dd
    return max_dd


# ── Tail Risk Result ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TailRiskResult:
    """Tail risk metrics derived from Monte Carlo simulation."""

    n_simulations: int
    n_trades: int

    # Tail metrics (alpha = 0.05 by default, looking at worst 5%)
    var_95: float                    # Value at Risk at 95% (P5 final P&L)
    cvar_95: float                   # Conditional VaR: avg loss beyond VaR
    tail_ratio: float                # Mean of best 5% / abs(mean of worst 5%)
    worst_1pct: float                # 1st-percentile final P&L (worst 1%)

    # Drawdown extremes
    max_dd_median: float             # Median max drawdown
    max_dd_99: float                 # 99th-percentile max drawdown
    max_dd_absolute: float           # Absolute worst drawdown across all sims

    # Distribution shape
    skewness: float                  # Skewness of final P&L distribution
    kurtosis: float                  # Excess kurtosis of final P&L
    p5_final_pnl: float              # 5th percentile (alias for var_95)
    p1_final_pnl: float              # 1st percentile (alias for worst_1pct)

    # Worst-case consecutive losses
    worst_streak_p99: int            # 99th-percentile max consecutive losses
    worst_streak_absolute: int       # Absolute worst streak across all sims

    # Auxiliary
    final_pnls_sorted: list[float] = field(repr=False, default_factory=list)
    max_drawdowns_sorted: list[float] = field(repr=False, default_factory=list)
    worst_streaks_sorted: list[int] = field(repr=False, default_factory=list)

    def summary(self) -> str:
        """Return a compact text summary."""
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║         MONTE CARLO TAIL RISK ANALYSIS                 ║",
            f"║  {self.n_simulations:,} sims × {self.n_trades} trades                          ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  P&L Distribution                                      ║",
            f"║    P1  (worst 1%) : {self.worst_1pct:>+10,.0f}                         ║",
            f"║    P5  (VaR 95%)  : {self.var_95:>+10,.0f}                         ║",
            f"║    CVaR (avg loss): {self.cvar_95:>+10,.0f}                         ║",
            f"║    Tail Ratio     : {self.tail_ratio:>8.2f}                             ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  Drawdown Extremes                                     ║",
            f"║    Median Max DD   : {self.max_dd_median:>10,.0f}                         ║",
            f"║    99th Pctl DD    : {self.max_dd_99:>10,.0f}                         ║",
            f"║    Absolute Worst  : {self.max_dd_absolute:>10,.0f}                         ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  Distribution Shape                                    ║",
            f"║    Skewness        : {self.skewness:>+8.3f}                             ║",
            f"║    Excess Kurtosis : {self.kurtosis:>+8.3f}                             ║",
            "╠══════════════════════════════════════════════════════════╣",
            "║  Consecutive Losses                                    ║",
            f"║    99th Pctl Streak: {self.worst_streak_p99:>4}                               ║",
            f"║    Absolute Worst  : {self.worst_streak_absolute:>4}                               ║",
            "╚══════════════════════════════════════════════════════════╝",
        ]
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_simulations": self.n_simulations,
            "n_trades": self.n_trades,
            "var_95": round(self.var_95, 2),
            "cvar_95": round(self.cvar_95, 2),
            "tail_ratio": round(self.tail_ratio, 4),
            "worst_1pct": round(self.worst_1pct, 2),
            "max_dd_median": round(self.max_dd_median, 2),
            "max_dd_99": round(self.max_dd_99, 2),
            "max_dd_absolute": round(self.max_dd_absolute, 2),
            "skewness": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
            "worst_streak_p99": self.worst_streak_p99,
            "worst_streak_absolute": self.worst_streak_absolute,
            "timestamp": str(_now_ist()),
        }


# ── Core Tail Risk Simulation ─────────────────────────────────────────────

def run_tail_risk_simulation(
    pnl_list: list[float],
    *,
    n_simulations: int = 5000,
    alpha: float = 0.05,
    seed: int | None = 42,
) -> TailRiskResult:
    """Run a tail-risk-focused Monte Carlo simulation.

    Unlike ``core.monte_carlo.run_simulation`` which provides a balanced
    statistical summary, this function focuses *aggressively* on the left
    tail (worst outcomes) with more simulations and tail-specific metrics.

    Args:
        pnl_list: List of closed-trade net P&L values.
        n_simulations: Number of simulations (default 5000 — higher than
            the standard MC for better tail resolution).
        alpha: Tail threshold (default 0.05 = worst 5%).
        seed: Random seed for reproducibility.

    Returns:
        ``TailRiskResult`` with tail-specific metrics.
    """
    if not pnl_list:
        raise ValueError("pnl_list is empty — need at least 1 trade to simulate")

    n = len(pnl_list)
    rng = random.Random(seed)

    final_pnls: list[float] = []
    max_dds: list[float] = []
    streaks: list[int] = []

    for _ in range(n_simulations):
        sim = list(pnl_list)
        rng.shuffle(sim)
        eq = _equity_curve(sim)
        final_pnls.append(eq[-1])
        max_dds.append(_max_drawdown(eq))

        # Worst consecutive losing streak
        streak = 0
        max_streak = 0
        for p in sim:
            if p < 0:
                streak += 1
                if streak > max_streak:
                    max_streak = streak
            else:
                streak = 0
        streaks.append(max_streak)

    final_pnls.sort()
    max_dds.sort()
    streaks.sort()

    # VaR = P5 final P&L
    var_95 = _percentile(final_pnls, alpha)

    # CVaR = average of all outcomes worse than VaR
    tail_cutoff = int(alpha * n_simulations)
    tail_below_var = final_pnls[:max(1, tail_cutoff)]
    cvar_95 = _mean(tail_below_var)

    # Tail ratio: mean of best 5% / abs(mean of worst 5%)
    worst_5pct = final_pnls[:max(1, tail_cutoff)]
    best_5pct = final_pnls[-max(1, tail_cutoff):]
    mean_worst = abs(_mean(worst_5pct)) if _mean(worst_5pct) != 0 else 0.001
    mean_best = _mean(best_5pct)
    tail_ratio = mean_best / mean_worst if mean_worst > 0 else 0.0

    # Worst 1%
    worst_1pct_cutoff = int(0.01 * n_simulations)
    worst_1pct = _percentile(final_pnls, 0.01)

    # Drawdown extremes
    max_dd_median = _percentile(max_dds, 0.50)
    max_dd_99 = _percentile(max_dds, 0.99)
    max_dd_absolute = max_dds[-1] if max_dds else 0.0

    # Distribution shape
    sk = _skewness(final_pnls)
    ku = _kurtosis(final_pnls)

    # Streak extremes
    worst_streak_p99 = int(_percentile([float(s) for s in streaks], 0.99))
    worst_streak_absolute = streaks[-1] if streaks else 0

    return TailRiskResult(
        n_simulations=n_simulations,
        n_trades=n,
        var_95=round(var_95, 2),
        cvar_95=round(cvar_95, 2),
        tail_ratio=round(tail_ratio, 4),
        worst_1pct=round(worst_1pct, 2),
        max_dd_median=round(max_dd_median, 2),
        max_dd_99=round(max_dd_99, 2),
        max_dd_absolute=round(max_dd_absolute, 2),
        skewness=round(sk, 4),
        kurtosis=round(ku, 4),
        p5_final_pnl=round(var_95, 2),
        p1_final_pnl=round(worst_1pct, 2),
        worst_streak_p99=worst_streak_p99,
        worst_streak_absolute=worst_streak_absolute,
        final_pnls_sorted=final_pnls,
        max_drawdowns_sorted=max_dds,
        worst_streaks_sorted=streaks,
    )


# ── CLI entry point ─────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="python -m core.monte_carlo_tail_risk")
    p.add_argument("--pnls", nargs="*", type=float, default=None,
                   help="Trade P&L values (space-separated)")
    p.add_argument("--n", type=int, default=5000, help="Number of simulations")
    p.add_argument("--seed", type=int, default=42, help="Random seed")
    args = p.parse_args()

    pnls = args.pnls
    if not pnls:
        # Generate a synthetic P&L list with some losers for demonstration
        import random as _r
        _r.seed(args.seed)
        pnls = [_r.gauss(50, 150) for _ in range(40)]

    result = run_tail_risk_simulation(pnls, n_simulations=args.n, seed=args.seed)
    print()
    print(result.summary())
    print()


if __name__ == "__main__":
    _cli()
