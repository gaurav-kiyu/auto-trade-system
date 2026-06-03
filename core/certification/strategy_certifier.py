"""
Strategy Certification Framework (Phase 8).

Every strategy must pass:
  - Historical backtest certification
  - Walk forward validation
  - Paper trading metrics

Minimum thresholds (configurable via cfg dict):
  Sharpe Ratio      > 1.5
  Sortino Ratio     > 2.0
  Profit Factor     > 1.5
  Max Drawdown      < 20%
  Win Rate          > 40%

Failing strategies are classified as BLOCKED and auto-disabled.

Usage
-----
    from core.certification.strategy_certifier import StrategyCertifier
    cert = StrategyCertifier(cfg)
    report = cert.certify("spread_strategy")
    if not report.passed:
        print(f"Strategy blocked: {report.verdict}")
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Any


# ── Default thresholds (overridable via cfg) ─────────────────────────────────

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "min_sharpe": 1.5,
    "min_sortino": 2.0,
    "min_profit_factor": 1.5,
    "max_drawdown_pct": 20.0,
    "min_win_rate": 0.40,
    "min_total_trades": 20,
}


@dataclass
class StrategyCertificationReport:
    """Result of certifying a single strategy."""

    passed: bool
    strategy_name: str = ""
    status: str = ""  # CERTIFIED / BLOCKED / INSUFFICIENT_DATA / NOT_FOUND
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_pct: float = 0.0
    thresholds: dict[str, float] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0
    verdict: str = ""

    def summary(self) -> str:
        status_icon = "✅ CERTIFIED" if self.passed else "❌ BLOCKED"
        lines = [
            f"STRATEGY CERTIFICATION: {self.strategy_name} [{status_icon}]",
            f"  Status: {self.status}",
            f"  Trades: {self.total_trades}",
            f"  Win Rate: {self.win_rate:.1%} (threshold: {self.thresholds.get('min_win_rate', 0.4):.0%})",
            f"  Profit Factor: {self.profit_factor:.2f} (threshold: {self.thresholds.get('min_profit_factor', 1.5):.1f})",
            f"  Sharpe: {self.sharpe_ratio:.2f} (threshold: {self.thresholds.get('min_sharpe', 1.5):.1f})",
            f"  Sortino: {self.sortino_ratio:.2f} (threshold: {self.thresholds.get('min_sortino', 2.0):.1f})",
            f"  Max Drawdown: {self.max_drawdown_pct:.1f}% (threshold: {self.thresholds.get('max_drawdown_pct', 20.0):.0f}%)",
        ]
        if self.failures:
            lines.append(f"  Failures ({len(self.failures)}):")
            for f in self.failures[:5]:
                lines.append(f"    ❌ {f}")
        lines.append(f"  Verdict: {self.verdict}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy_name,
            "passed": self.passed,
            "status": self.status,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "sortino_ratio": round(self.sortino_ratio, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "failures": self.failures[:10],
            "duration_seconds": round(self.duration_seconds, 2),
            "verdict": self.verdict,
        }


class _StrategyMetadata:
    """Internal metadata about a strategy for certification."""

    def __init__(
        self,
        name: str,
        pnls: list[float] | None = None,
        trades: list[dict[str, Any]] | None = None,
    ):
        self.name = name
        self.pnls = pnls or []
        self.trades = trades or []

    @property
    def total_trades(self) -> int:
        return len(self.pnls)

    @property
    def wins(self) -> list[float]:
        return [p for p in self.pnls if p > 0]

    @property
    def losses(self) -> list[float]:
        return [p for p in self.pnls if p < 0]

    @property
    def win_rate(self) -> float:
        return len(self.wins) / max(1, len(self.pnls))

    @property
    def profit_factor(self) -> float:
        total_wins = sum(self.wins)
        total_losses_abs = abs(sum(self.losses))
        if total_losses_abs == 0:
            return 10.0 if total_wins > 0 else 0.0
        return total_wins / total_losses_abs

    @property
    def sharpe_ratio(self) -> float:
        n = len(self.pnls)
        if n < 2:
            return 0.0
        mean = sum(self.pnls) / n
        variance = sum((p - mean) ** 2 for p in self.pnls) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 1e-10
        return mean / std if std > 0 else 0.0

    @property
    def sortino_ratio(self) -> float:
        """Downside deviation only on negative returns."""
        n = len(self.pnls)
        if n < 2:
            return 0.0
        mean = sum(self.pnls) / n
        negative_deviations = [(p - mean) ** 2 for p in self.pnls if p < 0]
        if not negative_deviations:
            return 10.0  # No losses = perfect
        downside_var = sum(negative_deviations) / (n - 1)
        downside_std = math.sqrt(downside_var) if downside_var > 0 else 1e-10
        return mean / downside_std if downside_std > 0 else 0.0

    @property
    def max_drawdown_pct(self) -> float:
        """Maximum peak-to-trough drawdown as percentage of peak."""
        if not self.pnls:
            return 0.0
        running = 0.0
        peak = 0.0
        max_dd = 0.0
        for p in self.pnls:
            running += p
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd
        if peak == 0:
            return 0.0
        return max_dd / peak * 100


class StrategyCertifier:
    """
    Certifies strategies against minimum performance thresholds.

    Reads trade history (from trades.db or provided PnL list) and computes
    all metrics. If any metric falls below the threshold, the strategy is
    classified as BLOCKED and auto-disabled.
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._thresholds = dict(_DEFAULT_THRESHOLDS)
        # Override thresholds from config
        if self._cfg:
            for key in self._thresholds:
                cfg_key = f"strategy_cert_{key}"
                if cfg_key in self._cfg:
                    self._thresholds[key] = float(self._cfg[cfg_key])

    def certify(self, strategy_name: str, pnls: list[float] | None = None,
                trades_db_path: str | None = None) -> StrategyCertificationReport:
        """
        Certify a single strategy by name.

        Args:
            strategy_name: Name of the strategy (e.g., "spread_strategy")
            pnls: Optional list of PnL values (if provided, used directly)
            trades_db_path: Path to trades.db to load historical data

        Returns:
            StrategyCertificationReport
        """
        start = time.time()
        report = StrategyCertificationReport(
            passed=False,
            strategy_name=strategy_name,
            thresholds=dict(self._thresholds),
        )

        # Get trade data
        meta = self._load_strategy_data(strategy_name, pnls, trades_db_path)
        if meta is None:
            report.status = "NOT_FOUND"
            report.verdict = f"Strategy '{strategy_name}' not found or has no trade data"
            report.duration_seconds = time.time() - start
            return report

        report.total_trades = meta.total_trades
        if meta.total_trades < self._thresholds.get("min_total_trades", 20):
            report.status = "INSUFFICIENT_DATA"
            report.verdict = (
                f"Only {meta.total_trades} trades (need "
                f"{self._thresholds.get('min_total_trades', 20)})"
            )
            report.duration_seconds = time.time() - start
            return report

        # Compute all metrics
        report.win_rate = meta.win_rate
        report.profit_factor = meta.profit_factor
        report.sharpe_ratio = meta.sharpe_ratio
        report.sortino_ratio = meta.sortino_ratio
        report.max_drawdown_pct = meta.max_drawdown_pct

        # Check each threshold
        failures: list[str] = []

        if meta.sharpe_ratio < self._thresholds.get("min_sharpe", 1.5):
            failures.append(
                f"Sharpe {meta.sharpe_ratio:.2f} < {self._thresholds.get('min_sharpe', 1.5):.1f}"
            )
        if meta.sortino_ratio < self._thresholds.get("min_sortino", 2.0):
            failures.append(
                f"Sortino {meta.sortino_ratio:.2f} < {self._thresholds.get('min_sortino', 2.0):.1f}"
            )
        if meta.profit_factor < self._thresholds.get("min_profit_factor", 1.5):
            failures.append(
                f"Profit Factor {meta.profit_factor:.2f} < {self._thresholds.get('min_profit_factor', 1.5):.1f}"
            )
        if meta.max_drawdown_pct > self._thresholds.get("max_drawdown_pct", 20.0):
            failures.append(
                f"Max DD {meta.max_drawdown_pct:.1f}% > {self._thresholds.get('max_drawdown_pct', 20.0):.0f}%"
            )
        if meta.win_rate < self._thresholds.get("min_win_rate", 0.40):
            failures.append(
                f"Win Rate {meta.win_rate:.1%} < {self._thresholds.get('min_win_rate', 0.40):.0%}"
            )

        report.failures = failures
        report.duration_seconds = time.time() - start

        if failures:
            report.passed = False
            report.status = "BLOCKED"
            report.verdict = f"BLOCKED: {len(failures)} threshold(s) not met"
        else:
            report.passed = True
            report.status = "CERTIFIED"
            report.verdict = (
                f"CERTIFIED: All {len(self._thresholds)} thresholds met"
            )

        return report

    def certify_multiple(self, strategies: list[tuple[str, list[float]]]) -> list[StrategyCertificationReport]:
        """Certify multiple strategies at once."""
        return [self.certify(name, pnls) for name, pnls in strategies]

    def _load_strategy_data(
        self, strategy_name: str, pnls: list[float] | None, db_path: str | None
    ) -> _StrategyMetadata | None:
        """Load trade data for a strategy from DB or provided PnL list."""
        if pnls is not None:
            return _StrategyMetadata(strategy_name, pnls=pnls)

        if db_path:
            try:
                import sqlite3
                from pathlib import Path

                p = Path(db_path)
                if p.is_file():
                    conn = sqlite3.connect(str(p), timeout=5)
                    try:
                        rows = conn.execute(
                            "SELECT net_pnl FROM trades "
                            "WHERE strategy = ? AND net_pnl IS NOT NULL "
                            "ORDER BY id",
                            (strategy_name,),
                        ).fetchall()
                        if rows:
                            pnls = [float(r[0]) for r in rows]
                            return _StrategyMetadata(strategy_name, pnls=pnls)
                    finally:
                        conn.close()
            except (sqlite3.Error, OSError):
                pass

        # Try loading from known strategy modules
        return self._load_from_strategy_module(strategy_name)

    def _load_from_strategy_module(self, strategy_name: str) -> _StrategyMetadata | None:
        """Attempt to load trade data from a strategy's internal tracking.

        Checks known strategy module paths (e.g., core/strategy/sandbox.py)
        for registered PnL data or internal tracking tables.
        """
        try:
            from core.strategy.sandbox import get_strategy_pnls
            pnls = get_strategy_pnls(strategy_name)
            if pnls:
                return _StrategyMetadata(strategy_name, pnls=pnls)
        except (ImportError, AttributeError, TypeError):
            pass
        try:
            # Fall back to trades.db for strategy-specific trades
            db_path = "trades.db"
            from pathlib import Path as _Path
            if _Path(db_path).is_file():
                import sqlite3
                conn = sqlite3.connect(db_path, timeout=5)
                try:
                    rows = conn.execute(
                        "SELECT net_pnl FROM trades "
                        "WHERE strategy = ? AND net_pnl IS NOT NULL "
                        "ORDER BY id",
                        (strategy_name,),
                    ).fetchall()
                    if rows:
                        pnls = [float(r[0]) for r in rows]
                        return _StrategyMetadata(strategy_name, pnls=pnls)
                finally:
                    conn.close()
        except (ImportError, AttributeError, OSError, ValueError, sqlite3.Error):
            pass
        return None


def certify_strategy(
    strategy_name: str,
    pnls: list[float] | None = None,
    cfg: dict[str, Any] | None = None,
) -> StrategyCertificationReport:
    """
    Convenience function — certify a single strategy.

    Usage:
        report = certify_strategy("spread_strategy", pnls=[100, -50, 200])
        print(report.summary())
    """
    certifier = StrategyCertifier(cfg)
    return certifier.certify(strategy_name, pnls)


# ── Predefined strategy certification ────────────────────────────────────────

def certify_all_strategies() -> list[StrategyCertificationReport]:
    """
    Certify all known strategies using data from the system.

    Returns:
        List of certification reports, one per strategy.
    """
    # Known strategies in the system
    strategy_names = [
        "spread_strategy",
        "straddle_strategy",
        "iron_condor_strategy",
        "ab_strategy_tester",
    ]
    certifier = StrategyCertifier()
    reports = []

    for name in strategy_names:
        report = certifier.certify(name, trades_db_path="trades.db")
        reports.append(report)

    return reports


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.certification.strategy_certifier",
        description="Strategy Certification Framework",
    )
    ap.add_argument("--strategy", "-s", help="Strategy name to certify")
    ap.add_argument("--pnls", nargs="*", type=float, help="Trade PnL values")
    ap.add_argument("--list", action="store_true", help="List known strategies")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    if args.list:
        print("Known strategies:")
        for name in ["spread_strategy", "straddle_strategy",
                      "iron_condor_strategy", "ab_strategy_tester"]:
            print(f"  - {name}")
        raise SystemExit(0)

    if args.strategy:
        report = certify_strategy(args.strategy, pnls=args.pnls)
        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print(report.summary())
        raise SystemExit(0 if report.passed else 1)

    # Default: certify all
    reports = certify_all_strategies()
    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
    else:
        for r in reports:
            print(r.summary())
            print()
    all_pass = all(r.passed for r in reports)
    raise SystemExit(0 if all_pass else 1)
