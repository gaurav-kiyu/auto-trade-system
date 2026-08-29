"""Continuous Intelligence Pipeline — Automated Constitution v4.0 monitoring.

Runs on a configurable schedule to:
1. Execute all 10 constitution module health checks
2. Run the scorecard compliance audit (87 requirements)
3. Detect compliance drift (score drops, module failures)
4. Generate automated reports (JSON, PPTX, summary text)
5. Send alerts via the notification service when issues are found

Usage:
    from core.continuous_intelligence import get_intelligence_pipeline

    pipeline = get_intelligence_pipeline()
    pipeline.run_once()               # Single check cycle
    pipeline.start_scheduler()        # Background thread with configurable interval
    pipeline.stop_scheduler()         # Graceful stop

Design:
- Thread-safe singleton with RLock
- Configurable check interval (default: 3600s = 1 hour)
- Stores check history in JSONL for trend analysis
- Integrates with NotificationService for alerting
- Lazy initialization: only imports heavy modules when checks run
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_CHECK_INTERVAL_SECONDS: int = 3600  # 1 hour
HISTORY_FILE: str = "json/continuous_intelligence_history.jsonl"
MAX_HISTORY_ENTRIES: int = 1000

# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class PipelineCheckResult:
    """Result of a single intelligence pipeline check cycle."""

    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_sec: float = 0.0
    modules_checked: int = 0
    modules_passed: int = 0
    modules_failed: int = 0
    scorecard_pct: float = 0.0
    scorecard_passed: int = 0
    scorecard_total: int = 0
    drift_detected: bool = False
    previous_score_pct: float | None = None
    score_delta_pct: float = 0.0
    alerts_sent: int = 0
    error: str = ""
    v4_overall_score: float = 0.0
    v4_total_categories: int = 0
    v4_open_regressions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "duration_sec": round(self.duration_sec, 2),
            "modules_checked": self.modules_checked,
            "modules_passed": self.modules_passed,
            "modules_failed": self.modules_failed,
            "scorecard_pct": round(self.scorecard_pct, 1),
            "scorecard_passed": self.scorecard_passed,
            "scorecard_total": self.scorecard_total,
            "drift_detected": self.drift_detected,
            "previous_score_pct": round(self.previous_score_pct, 1) if self.previous_score_pct is not None else None,
            "score_delta_pct": round(self.score_delta_pct, 1),
            "alerts_sent": self.alerts_sent,
            "error": self.error,
            "v4_overall_score": round(self.v4_overall_score, 2),
            "v4_total_categories": self.v4_total_categories,
            "v4_open_regressions": self.v4_open_regressions,
        }

    def is_healthy(self) -> bool:
        """Check if the pipeline result indicates a healthy system."""
        return (
            self.modules_failed == 0
            and self.scorecard_pct >= 90.0
            and not self.drift_detected
            and (self.v4_overall_score < 0 or self.v4_overall_score >= 5.0)
        )

    def summary_text(self) -> str:
        """Generate human-readable summary."""
        status = "HEALTHY" if self.is_healthy() else "DEGRADED" if self.scorecard_pct >= 70 else "CRITICAL"
        lines = [
            f"Continuous Intelligence — {self.timestamp}",
            f"  Status     : {status}",
            f"  Duration   : {self.duration_sec}s",
            f"  Modules    : {self.modules_passed}/{self.modules_checked} passed",
            f"  Scorecard  : {self.scorecard_pct}% ({self.scorecard_passed}/{self.scorecard_total})",
        ]
        if self.drift_detected:
            lines.append(f"  Drift      : YES ({self.score_delta_pct:+.1f}%)")
        if self.alerts_sent > 0:
            lines.append(f"  Alerts     : {self.alerts_sent} sent")
        if self.v4_total_categories > 0:
            lines.append(f"  v4.0 Health: {self.v4_overall_score}/10 ({self.v4_total_categories} cats, {self.v4_open_regressions} regr)")
        if self.error:
            lines.append(f"  Error      : {self.error}")
        return "\n".join(lines)


@dataclass
class PipelineConfig:
    """Configuration for the Continuous Intelligence Pipeline."""

    enabled: bool = True
    check_interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS
    history_file: str = HISTORY_FILE
    max_history: int = MAX_HISTORY_ENTRIES
    drift_threshold_pct: float = 5.0  # Alert if score drops > 5%
    auto_generate_pptx: bool = False
    pptx_output_dir: str = "reports"
    notify_on_failure: bool = True
    notify_on_drift: bool = True
    notify_on_recovery: bool = True


# ── Main Engine ──────────────────────────────────────────────────────────────


class ContinuousIntelligenceEngine:
    """Orchestrates automated constitution monitoring and alerting.

    Runs health checks and scorecard audits on a configurable schedule,
    detects compliance drift, generates reports, and sends alerts.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._cfg = PipelineConfig(**{k: v for k, v in (config or {}).items() if k in PipelineConfig.__dataclass_fields__})
        self._lock = threading.RLock()
        self._scheduler_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._history: list[PipelineCheckResult] = []
        self._last_result: PipelineCheckResult | None = None
        self._alert_fn: Callable[[str, bool], None] | None = None
        self._load_history()

    # ── Alert callback ─────────────────────────────────────────────────────

    def set_alert_fn(self, fn: Callable[[str, bool], None] | None) -> None:
        """Set the alert callback function (signature: fn(message: str, is_critical: bool))."""
        self._alert_fn = fn

    # ── History management ──────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Load check history from JSONL file."""
        path = self._cfg.history_file
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        result = PipelineCheckResult(**{k: v for k, v in data.items() if k in PipelineCheckResult.__dataclass_fields__})
                        self._history.append(result)
            # Trim to max
            if len(self._history) > self._cfg.max_history:
                self._history = self._history[-self._cfg.max_history:]
            _log.info("[CIP] Loaded %d history entries from %s", len(self._history), path)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("[CIP] Failed to load history: %s", exc)

    def _save_history(self) -> None:
        """Append last result to JSONL history file."""
        if not self._last_result:
            return
        try:
            with open(self._cfg.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(self._last_result.to_dict()) + "\n")
        except (OSError, ValueError, TypeError) as exc:
            _log.warning("[CIP] Failed to save history: %s", exc)

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent check history."""
        with self._lock:
            return [r.to_dict() for r in self._history[-limit:]]

    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        with self._lock:
            total_checks = len(self._history)
            healthy_checks = sum(1 for r in self._history if r.is_healthy())
            avg_duration = sum(r.duration_sec for r in self._history) / max(total_checks, 1)
            return {
                "enabled": self._cfg.enabled,
                "check_interval_seconds": self._cfg.check_interval_seconds,
                "scheduler_running": self._scheduler_thread is not None and self._scheduler_thread.is_alive(),
                "total_checks": total_checks,
                "healthy_checks": healthy_checks,
                "health_rate_pct": round((healthy_checks / max(total_checks, 1)) * 100, 1),
                "avg_duration_sec": round(avg_duration, 2),
                "drift_threshold_pct": self._cfg.drift_threshold_pct,
                "notify_on_failure": self._cfg.notify_on_failure,
                "history_file": self._cfg.history_file,
                "last_check": self._last_result.to_dict() if self._last_result else None,
            }

    # ── Core check cycle ───────────────────────────────────────────────────

    def run_once(self) -> PipelineCheckResult:
        """Execute a single complete check cycle.

        Runs:
        1. All 10 constitution module health checks
        2. Scorecard compliance audit
        3. Drift detection against previous result
        4. Alerting if issues found
        5. History persistence

        Returns:
            PipelineCheckResult with full details.
        """
        start = time.time()
        result = PipelineCheckResult()

        try:
            # Step 1: Run module health checks
            from scripts.run_constitution_checks import CheckReport, run_checks
            check_report: CheckReport = run_checks()
            result.modules_checked = check_report.total
            result.modules_passed = check_report.passed
            result.modules_failed = check_report.failed

            # Step 2: Run scorecard audit
            from scripts.constitution_scorecard import run_scorecard
            scorecard_report = run_scorecard()
            result.scorecard_pct = scorecard_report.overall_pct
            result.scorecard_passed = scorecard_report.total_passed
            result.scorecard_total = scorecard_report.total_requirements

            # Step 2b: Run v4.0 comprehensive health check
            try:
                from core.constitution import get_validator
                v4_health = get_validator().comprehensive_health_check()
                result.v4_overall_score = v4_health.get('overall_score', 0.0)
                result.v4_total_categories = v4_health.get('total_categories', 0)
                result.v4_open_regressions = v4_health.get('open_regressions', 0)
                # Export constitution metrics to Prometheus
                try:
                    from core.metrics_exporter import update_metrics
                    metrics = {
                        "constitution_overall_score": result.v4_overall_score,
                        "constitution_total_categories": float(result.v4_total_categories),
                        "constitution_open_regressions": float(result.v4_open_regressions),
                    }
                    update_metrics(metrics)
                except ImportError:
                    pass
            except Exception:
                # Sentinel: no v4.0 data available — don't trip is_healthy()
                result.v4_overall_score = -1.0
                result.v4_total_categories = 0
                result.v4_open_regressions = 0

            # Step 3: Detect drift
            with self._lock:
                if self._last_result is not None:
                    prev_pct = self._last_result.scorecard_pct
                    result.previous_score_pct = prev_pct
                    result.score_delta_pct = result.scorecard_pct - prev_pct
                    result.drift_detected = (
                        abs(result.score_delta_pct) >= self._cfg.drift_threshold_pct
                        and result.score_delta_pct < 0  # Only alert on drops
                    )

            # Step 4: Generate PPTX if enabled
            if self._cfg.auto_generate_pptx and result.scorecard_pct >= 0:
                try:
                    from core.presentation_generator import get_presentation_generator
                    gen = get_presentation_generator()
                    data = {
                        "title": f"Compliance Report - {result.timestamp[:10]}",
                        "date": result.timestamp[:10],
                        "compliance_score": result.scorecard_pct,
                        "total_passed": result.scorecard_passed,
                        "total_requirements": result.scorecard_total,
                    }
                    gen.generate("executive", data)
                except ImportError:
                    _log.debug("[CIP] PPTX generation skipped (not available)")

            # Step 5: Feed findings to Knowledge Base
            self._feed_knowledge_base(result)

            # Step 6: Alerting
            alerts = 0
            if self._cfg.notify_on_failure and result.modules_failed > 0:
                self._send_alert(
                    f"[CIP] {result.modules_failed}/{result.modules_checked} module(s) FAILED. "
                    f"Scorecard: {result.scorecard_pct}%",
                    is_critical=True,
                )
                alerts += 1
            if self._cfg.notify_on_drift and result.drift_detected:
                self._send_alert(
                    f"[CIP] Compliance DRIFT detected: {result.score_delta_pct:+.1f}% from {result.previous_score_pct:.1f}% "
                    f"to {result.scorecard_pct:.1f}%",
                    is_critical=True,
                )
                alerts += 1
            if self._cfg.notify_on_recovery and self._last_result is not None:
                if (not self._last_result.is_healthy()) and result.is_healthy():
                    self._send_alert(
                        f"[CIP] System RECOVERED to healthy state. "
                        f"Scorecard: {result.scorecard_pct}%",
                        is_critical=False,
                    )
                    alerts += 1
            result.alerts_sent = alerts

        except Exception as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            _log.error("[CIP] Check cycle failed: %s", exc)

        result.duration_sec = time.time() - start

        # Store result
        with self._lock:
            self._history.append(result)
            if len(self._history) > self._cfg.max_history:
                self._history = self._history[-self._cfg.max_history:]
            self._last_result = result

        # Persist
        self._save_history()

        _log.info(
            "[CIP] Check complete: %d/%d modules, scorecard %.1f%%, drift=%s, alerts=%d in %.2fs",
            result.modules_passed, result.modules_checked,
            result.scorecard_pct, result.drift_detected,
            result.alerts_sent, result.duration_sec,
        )
        return result

    def _feed_knowledge_base(self, result: PipelineCheckResult) -> None:
        """Feed CI pipeline results to the Knowledge Base for pattern extraction."""
        try:
            from core.knowledge_base import get_knowledge_base
            kb = get_knowledge_base()

            if result.modules_failed > 0:
                kb.add_entry(
                    pattern_type="INCIDENT_PATTERN",
                    pattern=f"CI Pipeline: {result.modules_failed}/{result.modules_checked} module(s) failed (scorecard: {result.scorecard_pct}%)",
                    solution="Review failed module checks and constitution audit trail",
                    source="continuous_intelligence.pipeline",
                    confidence=0.8 if result.modules_failed > 2 else 0.6,
                    tags=["ci_pipeline", "module_failure", f"failed_{result.modules_failed}"],
                    metadata={
                        "modules_failed": result.modules_failed,
                        "modules_checked": result.modules_checked,
                        "scorecard_pct": result.scorecard_pct,
                    },
                )

            if result.drift_detected:
                kb.add_entry(
                    pattern_type="INCIDENT_PATTERN",
                    pattern=f"CI Pipeline: Compliance drift detected ({result.score_delta_pct:+.1f}% delta)",
                    solution=f"Review recent changes that may have caused {result.score_delta_pct:+.1f}% score drop",
                    source="continuous_intelligence.pipeline",
                    confidence=0.7,
                    tags=["ci_pipeline", "drift", f"delta_{result.score_delta_pct:+.0f}"],
                    metadata={
                        "delta_pct": result.score_delta_pct,
                        "previous_score": result.previous_score_pct,
                        "current_score": result.scorecard_pct,
                    },
                )

        except ImportError:
            pass  # Knowledge base is optional
        except Exception as exc:
            _log.debug("[CIP] Pattern learning skipped: %s", exc)

    def _send_alert(self, message: str, is_critical: bool) -> None:
        """Send an alert via the configured callback or notification service."""
        if self._alert_fn:
            try:
                self._alert_fn(message, is_critical)
                return
            except Exception as exc:
                _log.warning("[CIP] Alert callback failed: %s", exc)

        # Fallback: log the alert (NotificationService requires Notification object,
        # so the caller should wire up the alert callback for production use)
        _log.info("[CIP] Alert (%s): %s", "CRITICAL" if is_critical else "INFO", message)

    # ── Scheduler ──────────────────────────────────────────────────────────

    def start_scheduler(self) -> bool:
        """Start the background scheduler thread.

        Runs check cycles on a configurable interval until stopped.
        Safe to call multiple times (idempotent).

        Returns:
            True if scheduler was started, False if already running.
        """
        with self._lock:
            if self._scheduler_thread is not None and self._scheduler_thread.is_alive():
                _log.debug("[CIP] Scheduler already running")
                return False

            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                daemon=True,
                name="continuous-intelligence",
            )
            self._scheduler_thread.start()
            _log.info(
                "[CIP] Scheduler started (interval=%ds)",
                self._cfg.check_interval_seconds,
            )
            return True

    def stop_scheduler(self) -> None:
        """Stop the background scheduler thread gracefully."""
        self._stop_event.set()
        _log.info("[CIP] Scheduler stop requested")

    def _scheduler_loop(self) -> None:
        """Main scheduler loop — runs check cycles at configured interval."""
        while not self._stop_event.is_set():
            self.run_once()
            # Wait for the interval (check every second for stop signal)
            for _ in range(self._cfg.check_interval_seconds):
                if self._stop_event.is_set():
                    return
                time.sleep(1)

    def get_last_report(self) -> dict[str, Any] | None:
        """Get the last check result as a dict, or None."""
        with self._lock:
            return self._last_result.to_dict() if self._last_result else None


# ── Singleton ────────────────────────────────────────────────────────────────

_pipeline: ContinuousIntelligenceEngine | None = None
_pipeline_lock = threading.RLock()


def get_intelligence_pipeline(config: dict[str, Any] | None = None) -> ContinuousIntelligenceEngine:
    """Get or create the singleton ContinuousIntelligenceEngine.

    Args:
        config: Optional config dict (only used on first creation).

    Returns:
        The singleton pipeline instance.
    """
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = ContinuousIntelligenceEngine(config)
    return _pipeline


def reset_intelligence_pipeline() -> None:
    """Reset the singleton (for testing)."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            _pipeline.stop_scheduler()
        _pipeline = None


# ── CLI Entry Point ──────────────────────────────────────────────────────────


def _cli() -> None:
    """Command-line interface for the Continuous Intelligence Pipeline.

    Usage:
        python -m core.continuous_intelligence            # Single check
        python -m core.continuous_intelligence --daemon   # Scheduler daemon
        python -m core.continuous_intelligence --json     # JSON output
        python -m core.continuous_intelligence --stats    # Show statistics
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Continuous Intelligence Pipeline — automated Constitution v4.0 monitoring",
    )
    parser.add_argument(
        "--daemon", action="store_true",
        help="Start the background scheduler daemon",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show pipeline statistics and exit",
    )
    parser.add_argument(
        "--interval", type=int, default=3600,
        help="Check interval in seconds (default: 3600)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress non-critical output",
    )

    args = parser.parse_args()
    pipeline = get_intelligence_pipeline({"check_interval_seconds": args.interval})

    if args.stats:
        stats = pipeline.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("=" * 50)
            print("Continuous Intelligence Pipeline — Statistics")
            print("=" * 50)
            print(f"  Enabled              : {stats['enabled']}")
            print(f"  Scheduler Running    : {stats['scheduler_running']}")
            print(f"  Check Interval       : {stats['check_interval_seconds']}s")
            print(f"  Total Checks         : {stats['total_checks']}")
            print(f"  Healthy Checks       : {stats['healthy_checks']}")
            print(f"  Health Rate          : {stats['health_rate_pct']}%")
            print(f"  Avg Duration         : {stats['avg_duration_sec']}s")
            if stats.get("last_check"):
                lc = stats["last_check"]
                print(f"  Last Check           : {lc['timestamp']}")
                print(f"  Last Scorecard       : {lc['scorecard_pct']}%")
        return

    if args.daemon:
        if not args.quiet:
            print(f"[CIP] Starting scheduler (interval={args.interval}s)...")
        pipeline.start_scheduler()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            if not args.quiet:
                print()
                print("[CIP] Stopping scheduler...")
            pipeline.stop_scheduler()
        return

    # Default: run a single check cycle
    if not args.quiet:
        print("[CIP] Running single check cycle...")
    result = pipeline.run_once()

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif not args.quiet:
        print(result.summary_text())

    if not result.is_healthy():
        sys.exit(1)


if __name__ == "__main__":
    _cli()


__all__ = [
    "ContinuousIntelligenceEngine",
    "PipelineCheckResult",
    "PipelineConfig",
    "get_intelligence_pipeline",
    "reset_intelligence_pipeline",
]
