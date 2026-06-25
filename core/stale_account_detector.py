"""
Stale Account Detector - Session & Credential Staleness Monitor.

Detects three classes of account staleness:
  1. BROKER_SESSION  - Trading session expired or no activity beyond TTL
  2. CREDENTIAL      - API key/token expired or due for rotation
  3. TRADING_STATE   - No trades, no heartbeats, no activity beyond threshold

Integrates with:
  - core/services/broker_health_service.py  (broker connectivity status)
  - core/auth/session_store.py              (session TTL & active count)
  - core/telegram_queue.py                  (CRITICAL alert dispatch)
  - core/logging.py                         (structured event logging)

Usage:
    from core.stale_account_detector import StaleAccountDetector

    detector = StaleAccountDetector()
    report = detector.run_check()
    if report.stale_accounts:
        print(f"Found {len(report.stale_accounts)} stale account(s)")
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from enum import Enum
from typing import Any, Callable


from core.logging import LoggingService
from core.safety_state import trip_hard_halt as _trip_halt

log = logging.getLogger("stale_account_detector")


class StalenessCategory(Enum):
    """Categories of account staleness that can be detected."""
    BROKER_SESSION = "broker_session"
    CREDENTIAL = "credential"
    TRADING_STATE = "trading_state"
    SYSTEM_HEARTBEAT = "system_heartbeat"


@dataclass
class StaleAccountFinding:
    """Single finding from a staleness check."""

    category: StalenessCategory
    broker_name: str = ""
    detail: str = ""
    severity: str = "INFO"       # INFO / WARNING / CRITICAL
    last_activity: float = 0.0   # Unix timestamp
    stale_since: float = 0.0     # Unix timestamp
    recommendation: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "broker_name": self.broker_name,
            "detail": self.detail,
            "severity": self.severity,
            "last_activity": self.last_activity,
            "stale_since": self.stale_since,
            "recommendation": self.recommendation,
            "timestamp": self.timestamp,
        }


@dataclass
class StaleAccountReport:
    """Complete report from a staleness scan."""

    stale_accounts: list[StaleAccountFinding] = field(default_factory=list)
    healthy_accounts: list[str] = field(default_factory=list)
    scan_timestamp: float = field(default_factory=time.time)
    scan_duration_ms: float = 0.0
    total_findings: int = 0
    critical_findings: int = 0
    warning_findings: int = 0

    @property
    def has_critical(self) -> bool:
        return self.critical_findings > 0

    @property
    def has_warnings(self) -> bool:
        return self.warning_findings > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "stale_accounts": [f.to_dict() for f in self.stale_accounts],
            "healthy_accounts": self.healthy_accounts,
            "scan_timestamp": self.scan_timestamp,
            "scan_duration_ms": self.scan_duration_ms,
            "total_findings": self.total_findings,
            "critical_findings": self.critical_findings,
            "warning_findings": self.warning_findings,
        }


@dataclass
class StaleAccountConfig:
    """Configuration for stale account detection."""

    # Session staleness
    session_ttl_hours: int = 24    # Max hours without activity before stale
    session_warn_hours: int = 12   # Warn after this many hours idle
    session_block_hours: int = 48  # Block trading after this many hours idle

    # Credential staleness
    credential_max_age_days: int = 30        # Max days since token refresh
    credential_warn_days: int = 25           # Warn N days before expiry
    credential_check_enabled: bool = True

    # Trading state staleness
    trading_idle_hours: int = 72             # No trades in this period = stale
    heartbeat_max_minutes: int = 15          # Max minutes without heartbeat
    min_trades_per_day: int = 0              # Min expected trades (0 = no minimum)

    # Detection intervals
    check_interval_seconds: int = 300        # 5 minutes between routine checks
    comprehensive_check_interval: int = 3600 # Hourly comprehensive scan

    # Alerting
    enable_alerts: bool = True
    alert_on_critical: bool = True
    alert_on_recovery: bool = True


class StaleAccountDetector:
    """
    Stale Account Detector - monitors broker session, credential,
    and trading state for staleness.

    Designed as a passive monitor that checks conditions on demand
    or on a schedule, and reports findings for alerting or action.
    """

    def __init__(
        self,
        config: StaleAccountConfig | None = None,
        broker_health_service: Any | None = None,
        session_store: Any | None = None,
        alert_fn: Callable | None = None,
    ):
        """
        Args:
            config: Detection configuration
            broker_health_service: Optional BrokerHealthService instance
            session_store: Optional SessionStore instance
            alert_fn: Optional callable for dispatching alerts (e.g. telegram queue)
        """
        self.config = config or StaleAccountConfig()
        self._broker_health = broker_health_service
        self._session_store = session_store
        self._alert_fn = alert_fn

        self._lock = threading.RLock()
        self._startup_time: float = time.time()  # Startup timestamp (used for grace period)
        self._last_check: dict[str, float] = {}   # broker -> last check timestamp
        self._last_trade_time: dict[str, float] = {}  # broker -> last trade time
        self._last_heartbeat: float = 0.0
        self._detected_stale_brokers: set[str] = set()

        version = "2.53.0"
        try:
            from pathlib import Path
            _vfile = Path(__file__).resolve().parent.parent / "VERSION"
            if _vfile.exists():
                version = _vfile.read_text(encoding="utf-8").strip()
        except (OSError, IOError) as e:
            log.debug("[STALE_ACCOUNT_DETECTOR] non-critical error: %s", e)
        self._logger = LoggingService(
            log_dir="logs",
            log_filename_prefix="stale_account_",
            retain_days=30,
            json_log_file="",
            version=version,
            enable_correlation_ids=True,
            enable_contextual_logging=True,
        )

    # ── Public API ──────────────────────────────────────────────────────

    def run_check(self, comprehensive: bool = False) -> StaleAccountReport:
        """
        Run a staleness check and return a report.

        Args:
            comprehensive: If True, runs all checks including credential rotation.
                           If False, skips expensive comprehensive checks.

        Returns:
            StaleAccountReport with findings
        """
        start = time.time()
        report = StaleAccountReport()

        findings: list[StaleAccountFinding] = []

        # 1. Check broker session staleness
        findings.extend(self._check_broker_sessions())

        # 2. Check credentials (comprehensive only)
        if comprehensive and self.config.credential_check_enabled:
            findings.extend(self._check_credentials())

        # 3. Check trading state staleness
        findings.extend(self._check_trading_state())

        # 4. Check system heartbeat
        findings.extend(self._check_heartbeat())

        # Classify findings
        for f in findings:
            if f.severity == "CRITICAL":
                report.critical_findings += 1
            elif f.severity == "WARNING":
                report.warning_findings += 1

        report.stale_accounts = findings
        report.healthy_accounts = self._get_healthy_brokers(findings)
        report.scan_duration_ms = (time.time() - start) * 1000
        report.total_findings = len(findings)

        # Dispatch alerts for critical findings AND trip hard halt
        has_critical = False
        if self.config.enable_alerts and self.config.alert_on_critical:
            for f in findings:
                if f.severity == "CRITICAL":
                    has_critical = True
                    try:
                        if self._alert_fn:
                            self._alert_fn(
                                f"[STALE_ACCOUNT] {f.category.value}: {f.detail}",
                                priority="CRITICAL",
                            )
                    except (OSError, ConnectionError) as e:
                        log.warning("[STALE] Alert dispatch failed: %s", e)

        # CRITICAL: Trip hard halt on critical findings to prevent trading
        # on stale accounts. This is the centralized halting mechanism
        # referenced in the Risk Certification gap (stale account protection).
        #
        # Grace period: Skip hard halt trips during the first 30 minutes
        # after startup to avoid false positives on cold start (e.g., first
        # launch with no trade history, or during market warmup).
        if has_critical:
            startup_elapsed = time.time() - self._startup_time
            grace_period_seconds = self.config.check_interval_seconds * 6  # ~6 check cycles
            if startup_elapsed < grace_period_seconds:
                log.info(
                    "[STALE] Skipping hard halt trip during startup grace period "
                    "(%.0f/%.0f seconds elapsed)",
                    startup_elapsed, grace_period_seconds,
                )
            else:
                for f in findings:
                    if f.severity == "CRITICAL":
                        _trip_halt(
                            f"Stale account detected: [{f.category.value}] {f.detail}",
                            source="stale_account_detector.run_check",
                        )
                        break  # Only trip once

        return report

    def record_trade(self, broker_name: str = "default") -> None:
        """Record that a trade occurred (resets trading state staleness)."""
        with self._lock:
            self._last_trade_time[broker_name] = time.time()

    def record_heartbeat(self) -> None:
        """Record a system heartbeat (resets heartbeat staleness)."""
        self._last_heartbeat = time.time()

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of current staleness state."""
        with self._lock:
            now = time.time()
            return {
                "stale_brokers": list(self._detected_stale_brokers),
                "last_heartbeat_age_seconds": now - self._last_heartbeat if self._last_heartbeat else -1,
                "broker_trade_counts": {
                    k: now - v for k, v in self._last_trade_time.items()
                },
                "config": {
                    "session_ttl_hours": self.config.session_ttl_hours,
                    "credential_max_age_days": self.config.credential_max_age_days,
                    "trading_idle_hours": self.config.trading_idle_hours,
                    "check_interval_seconds": self.config.check_interval_seconds,
                },
            }

    # ── Internal Check Methods ──────────────────────────────────────────

    def _check_broker_sessions(self) -> list[StaleAccountFinding]:
        """Check broker sessions for staleness."""
        findings: list[StaleAccountFinding] = []
        now = time.time()
        session_ttl = self.config.session_ttl_hours * 3600
        session_warn = self.config.session_warn_hours * 3600
        session_block = self.config.session_block_hours * 3600

        known_brokers = ["default"]

        # If we have a broker health service, check all known brokers
        if self._broker_health:
            try:
                health = self._broker_health.get_all_brokers_health()
                known_brokers = list(health.keys())
            except (AttributeError, ValueError, OSError) as e:
                log.warning("[STALE] Could not get broker health: %s", e)

        for broker_name in known_brokers:
            last = self._last_check.get(broker_name, 0.0)
            if last == 0.0:
                # Never checked - skip, unknown is not stale
                continue
            age = now - last

            if age >= session_block:
                if broker_name not in self._detected_stale_brokers:
                    self._detected_stale_brokers.add(broker_name)
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.BROKER_SESSION,
                    broker_name=broker_name,
                    detail=(
                        f"Broker session {broker_name!r} has been idle for "
                        f"{age / 3600:.1f}h (block threshold: {self.config.session_block_hours}h). "
                        f"Trading may be blocked until session is refreshed."
                    ),
                    severity="CRITICAL",
                    last_activity=last,
                    stale_since=last + session_block,
                    recommendation=(
                        f"Re-authenticate broker {broker_name!r} by refreshing "
                        f"credentials via OPBUYING_* env vars or restart the bot."
                    ),
                ))
            elif age >= session_ttl:
                if broker_name not in self._detected_stale_brokers:
                    self._detected_stale_brokers.add(broker_name)
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.BROKER_SESSION,
                    broker_name=broker_name,
                    detail=(
                        f"Broker session {broker_name!r} stale: "
                        f"{age / 3600:.1f}h idle (TTL: {self.config.session_ttl_hours}h)."
                    ),
                    severity="WARNING",
                    last_activity=last,
                    stale_since=last + session_ttl,
                    recommendation="Refresh broker session or restart the bot.",
                ))
            elif age >= session_warn:
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.BROKER_SESSION,
                    broker_name=broker_name,
                    detail=(
                        f"Broker session {broker_name!r} approaching staleness: "
                        f"{age / 3600:.1f}h idle (warn at {self.config.session_warn_hours}h)."
                    ),
                    severity="INFO",
                    last_activity=last,
                    stale_since=last + session_warn,
                    recommendation="No action required yet, but monitor session health.",
                ))
            else:
                # Broker is healthy - remove from stale set if present
                if broker_name in self._detected_stale_brokers:
                    self._detected_stale_brokers.discard(broker_name)
                    if self.config.enable_alerts and self.config.alert_on_recovery and self._alert_fn:
                        try:
                            self._alert_fn(
                                f"[STALE_RECOVERY] Broker {broker_name!r} session recovered. "
                                f"Trading should resume normally.",
                                priority="HIGH",
                            )
                        except (OSError, ConnectionError) as e:
                            log.warning("[STALE] Recovery alert failed: %s", e)

        return findings

    def _check_credentials(self) -> list[StaleAccountFinding]:
        """Check broker credentials for staleness (comprehensive check only)."""
        findings: list[StaleAccountFinding] = []
        now = time.time()

        known_brokers = ["default"]

        if self._broker_health:
            try:
                health = self._broker_health.get_all_brokers_health()
                known_brokers = list(health.keys())
            except (AttributeError, ValueError, OSError) as e:
                log.warning("[STALE] Could not get broker health for credential check: %s", e)

        for broker_name in known_brokers:
            # Check credential age
            last_check = self._last_check.get(broker_name, 0.0)
            if last_check == 0.0:
                # Never checked - skip, unknown is not stale
                continue
            credential_age_days = (now - last_check) / 86400

            if credential_age_days >= self.config.credential_max_age_days:
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.CREDENTIAL,
                    broker_name=broker_name,
                    detail=(
                        f"Credentials for {broker_name!r} may be stale: "
                        f"{credential_age_days:.0f} days since last refresh "
                        f"(max: {self.config.credential_max_age_days} days)."
                    ),
                    severity="WARNING",
                    last_activity=last_check,
                    stale_since=last_check + (self.config.credential_max_age_days * 86400),
                    recommendation=(
                        f"Refresh {broker_name!r} credentials. Set OPBUYING_BROKER_* "
                        f"env vars with new API tokens or restart with fresh credentials."
                    ),
                ))
            elif credential_age_days >= self.config.credential_warn_days:
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.CREDENTIAL,
                    broker_name=broker_name,
                    detail=(
                        f"Credentials for {broker_name!r} nearing expiry: "
                        f"{credential_age_days:.0f} days (warn at {self.config.credential_warn_days}d, "
                        f"max: {self.config.credential_max_age_days}d)."
                    ),
                    severity="INFO",
                    last_activity=last_check,
                    stale_since=last_check + (self.config.credential_warn_days * 86400),
                    recommendation="Plan credential refresh within the next few days.",
                ))

        return findings

    def _check_trading_state(self) -> list[StaleAccountFinding]:
        """Check trading state for staleness."""
        findings: list[StaleAccountFinding] = []
        now = time.time()
        idle_threshold = self.config.trading_idle_hours * 3600

        for broker_name, last_trade in list(self._last_trade_time.items()):
            age = now - last_trade

            if age >= idle_threshold:
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.TRADING_STATE,
                    broker_name=broker_name,
                    detail=(
                        f"No trades on {broker_name!r} for {age / 3600:.1f}h "
                        f"(threshold: {self.config.trading_idle_hours}h). "
                        f"Trading state may be stale."
                    ),
                    severity="WARNING",
                    last_activity=last_trade,
                    stale_since=last_trade + idle_threshold,
                    recommendation=(
                        f"Check signal pipeline for {broker_name!r}. "
                        f"Verify data feed, market hours, and entry conditions."
                    ),
                ))

        return findings

    def _check_heartbeat(self) -> list[StaleAccountFinding]:
        """Check system heartbeat staleness."""
        findings: list[StaleAccountFinding] = []
        now = time.time()

        if self._last_heartbeat > 0:
            age_seconds = now - self._last_heartbeat
            max_heartbeat = self.config.heartbeat_max_minutes * 60

            if age_seconds >= max_heartbeat:
                findings.append(StaleAccountFinding(
                    category=StalenessCategory.SYSTEM_HEARTBEAT,
                    broker_name="system",
                    detail=(
                        f"System heartbeat stale: {age_seconds / 60:.0f} min since last heartbeat "
                        f"(max: {self.config.heartbeat_max_minutes} min). "
                        f"System may be hung or in a degraded state."
                    ),
                    severity="CRITICAL" if age_seconds >= max_heartbeat * 2 else "WARNING",
                    last_activity=self._last_heartbeat,
                    stale_since=self._last_heartbeat + max_heartbeat,
                    recommendation=(
                        "Restart the bot. If the issue persists, check logs for "
                        "deadlock, infinite loop, or resource exhaustion."
                    ),
                ))

        return findings

    def _get_healthy_brokers(self, findings: list[StaleAccountFinding]) -> list[str]:
        """Extract broker names that have no staleness findings."""
        stale_brokers: set[str] = set()
        for f in findings:
            if f.broker_name:
                stale_brokers.add(f.broker_name)

        known: list[str] = ["default", "system"]
        if self._broker_health:
            try:
                known = list(self._broker_health.get_all_brokers_health().keys()) + ["system"]
            except (AttributeError, ValueError, OSError) as e:
                log.debug("[STALE_ACCOUNT_DETECTOR] non-critical error: %s", e)

        return [b for b in known if b not in stale_brokers]


__all__ = [
    "StaleAccountConfig",
    "StaleAccountDetector",
    "StaleAccountFinding",
    "StaleAccountReport",
    "StalenessCategory",
    "log",
]

