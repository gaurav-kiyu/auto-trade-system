"""
Error Budget — SLO Error Budget Tracking and Burn Rate Alerts.

An error budget is the acceptable amount of failure (1 − SLO target).
This module tracks error budget consumption over time, computes burn
rates, and triggers alerts when the budget is being consumed too quickly.

Usage
-----
    from core.error_budget import ErrorBudget

    budget = ErrorBudget(slo_name="uptime", target=99.9, window_hours=720)
    budget.record_failure(1.0)    # 1 second of downtime
    budget.record_success(3599.0)  # 3599 seconds of uptime
    status = budget.get_status()
    print(f"Budget remaining: {status.remaining_pct:.1f}%")
    print(f"Burn rate: {status.burn_rate:.3f}x")
    print(f"At risk: {status.at_risk}")
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_log = logging.getLogger(__name__)


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class BudgetStatus:
    """Current error budget status.

    Attributes:
        slo_name: Name of the tracked SLO.
        target_pct: SLO target percentage (e.g., 99.9).
        budget_total: Total error budget in seconds.
        budget_consumed: Error budget consumed so far in seconds.
        budget_remaining: Error budget remaining in seconds.
        remaining_pct: Percentage of budget still available.
        burn_rate: Current burn rate as a multiple of ideal rate.
                   1.0 = on track, >1.0 = consuming too fast.
        at_risk: True if burn rate > 1.5 over the short window.
        window_hours: Total tracking window in hours.
        window_start: When the tracking window started.
        failures: Total failure seconds recorded.
        successes: Total success seconds recorded.
        projected_exhaustion: Estimated time until budget is exhausted.
        timestamp: Report generation time.
    """
    slo_name: str = ""
    target_pct: float = 99.9
    budget_total: float = 0.0
    budget_consumed: float = 0.0
    budget_remaining: float = 0.0
    remaining_pct: float = 100.0
    burn_rate: float = 0.0
    at_risk: bool = False
    window_hours: float = 720.0
    window_start: float = 0.0
    failures: float = 0.0
    successes: float = 0.0
    projected_exhaustion: str = "N/A"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "slo_name": self.slo_name,
            "target_pct": self.target_pct,
            "budget_total_seconds": round(self.budget_total, 1),
            "budget_consumed_seconds": round(self.budget_consumed, 1),
            "budget_remaining_seconds": round(self.budget_remaining, 1),
            "remaining_pct": round(self.remaining_pct, 2),
            "burn_rate": round(self.burn_rate, 3),
            "at_risk": self.at_risk,
            "window_hours": self.window_hours,
            "failures_seconds": round(self.failures, 1),
            "successes_seconds": round(self.successes, 1),
            "projected_exhaustion": self.projected_exhaustion,
            "timestamp": self.timestamp,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        risk_icon = "[!!]" if self.at_risk else "[OK]"
        lines = [
            "=" * 60,
            f"  Error Budget: {self.slo_name} ({self.target_pct}%)",
            "=" * 60,
            f"  Budget Window:       {self.window_hours:.0f}h",
            f"  Total Budget:        {self.budget_total:.1f}s",
            f"  Consumed:            {self.budget_consumed:.1f}s",
            f"  Remaining:           {self.budget_remaining:.1f}s ({self.remaining_pct:.1f}%)",
            f"  Failures:            {self.failures:.1f}s",
            f"  Successes:           {self.successes:.1f}s",
            "",
            f"  Burn Rate:           {self.burn_rate:.3f}x",
            f"  Status:              {risk_icon} {'AT RISK' if self.at_risk else 'Healthy'}",
            f"  Projected Exhaustion: {self.projected_exhaustion}",
            "=" * 60,
        ]
        return "\n".join(lines)


# ── Error Budget Tracker ────────────────────────────────────────────────────


class ErrorBudget:
    """Tracks error budget consumption and burn rate for a single SLO.

    Thread-safe. Uses two time windows:
      - Short window (default 1 hour) for fast burn-rate detection
      - Long window (default 30 days) for total budget tracking

    Args:
        slo_name: Name of the SLO this budget belongs to.
        target: SLO target as percentage (e.g., 99.9 for 99.9%).
        window_hours: Total budget window in hours (default 720 = 30 days).
        short_window_minutes: Fast detection window in minutes (default 60).
        alert_fn: Optional callback for alerting on burn rate breaches.
    """

    def __init__(
        self,
        slo_name: str = "",
        target: float = 99.9,
        window_hours: float = 720.0,
        short_window_minutes: float = 60.0,
        alert_fn: Any | None = None,
    ):
        self._slo_name = slo_name
        self._target = target
        self._window_hours = window_hours
        self._window_seconds = window_hours * 3600.0
        self._short_window_seconds = short_window_minutes * 60.0
        self._alert_fn = alert_fn
        self._lock = threading.RLock()
        self._start_time = time.time()
        # Rolling windows: list of (timestamp, is_failure, duration_seconds)
        self._events: list[tuple[float, bool, float]] = []
        # Cumulative counters
        self._total_failures = 0.0
        self._total_successes = 0.0
        self._last_alert_time = 0.0
        self._alert_cooldown = 3600.0  # Don't alert more than once per hour

    @property
    def slo_name(self) -> str:
        return self._slo_name

    @property
    def target(self) -> float:
        return self._target

    # ── Budget computation ─────────────────────────────────────────────────

    def _budget_total(self) -> float:
        """Total error budget in seconds."""
        elapsed = min(time.time() - self._start_time, self._window_seconds)
        allowed_failure_ratio = 1.0 - (self._target / 100.0)
        return elapsed * allowed_failure_ratio

    def _budget_consumed(self, window_seconds: float | None = None) -> float:
        """Error budget consumed in seconds within the given window."""
        cutoff = time.time() - (window_seconds or self._window_seconds)
        failures = 0.0
        now = time.time()
        with self._lock:
            # Prune old events
            self._events = [e for e in self._events if e[0] >= cutoff]
            for ts, is_failure, duration in self._events:
                if is_failure:
                    failures += duration
        return failures

    def _burn_rate(self) -> float:
        """Compute burn rate as multiple of ideal rate.

        Burn rate = (actual failures / elapsed) / (allowed failure ratio)
        1.0 = exactly on track
        >1.0 = consuming budget too fast
        """
        elapsed = min(time.time() - self._start_time, self._window_seconds)
        if elapsed < 60:  # Need at least 1 minute of data
            return 0.0
        allowed_failure_ratio = 1.0 - (self._target / 100.0)
        if allowed_failure_ratio <= 0:
            return 0.0
        failures = self._budget_consumed()
        actual_failure_ratio = failures / max(elapsed, 1.0)
        return actual_failure_ratio / allowed_failure_ratio

    def _short_window_burn_rate(self) -> float:
        """Compute burn rate over the short window."""
        cutoff = time.time() - self._short_window_seconds
        allowed_failure_ratio = 1.0 - (self._target / 100.0)
        if allowed_failure_ratio <= 0:
            return 0.0
        with self._lock:
            short_failures = sum(
                d for ts, is_fail, d in self._events
                if ts >= cutoff and is_fail
            )
        actual_ratio = short_failures / max(self._short_window_seconds, 1.0)
        return actual_ratio / allowed_failure_ratio

    # ── Recording ──────────────────────────────────────────────────────────

    def record_success(self, duration_seconds: float) -> None:
        """Record a successful (non-failure) period.

        Args:
            duration_seconds: Duration of the success period.
        """
        with self._lock:
            self._events.append((time.time(), False, duration_seconds))
            self._total_successes += duration_seconds
        self._check_alert()

    def record_failure(self, duration_seconds: float) -> None:
        """Record a failure period that consumes error budget.

        Args:
            duration_seconds: Duration of the failure in seconds.
        """
        with self._lock:
            self._events.append((time.time(), True, duration_seconds))
            self._total_failures += duration_seconds
        self._check_alert()

    def _check_alert(self) -> None:
        """Trigger alert if burn rate exceeds thresholds."""
        short_rate = self._short_window_burn_rate()
        if short_rate <= 1.5:
            return  # Below alert threshold
        now = time.time()
        if now - self._last_alert_time < self._alert_cooldown:
            return  # In cooldown

        self._last_alert_time = now
        message = (
            f"[ERROR-BUDGET] {self._slo_name}: burn rate {short_rate:.2f}x "
            f"over {self._short_window_seconds / 60:.0f}min window — "
            f"budget being consumed too quickly"
        )
        _log.warning(message)

        if self._alert_fn:
            try:
                self._alert_fn(message)
            except Exception as exc:
                _log.debug("[ERROR-BUDGET] Alert fn failed: %s", exc)

        # Cascade to SLO governance
        try:
            from core.slo_governance import record_metric
            record_metric(f"error_budget_{self._slo_name}", self.get_status().remaining_pct)
            record_metric(f"burn_rate_{self._slo_name}", short_rate)
        except ImportError:
            pass
        except Exception as exc:
            _log.debug("[ERROR-BUDGET] SLO cascade skipped: %s", exc)

    # ── Status ─────────────────────────────────────────────────────────────

    def get_status(self) -> BudgetStatus:
        """Get current error budget status."""
        now = time.time()
        budget_total = self._budget_total()
        budget_consumed = self._budget_consumed()
        budget_remaining = max(budget_total - budget_consumed, 0.0)
        # If budget window just started (total < 1ms budget), report 100% remaining
        if budget_total < 0.001:
            remaining_pct = 100.0
        else:
            remaining_pct = (budget_remaining / budget_total) * 100.0
        burn_rate = self._burn_rate()
        short_rate = self._short_window_burn_rate()
        at_risk = short_rate > 1.5 or remaining_pct < 20.0

        # Projected exhaustion
        if burn_rate > 0 and remaining_pct < 50 and budget_remaining < budget_total * 0.5:
            if burn_rate > 0.5:
                remaining_seconds = budget_remaining / (budget_consumed / max(budget_total, 1) * burn_rate) if budget_consumed > 0 else float('inf')
                # Simpler: time until exhaustion = remaining_budget / (failures_per_second)
                elapsed = now - self._start_time
                if elapsed > 0:
                    rate = budget_consumed / max(elapsed, 1)
                    if rate > 0:
                        time_to_exhaustion = budget_remaining / rate
                        hours = time_to_exhaustion / 3600
                        projection = f"{hours:.1f}h"
                    else:
                        projection = "N/A"
                else:
                    projection = "N/A"
            else:
                projection = "N/A"
        else:
            projection = "N/A"

        return BudgetStatus(
            slo_name=self._slo_name,
            target_pct=self._target,
            budget_total=budget_total,
            budget_consumed=budget_consumed,
            budget_remaining=budget_remaining,
            remaining_pct=remaining_pct,
            burn_rate=burn_rate,
            at_risk=at_risk,
            window_hours=self._window_hours,
            window_start=self._start_time,
            failures=self._total_failures,
            successes=self._total_successes,
            projected_exhaustion=projection,
        )

    # ── Utility ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Reset all tracking data."""
        with self._lock:
            self._events.clear()
            self._total_failures = 0.0
            self._total_successes = 0.0
            self._start_time = time.time()

    def merge(self, other: ErrorBudget) -> None:
        """Merge events from another ErrorBudget for the same SLO."""
        with self._lock:
            for event in other._events:
                self._events.append(event)
            self._total_failures += other._total_failures
            self._total_successes += other._total_successes


# ── Error Budget Manager (manages multiple budgets) ─────────────────────────


class ErrorBudgetManager:
    """Manages multiple ErrorBudget instances for different SLOs.

    Provides a unified interface for recording successes/failures across
    all tracked SLOs and retrieving consolidated status reports.
    """

    def __init__(self, alert_fn: Any | None = None):
        self._lock = threading.RLock()
        self._budgets: dict[str, ErrorBudget] = {}
        self._alert_fn = alert_fn

    def register_slo(
        self,
        slo_name: str,
        target: float = 99.9,
        window_hours: float = 720.0,
        short_window_minutes: float = 60.0,
    ) -> ErrorBudget:
        """Register a new SLO for error budget tracking.

        Args:
            slo_name: SLO name (e.g., "uptime", "replay_success").
            target: SLO target percentage.
            window_hours: Budget window in hours.
            short_window_minutes: Fast detection window in minutes.

        Returns:
            The ErrorBudget instance.
        """
        with self._lock:
            if slo_name in self._budgets:
                return self._budgets[slo_name]
            budget = ErrorBudget(
                slo_name=slo_name,
                target=target,
                window_hours=window_hours,
                short_window_minutes=short_window_minutes,
                alert_fn=self._alert_fn,
            )
            self._budgets[slo_name] = budget
            return budget

    def get_budget(self, slo_name: str) -> ErrorBudget | None:
        """Get the ErrorBudget for a specific SLO."""
        with self._lock:
            return self._budgets.get(slo_name)

    def record_success(self, slo_name: str, duration_seconds: float) -> None:
        """Record a success for a specific SLO."""
        budget = self.get_budget(slo_name)
        if budget:
            budget.record_success(duration_seconds)

    def record_failure(self, slo_name: str, duration_seconds: float) -> None:
        """Record a failure for a specific SLO."""
        budget = self.get_budget(slo_name)
        if budget:
            budget.record_failure(duration_seconds)

    def get_all_statuses(self) -> dict[str, BudgetStatus]:
        """Get status for all tracked SLOs."""
        with self._lock:
            return {name: budget.get_status() for name, budget in self._budgets.items()}

    def get_risk_summary(self) -> dict[str, Any]:
        """Get a summary of all budgets, flagging at-risk ones."""
        statuses = self.get_all_statuses()
        at_risk = [name for name, s in statuses.items() if s.at_risk]
        total_budget = sum(s.budget_total for s in statuses.values())
        total_consumed = sum(s.budget_consumed for s in statuses.values())
        return {
            "tracked_slos": len(statuses),
            "at_risk_count": len(at_risk),
            "at_risk_names": at_risk,
            "total_budget_seconds": round(total_budget, 1),
            "total_consumed_seconds": round(total_consumed, 1),
            "overall_remaining_pct": round(
                ((total_budget - total_consumed) / max(total_budget, 1.0)) * 100.0, 2
            ),
            "timestamp": datetime.utcnow().isoformat(),
        }

    def reset_all(self) -> None:
        """Reset all budgets."""
        with self._lock:
            for budget in self._budgets.values():
                budget.reset()


# ── Singleton ────────────────────────────────────────────────────────────────

_manager: ErrorBudgetManager | None = None
_manager_lock = threading.RLock()


def get_error_budget_manager() -> ErrorBudgetManager:
    """Get the global ErrorBudgetManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = ErrorBudgetManager()
    return _manager


def register_error_budget(
    slo_name: str,
    target: float = 99.9,
    window_hours: float = 720.0,
) -> ErrorBudget:
    """Convenience: register a new error budget."""
    return get_error_budget_manager().register_slo(slo_name, target=target, window_hours=window_hours)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.error_budget")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--register", nargs=2, metavar=("name", "target"),
                    help="Register SLO: --register uptime 99.9")
    ap.add_argument("--fail", nargs=2, metavar=("name", "seconds"),
                    help="Record failure: --fail uptime 5.0")
    ap.add_argument("--ok", nargs=2, metavar=("name", "seconds"),
                    help="Record success: --ok uptime 3600.0")
    args = ap.parse_args()

    mgr = get_error_budget_manager()

    if args.register:
        name, target = args.register
        mgr.register_slo(name, target=float(target))
        print(f"Registered: {name} ({target}%)")
        return

    if args.fail:
        name, seconds = args.fail
        mgr.record_failure(name, float(seconds))
        print(f"Recorded failure for {name}: {seconds}s")
        return

    if args.ok:
        name, seconds = args.ok
        mgr.record_success(name, float(seconds))
        print(f"Recorded success for {name}: {seconds}s")
        return

    # Default: show all statuses
    statuses = mgr.get_all_statuses()
    if args.json:
        print(json.dumps(
            {name: s.to_dict() for name, s in statuses.items()},
            indent=2,
        ))
    else:
        if not statuses:
            print("No error budgets registered. Use --register to add one.")
        for name, status in statuses.items():
            print(status.summary())
            print()

        summary = mgr.get_risk_summary()
        print(f"\n{'=' * 60}")
        print(f"  Risk Summary: {summary['at_risk_count']}/{summary['tracked_slos']} SLOs at risk")
        if summary['at_risk_names']:
            print(f"  At-risk: {', '.join(summary['at_risk_names'])}")
        print(f"  Overall budget: {summary['overall_remaining_pct']:.1f}% remaining")
        print(f"{'=' * 60}")


if __name__ == "__main__":
    _cli()
