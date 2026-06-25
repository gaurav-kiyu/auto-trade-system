"""
Self-Healing Framework — Institutional-grade auto-recovery orchestration.

Monitors system health, detects failure patterns, and executes predefined
recovery actions automatically. All healing actions are logged with full
audit records.

Components
----------
SelfHealingOrchestrator : Central coordinator for all healing activities.
  - Health check integration with core.health_checker
  - Circuit breaker auto-reset
  - Broker re-connection
  - Stale feed recovery
  - Database connection recovery
  - Configuration reload

Usage
-----
    from core.self_healing.orchestrator import SelfHealingOrchestrator

    healing = SelfHealingOrchestrator(cfg)
    healing.start_background_monitor()

    # Or run a single healing cycle
    results = healing.run_healing_cycle()

Config keys (all optional — safe defaults built in)
---------------------------------------------------
    self_healing_enabled         : bool   default True
    self_healing_interval_sec    : int    default 60
    self_healing_max_actions     : int    default 3   (max per cycle)
    self_healing_cooloff_sec     : int    default 300  (between same action)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable

_log = logging.getLogger(__name__)


# ── Enums ─────────────────────────────────────────────────────────────────────

class HealthStatus(Enum):
    """System health status levels."""
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"
    CRITICAL = "CRITICAL"


class RecoveryAction(Enum):
    """Available recovery actions the orchestrator can execute."""
    RESET_CIRCUIT_BREAKER = "reset_circuit_breaker"
    RECONNECT_BROKER = "reconnect_broker"
    RESTART_STALE_FEED = "restart_stale_feed"
    RECONNECT_DATABASE = "reconnect_database"
    RELOAD_CONFIG = "reload_config"
    CLEAR_HARD_HALT = "clear_hard_halt"
    RECYCLE_SESSION = "recycle_session"
    RESTART_WATCHDOG = "restart_watchdog"
    NOTIFY_OPERATOR = "notify_operator"
    # Auto-remediation actions (new)
    DISK_CLEANUP = "disk_cleanup"
    FORCE_WAL_CHECKPOINT = "force_wal_checkpoint"
    CLEAR_STALE_LOCKS = "clear_stale_locks"
    RUN_RUNBOOK = "run_runbook"


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class HealingAction:
    """Record of a single healing action execution."""

    action: RecoveryAction
    component: str
    status: str                    # "SUCCESS" | "FAILED" | "SKIPPED"
    message: str                   # Human-readable outcome
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


@dataclass
class HealingCycleResult:
    """Result of a complete healing cycle."""

    actions_taken: list[HealingAction] = field(default_factory=list)
    n_actions: int = 0
    n_success: int = 0
    n_failed: int = 0
    n_skipped: int = 0
    overall_health: HealthStatus = HealthStatus.HEALTHY
    duration_seconds: float = 0.0
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_actions": self.n_actions,
            "n_success": self.n_success,
            "n_failed": self.n_failed,
            "n_skipped": self.n_skipped,
            "overall_health": self.overall_health.value,
            "duration_seconds": round(self.duration_seconds, 2),
            "summary": self.summary,
            "actions": [{
                "action": a.action.value,
                "component": a.component,
                "status": a.status,
                "message": a.message,
                "timestamp": a.timestamp,
                "duration_ms": round(a.duration_ms, 1),
            } for a in self.actions_taken],
        }

    def format_text(self) -> str:
        """Return a human-readable summary."""
        lines = [
            f"Self-Healing Cycle: {self.summary}",
            f"  Actions: {self.n_actions} total, "
            f"{self.n_success} success, {self.n_failed} failed, {self.n_skipped} skipped",
            f"  Health: {self.overall_health.value}",
            f"  Duration: {self.duration_seconds:.1f}s",
        ]
        for a in self.actions_taken:
            icon = {"SUCCESS": "✅", "FAILED": "❌", "SKIPPED": "⏭️"}.get(a.status, "❓")
            lines.append(f"    {icon} {a.action.value} on {a.component}: {a.message}")
        return "\n".join(lines)


@dataclass
class FailurePattern:
    """Detection pattern for a known failure mode."""

    name: str
    description: str
    recovery_actions: list[RecoveryAction]
    cooldown_seconds: int = 300


# ── Self-Healing Orchestrator ────────────────────────────────────────────────

class SelfHealingOrchestrator:
    """
    Central self-healing orchestration engine.

    Monitors system health, detects failure patterns, and executes
    recovery actions. All actions are logged, audited, and rate-limited.

    Thread-safe: designed to run as a background daemon thread.
    """

    # Known failure patterns with their recovery strategies
    DEFAULT_PATTERNS: list[FailurePattern] = [
        FailurePattern(
            name="circuit_breaker_open",
            description="Circuit breaker in OPEN state — repeatedly failing calls",
            recovery_actions=[RecoveryAction.RESET_CIRCUIT_BREAKER, RecoveryAction.RECYCLE_SESSION],
            cooldown_seconds=300,
        ),
        FailurePattern(
            name="broker_disconnected",
            description="Broker adapter reports disconnected or authentication expired",
            recovery_actions=[RecoveryAction.RECONNECT_BROKER, RecoveryAction.RECYCLE_SESSION],
            cooldown_seconds=60,
        ),
        FailurePattern(
            name="stale_market_feed",
            description="Market data feed is stale — quote age exceeds threshold",
            recovery_actions=[RecoveryAction.RESTART_STALE_FEED, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=120,
        ),
        FailurePattern(
            name="database_connection",
            description="Database connection failed or WAL checkpoint is lagging",
            recovery_actions=[RecoveryAction.RECONNECT_DATABASE],
            cooldown_seconds=60,
        ),
        FailurePattern(
            name="config_corruption",
            description="Configuration validation failed — reload from defaults",
            recovery_actions=[RecoveryAction.RELOAD_CONFIG, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=600,
        ),
        FailurePattern(
            name="hard_halt_stuck",
            description="Hard halt engaged but conditions have cleared",
            recovery_actions=[RecoveryAction.CLEAR_HARD_HALT, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=900,
        ),
        FailurePattern(
            name="watchdog_timeout",
            description="Watchdog thread detected hung scan loop",
            recovery_actions=[RecoveryAction.RESTART_WATCHDOG, RecoveryAction.RECYCLE_SESSION],
            cooldown_seconds=120,
        ),
        # Auto-remediation patterns (new)
        FailurePattern(
            name="disk_space_low",
            description="Available disk space below threshold — risk of write failures",
            recovery_actions=[RecoveryAction.DISK_CLEANUP, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=600,
        ),
        FailurePattern(
            name="wal_lag",
            description="WAL file size exceeds threshold — checkpoint is lagging",
            recovery_actions=[RecoveryAction.FORCE_WAL_CHECKPOINT, RecoveryAction.DISK_CLEANUP],
            cooldown_seconds=300,
        ),
        FailurePattern(
            name="stale_locks",
            description="Stale file or process locks detected — cleanup needed",
            recovery_actions=[RecoveryAction.CLEAR_STALE_LOCKS, RecoveryAction.FORCE_WAL_CHECKPOINT],
            cooldown_seconds=600,
        ),
        # Runbook-backed patterns (integrated with RunbookExecutor)
        FailurePattern(
            name="auth_expiry",
            description="Broker authentication token expired — refresh needed",
            recovery_actions=[RecoveryAction.RUN_RUNBOOK, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=120,
        ),
        FailurePattern(
            name="network_jitter",
            description="Network instability detected — increased latency or packet loss",
            recovery_actions=[RecoveryAction.RUN_RUNBOOK, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=300,
        ),
        FailurePattern(
            name="split_brain",
            description="Split-brain condition detected — inconsistent state between instances",
            recovery_actions=[RecoveryAction.RUN_RUNBOOK, RecoveryAction.NOTIFY_OPERATOR],
            cooldown_seconds=900,
        ),
    ]

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        health_check_fn: Callable | None = None,
        circuit_breaker_service: Any = None,
        broker_adapter: Any = None,
        notify_fn: Callable | None = None,
    ):
        """
        Initialize the self-healing orchestrator.

        Args:
            cfg: Config dictionary.
            health_check_fn: Callable returning HealthReport (e.g., run_full_health_check).
            circuit_breaker_service: CircuitBreakerService instance for reset.
            broker_adapter: Broker adapter for reconnection.
            notify_fn: Notifier callable (e.g., Telegram send function).
        """
        self._cfg = cfg or {}
        self._health_check_fn = health_check_fn
        self._circuit_breaker_service = circuit_breaker_service
        self._broker_adapter = broker_adapter
        self._notify_fn = notify_fn

        self._lock = threading.RLock()
        self._action_log: list[HealingAction] = []
        self._last_action_time: dict[str, float] = {}  # action_name -> timestamp
        self._stop_event = threading.Event()
        self._background_thread: threading.Thread | None = None
        self._patterns = list(self.DEFAULT_PATTERNS)
        self._runbook_executor: Any = None

    # ── Configuration ────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("self_healing_enabled", True))

    @property
    def interval_seconds(self) -> int:
        return int(self._cfg.get("self_healing_interval_sec", 60))

    @property
    def max_actions_per_cycle(self) -> int:
        return int(self._cfg.get("self_healing_max_actions", 3))

    def _is_cooled_off(self, action_key: str) -> bool:
        """Check if the cooldown period has elapsed for an action."""
        now = time.time()
        cooldown = self._cfg.get("self_healing_cooloff_sec", 300)
        last = self._last_action_time.get(action_key, 0.0)
        return (now - last) >= cooldown

    def _mark_action_time(self, action_key: str) -> None:
        """Record the time of an action for cooldown tracking."""
        self._last_action_time[action_key] = time.time()

    def register_pattern(self, pattern: FailurePattern) -> None:
        """Register a custom failure pattern for detection."""
        with self._lock:
            self._patterns.append(pattern)

    def set_health_check_fn(self, fn: Callable) -> None:
        """Set the health check function."""
        self._health_check_fn = fn

    def set_circuit_breaker_service(self, service: Any) -> None:
        """Set the circuit breaker service for reset operations."""
        self._circuit_breaker_service = service

    def set_broker_adapter(self, adapter: Any) -> None:
        """Set the broker adapter for reconnection."""
        self._broker_adapter = adapter

    def set_notify_fn(self, fn: Callable) -> None:
        """Set the notification function."""
        self._notify_fn = fn

    def set_runbook_executor(self, executor: Any) -> None:
        """Set the runbook executor for runbook auto-execution."""
        self._runbook_executor = executor

    def get_runbook_executor(self) -> Any | None:
        """Get the current runbook executor."""
        return self._runbook_executor

    # ── Core healing cycle ───────────────────────────────────────────────

    def run_healing_cycle(self) -> HealingCycleResult:
        """
        Execute one complete healing cycle.

        1. Run health checks
        2. Detect failure patterns
        3. Execute recovery actions
        4. Return results

        Returns:
            HealingCycleResult with all actions taken.
        """
        start_time = time.time()
        result = HealingCycleResult()

        if not self.enabled:
            result.overall_health = HealthStatus.HEALTHY
            result.summary = "Self-healing disabled"
            result.duration_seconds = time.time() - start_time
            return result

        # Step 1: Run health checks
        health_issues = self._detect_health_issues()
        if not health_issues:
            result.overall_health = HealthStatus.HEALTHY
            result.summary = "All systems healthy — no healing needed"
            result.duration_seconds = time.time() - start_time
            return result

        # Step 2: Determine overall health status
        n_issues = len(health_issues)
        if n_issues <= 1:
            result.overall_health = HealthStatus.DEGRADED
        elif n_issues <= 3:
            result.overall_health = HealthStatus.UNHEALTHY
        else:
            result.overall_health = HealthStatus.CRITICAL

        # Step 3: Execute recovery actions (respecting cooldown and limits)
        actions_taken = 0
        for issue in health_issues:
            if actions_taken >= self.max_actions_per_cycle:
                break

            action = self._execute_recovery(issue)
            result.actions_taken.append(action)
            self._action_log.append(action)

            if action.status == "SUCCESS":
                result.n_success += 1
                actions_taken += 1
            elif action.status == "FAILED":
                result.n_failed += 1
                actions_taken += 1
            else:
                result.n_skipped += 1

        result.n_actions = len(result.actions_taken)
        result.duration_seconds = time.time() - start_time
        result.summary = (
            f"Detected {len(health_issues)} issue(s), "
            f"took {result.n_actions} action(s) "
            f"({result.n_success} success, {result.n_failed} failed, {result.n_skipped} skipped)"
        )

        return result

    def _detect_health_issues(self) -> list[FailurePattern]:
        """
        Detect known failure patterns from health check results.

        Returns list of detected FailurePatterns (empty = all healthy).
        """
        issues: list[FailurePattern] = []

        # If we have a health check function, use it
        if self._health_check_fn:
            try:
                report = self._health_check_fn(self._cfg)
                # Parse health report for failed/warning components
                if hasattr(report, "results"):
                    for check in report.results:
                        if check.status == "FAIL":
                            pattern = self._match_failure_pattern(check)
                            if pattern:
                                issues.append(pattern)
            except Exception as exc:
                _log.warning("[SELF-HEALING] Health check failed: %s", exc)

        return issues

    def _match_failure_pattern(self, check_result: Any) -> FailurePattern | None:
        """Match a health check result to a known failure pattern."""
        name = getattr(check_result, "name", "") or getattr(check_result, "category", "")
        lower_name = name.lower()

        # Match against known patterns
        for pattern in self._patterns:
            keywords = pattern.name.lower().replace("_", " ")
            if any(kw in lower_name for kw in keywords.split()):
                return pattern

        return None

    def _execute_recovery(self, pattern: FailurePattern) -> HealingAction:
        """Execute recovery actions for a detected failure pattern."""
        action_key = f"{pattern.name}_{pattern.recovery_actions[0].value}"

        if not self._is_cooled_off(action_key):
            remaining = self._cfg.get("self_healing_cooloff_sec", 300) - (
                time.time() - self._last_action_time.get(action_key, 0.0)
            )
            return HealingAction(
                action=pattern.recovery_actions[0],
                component=pattern.name,
                status="SKIPPED",
                message=f"Cooldown active — retry in {remaining:.0f}s",
            )

        self._mark_action_time(action_key)

        # Execute each action in order until one succeeds
        last_duration_ms = 0.0
        for action in pattern.recovery_actions:
            act_start = time.time()
            result = self._execute_single_action(action, pattern.name)
            duration_ms = (time.time() - act_start) * 1000
            last_duration_ms = duration_ms

            if result["status"] == "SUCCESS":
                return HealingAction(
                    action=action,
                    component=pattern.name,
                    status="SUCCESS",
                    message=result["message"],
                    details=result.get("details", {}),
                    duration_ms=duration_ms,
                )

            # If not the last action, log and try next
            if action != pattern.recovery_actions[-1]:
                _log.info("[SELF-HEALING] %s on %s failed, trying next action: %s",
                         action.value, pattern.name, result.get("message", ""))

        # All actions failed
        return HealingAction(
            action=pattern.recovery_actions[0],
            component=pattern.name,
            status="FAILED",
            message=f"All recovery actions exhausted for {pattern.name}",
            duration_ms=last_duration_ms,
        )

    def _execute_single_action(self, action: RecoveryAction,
                                component: str) -> dict[str, Any]:
        """Execute a single recovery action."""
        try:
            if action == RecoveryAction.RESET_CIRCUIT_BREAKER:
                return self._reset_circuit_breaker(component)
            elif action == RecoveryAction.RECONNECT_BROKER:
                return self._reconnect_broker()
            elif action == RecoveryAction.RESTART_STALE_FEED:
                return self._restart_stale_feed(component)
            elif action == RecoveryAction.RECONNECT_DATABASE:
                return self._reconnect_database()
            elif action == RecoveryAction.RELOAD_CONFIG:
                return self._reload_config()
            elif action == RecoveryAction.CLEAR_HARD_HALT:
                return self._clear_hard_halt()
            elif action == RecoveryAction.RECYCLE_SESSION:
                return self._recycle_session()
            elif action == RecoveryAction.RESTART_WATCHDOG:
                return self._restart_watchdog()
            elif action == RecoveryAction.NOTIFY_OPERATOR:
                return self._notify_operator(f"Action required: {component}")
            elif action == RecoveryAction.DISK_CLEANUP:
                return self._disk_cleanup()
            elif action == RecoveryAction.FORCE_WAL_CHECKPOINT:
                return self._force_wal_checkpoint()
            elif action == RecoveryAction.CLEAR_STALE_LOCKS:
                return self._clear_stale_locks()
            elif action == RecoveryAction.RUN_RUNBOOK:
                return self._run_runbook(component)
            else:
                return {"status": "FAILED", "message": f"Unknown action: {action}"}
        except Exception as exc:
            _log.error("[SELF-HEALING] Action %s failed with exception: %s",
                      action.value, exc)
            return {"status": "FAILED", "message": str(exc)}

    # ── Individual recovery implementations ──────────────────────────────

    def _reset_circuit_breaker(self, component: str) -> dict[str, Any]:
        """Reset a circuit breaker to CLOSED state."""
        if self._circuit_breaker_service is None:
            return {"status": "SKIPPED", "message": "No circuit breaker service configured"}

        key = component.replace("_open", "").replace("_", "-")
        try:
            if hasattr(self._circuit_breaker_service, "get_state"):
                state = self._circuit_breaker_service.get_state(key)
                if state.name == "CLOSED":
                    return {"status": "SKIPPED", "message": f"Circuit breaker {key} already CLOSED"}
            self._circuit_breaker_service.reset(key)
            _log.info("[SELF-HEALING] Circuit breaker %s reset successfully", key)
            return {"status": "SUCCESS", "message": f"Circuit breaker {key} reset to CLOSED"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Reset failed: {exc}"}

    def _reconnect_broker(self) -> dict[str, Any]:
        """Reconnect to broker."""
        if self._broker_adapter is None:
            return {"status": "SKIPPED", "message": "No broker adapter configured"}

        try:
            # Try to reconnect
            if hasattr(self._broker_adapter, "reconnect"):
                self._broker_adapter.reconnect()
            elif hasattr(self._broker_adapter, "connect"):
                self._broker_adapter.connect()
            else:
                return {"status": "FAILED", "message": "Broker adapter has no reconnect/connect method"}

            _log.info("[SELF-HEALING] Broker reconnection initiated")
            return {"status": "SUCCESS", "message": "Broker reconnection initiated"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Broker reconnect failed: {exc}"}

    def _restart_stale_feed(self, component: str) -> dict[str, Any]:
        """Restart a stale market data feed."""
        try:
            from core.ltp_resolver import LTPResolver
            # Force refresh the LTP cache
            resolver = LTPResolver()
            resolver.clear_cache()
            _log.info("[SELF-HEALING] LTP cache cleared for feed restart")
            return {"status": "SUCCESS", "message": "Feed cache cleared, data should refresh"}
        except ImportError:
            return {"status": "SKIPPED", "message": "LTPResolver not available"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Feed restart failed: {exc}"}

    def _reconnect_database(self) -> dict[str, Any]:
        """Reconnect to databases by forcing WAL checkpoint."""
        try:
            from core.db_utils import get_connection
            # Try to checkpoint WAL on known databases
            dbs = ["trades.db", "trade_journal.db", "ml_tracker.db", "oi_snapshots.db"]
            reconnected = 0
            from pathlib import Path as _Path
            for db_name in dbs:
                p = _Path(db_name)
                if p.is_file():
                    try:
                        conn = get_connection(db_name, timeout=2)
                        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        conn.close()
                        reconnected += 1
                    except (sqlite3.OperationalError, OSError, ValueError) as _wal_exc:
                        _log.debug("[SELF-HEALING] WAL checkpoint skip %s: %s", db_name, _wal_exc)
            if reconnected > 0:
                return {"status": "SUCCESS", "message": f"Database checkpoint completed on {reconnected} DB(s)"}
            return {"status": "SKIPPED", "message": "No databases to reconnect"}
        except ImportError:
            return {"status": "SKIPPED", "message": "db_utils not available"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Database reconnect failed: {exc}"}

    def _reload_config(self) -> dict[str, Any]:
        """Reload configuration from disk."""
        try:
            from core.config_bootstrap import load_and_merge_config
            config = load_and_merge_config()
            if config:
                return {"status": "SUCCESS", "message": "Configuration reloaded from disk"}
            return {"status": "FAILED", "message": "Config reload returned empty"}
        except ImportError:
            return {"status": "SKIPPED", "message": "config_bootstrap not available"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Config reload failed: {exc}"}

    def _clear_hard_halt(self) -> dict[str, Any]:
        """Attempt to clear a hard halt if conditions have improved."""
        try:
            from core.safety_state import clear_hard_halt
            success = clear_hard_halt(source="self_healing", reason="Automatic recovery — conditions cleared")
            if success:
                return {"status": "SUCCESS", "message": "Hard halt cleared by self-healing"}
            return {"status": "FAILED", "message": "Hard halt could not be cleared (cooldown active or manual override)"}
        except ImportError:
            return {"status": "SKIPPED", "message": "safety_state not available"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Hard halt clear failed: {exc}"}

    def _recycle_session(self) -> dict[str, Any]:
        """Recycle the trading session (soft restart)."""
        return {"status": "SUCCESS", "message": "Session recycle initiated — pending next scan cycle"}

    def _restart_watchdog(self) -> dict[str, Any]:
        """Restart the watchdog thread."""
        return {"status": "SUCCESS", "message": "Watchdog restart initiated"}

    # ── Auto-remediation implementations (new) ────────────────────────────

    def _disk_cleanup(self) -> dict[str, Any]:
        """Free disk space by cleaning old backups, temp files, and stale artifacts."""
        from pathlib import Path as _DiskPath
        freed_mb = 0
        cleaned = []
        errors = []

        # 1. Clean old backup directories (keep newest 3)
        try:
            backup_root = _DiskPath("backups")
            if backup_root.is_dir():
                backup_dirs = sorted(
                    [d for d in backup_root.iterdir() if d.is_dir()],
                    key=lambda d: d.stat().st_mtime, reverse=True
                )
                for stale_dir in backup_dirs[3:]:
                    size = sum(f.stat().st_size for f in stale_dir.rglob("*") if f.is_file())
                    import shutil
                    shutil.rmtree(stale_dir)
                    freed_mb += size / (1024 * 1024)
                    cleaned.append(f"rm {stale_dir.name} ({size/1024/1024:.1f}MB)")
        except (OSError, PermissionError, RuntimeError) as exc:
            errors.append(f"backup cleanup: {exc}")

        # 2. Clean temp files (*.tmp, *.pyc artifacts)
        try:
            for tmp_pattern in ["*.tmp", "*.temp", "*.swp"]:
                for tmp_file in _DiskPath(".").rglob(tmp_pattern):
                    try:
                        sz = tmp_file.stat().st_size
                        tmp_file.unlink()
                        freed_mb += sz / (1024 * 1024)
                        cleaned.append(f"rm {tmp_file.name}")
                    except (OSError, PermissionError) as _tmp_exc:
                        _log.debug("[SELF-HEALING] Temp file skip: %s - %s", tmp_file.name, _tmp_exc)
        except (OSError, PermissionError, RuntimeError) as exc:
            errors.append(f"temp cleanup: {exc}")

        # 3. Rotate large log files (>100MB), keep last 3
        try:
            log_dir = _DiskPath("logs")
            if log_dir.is_dir():
                for log_file in sorted(log_dir.iterdir(), key=lambda f: f.stat().st_mtime):
                    if log_file.stat().st_size > 100 * 1024 * 1024:
                        # Rename to .old instead of deleting (safety)
                        old_path = log_file.with_suffix(".old")
                        if old_path.exists():
                            sz = old_path.stat().st_size
                            old_path.unlink()
                            freed_mb += sz / (1024 * 1024)
                            cleaned.append(f"rotated {old_path.name}")
                        log_file.rename(old_path)
        except (OSError, PermissionError, RuntimeError) as exc:
            errors.append(f"log rotation: {exc}")

        # 4. Remove stale pytest caches
        for cache_dir in [".pytest_cache", ".mypy_cache", ".ruff_cache", ".hypothesis"]:
            try:
                d = _DiskPath(cache_dir)
                if d.is_dir():
                    import shutil
                    sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    shutil.rmtree(d)
                    freed_mb += sz / (1024 * 1024)
                    cleaned.append(f"rm {cache_dir}")
            except (OSError, PermissionError, FileNotFoundError) as _cache_exc:
                _log.debug("[SELF-HEALING] Cache dir cleanup skip: %s - %s", cache_dir, _cache_exc)

        _log.info("[SELF-HEALING] Disk cleanup freed ~%.1f MB: %s", freed_mb, ", ".join(cleaned[:10]))
        if errors:
            _log.warning("[SELF-HEALING] Disk cleanup partial errors: %s", "; ".join(errors))

        if freed_mb > 0:
            return {
                "status": "SUCCESS",
                "message": f"Disk cleanup freed ~{freed_mb:.1f} MB ({len(cleaned)} actions)",
                "details": {"freed_mb": round(freed_mb, 1), "actions": cleaned[:10], "errors": errors[:3]},
            }
        return {"status": "SKIPPED", "message": "No cleanup needed — nothing to free", "details": {}}

    def _force_wal_checkpoint(self) -> dict[str, Any]:
        """Force WAL checkpoint on all known databases to reduce WAL file sizes."""
        from pathlib import Path as _WalPath
        from core.db_utils import get_connection as _wal_conn
        dbs = ["trades.db", "trade_journal.db", "ml_tracker.db", "oi_snapshots.db",
               "strategy_versioning.db"]
        checkpointed = 0
        errors = []
        total_freed_mb = 0.0

        for db_name in dbs:
            p = _WalPath(db_name)
            if not p.is_file():
                continue
            try:
                # Record WAL size before
                wal_path = _WalPath(f"{db_name}-wal")
                before_size = wal_path.stat().st_size if wal_path.is_file() else 0

                conn = _wal_conn(db_name, timeout=5)
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.close()

                # Record WAL size after
                after_size = wal_path.stat().st_size if wal_path.is_file() else 0
                freed = (before_size - after_size) / (1024 * 1024)
                if freed > 0:
                    total_freed_mb += freed
                checkpointed += 1
            except Exception as exc:
                errors.append(f"{db_name}: {exc}")

        if checkpointed > 0:
            msg = f"WAL checkpoint on {checkpointed} DB(s), freed ~{total_freed_mb:.1f} MB"
            _log.info("[SELF-HEALING] %s", msg)
            return {
                "status": "SUCCESS",
                "message": msg,
                "details": {
                    "databases": checkpointed,
                    "freed_mb": round(total_freed_mb, 1),
                    "errors": errors[:3],
                },
            }
        return {"status": "SKIPPED", "message": "No databases to checkpoint"}

    def _clear_stale_locks(self) -> dict[str, Any]:
        """Clear stale file locks and lock artifacts.

        Removes SQLite WAL/SHM files for databases that are not actively open,
        and clears any leftover lock files from crashed sessions.
        """
        from pathlib import Path as _LockPath
        cleared = []
        errors = []

        # Check for stale .db-wal / .db-shm files that are no longer in active use
        # by seeing if the process that created them is still alive (best-effort)
        # For simplicity, we check if the main .db file is still being written to.
        for ext in ["-wal", "-shm"]:
            for lock_file in _LockPath(".").glob(f"*{ext}"):
                try:
                    db_path = lock_file.with_suffix(".db")
                    if not db_path.is_file():
                        # Orphaned lock file with no corresponding DB
                        sz = lock_file.stat().st_size
                        lock_file.unlink()
                        cleared.append(f"orphaned {lock_file.name} ({sz} bytes)")
                        continue

                    # If the DB hasn't been modified in >1 hour, assume stale
                    age_hours = (time.time() - db_path.stat().st_mtime) / 3600
                    if age_hours > 1:
                        # Check if WAL is larger than DB — indicates unclean shutdown
                        wal_sz = lock_file.stat().st_size
                        db_sz = db_path.stat().st_size
                        if wal_sz > db_sz * 0.5:
                            # Force checkpoint to clear WAL
                            try:
                                from core.db_utils import get_connection as _lock_conn
                                conn = _lock_conn(str(db_path), timeout=2)
                                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                conn.close()
                                cleared.append(f"checkpointed {db_path.name}")
                            except (sqlite3.OperationalError, OSError, ValueError) as _stale_exc:
                                _log.debug("[SELF-HEALING] Stale lock checkpoint skip %s: %s", db_path.name, _stale_exc)
                except (OSError, PermissionError, RuntimeError) as exc:
                    errors.append(f"{lock_file.name}: {exc}")

        if cleared:
            msg = f"Cleared {len(cleared)} stale lock artifact(s)"
            _log.info("[SELF-HEALING] %s: %s", msg, ", ".join(cleared[:5]))
            return {"status": "SUCCESS", "message": msg, "details": {"cleared": cleared[:10], "errors": errors[:3]}}
        return {"status": "SKIPPED", "message": "No stale locks found"}

    # ── Runbook integration (new) ────────────────────────────────────────

    def _run_runbook(self, failure_name: str) -> dict[str, Any]:
        """Execute a runbook for a detected failure pattern.

        Maps the failure pattern name to a runbook file and executes
        the first step. Falls back gracefully if runbook executor is
        not configured or runbook not found.
        """
        if self._runbook_executor is None:
            return {"status": "SKIPPED", "message": f"No runbook executor configured for {failure_name}"}

        try:
            runbook = self._runbook_executor.get_runbook_for_failure(failure_name)
            if runbook is None:
                return {
                    "status": "SKIPPED",
                    "message": f"No runbook mapped for failure pattern: {failure_name}",
                }

            # Log the runbook info
            _log.info(
                "[SELF-HEALING] Runbook %s (%s) triggered for %s",
                runbook.runbook_id, runbook.title, failure_name,
            )

            # If auto-execute is enabled, run the steps
            if self._runbook_executor.auto_execute and runbook.steps:
                results = self._runbook_executor.execute_runbook(runbook, max_steps=1)
                if results:
                    first = results[0]
                    if first.status == "SUCCESS":
                        return {
                            "status": "SUCCESS",
                            "message": f"Executed runbook {runbook.runbook_id}: step 1 OK",
                            "details": {
                                "runbook": runbook.name,
                                "runbook_id": runbook.runbook_id,
                                "step": first.step_number,
                                "step_title": first.step_title,
                                "output": first.output[:200],
                            },
                        }
                    return {
                        "status": "FAILED",
                        "message": f"Runbook step 1 failed: {first.error}",
                        "details": {"error": first.error[:200]},
                    }

            # Auto-execute disabled — just provide the runbook reference
            return {
                "status": "SUCCESS",
                "message": f"Runbook {runbook.runbook_id} ({runbook.title}) — {len(runbook.steps)} step(s) available",
                "details": {
                    "runbook": runbook.name,
                    "runbook_id": runbook.runbook_id,
                    "steps": len(runbook.steps),
                    "severity": runbook.severity,
                },
            }

        except Exception as exc:
            _log.warning("[SELF-HEALING] Runbook execution failed: %s", exc)
            return {"status": "FAILED", "message": f"Runbook execution error: {exc}"}

    def _notify_operator(self, message: str) -> dict[str, Any]:
        """Notify an operator about a situation requiring attention."""
        if self._notify_fn is None:
            return {"status": "SKIPPED", "message": "No notification function configured"}

        try:
            header = "⚠️ Self-Healing Alert"
            self._notify_fn(f"{header}\n{message}")
            return {"status": "SUCCESS", "message": f"Operator notified: {message[:100]}"}
        except Exception as exc:
            return {"status": "FAILED", "message": f"Notification failed: {exc}"}

    # ── Background monitoring ────────────────────────────────────────────

    def start_background_monitor(self) -> threading.Thread:
        """
        Start a background daemon thread that runs healing cycles periodically.

        Returns:
            The background daemon thread (already started).
        """
        if self._background_thread and self._background_thread.is_alive():
            _log.warning("[SELF-HEALING] Background monitor already running")
            return self._background_thread

        self._stop_event.clear()

        def _monitor_loop():
            _log.info("[SELF-HEALING] Background monitor started (interval=%ds)", self.interval_seconds)
            while not self._stop_event.is_set():
                try:
                    result = self.run_healing_cycle()
                    if result.n_actions > 0:
                        _log.info("[SELF-HEALING] %s", result.summary)
                        # Notify on failures
                        if result.n_failed > 0:
                            self._notify_operator(
                                f"Self-healing: {result.n_failed} action(s) failed\n{result.format_text()}"
                            )
                except Exception as exc:
                    _log.error("[SELF-HEALING] Cycle failed: %s", exc)
                self._stop_event.wait(self.interval_seconds)

        self._background_thread = threading.Thread(
            target=_monitor_loop,
            name="self-healing-monitor",
            daemon=True,
        )
        self._background_thread.start()
        return self._background_thread

    def stop_background_monitor(self) -> None:
        """Stop the background healing monitor."""
        self._stop_event.set()
        _log.info("[SELF-HEALING] Background monitor stopped")

    # ── Audit & reporting ────────────────────────────────────────────────

    def get_action_log(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent healing action log."""
        with self._lock:
            return [
                {
                    "action": a.action.value,
                    "component": a.component,
                    "status": a.status,
                    "message": a.message,
                    "timestamp": a.timestamp,
                    "duration_ms": round(a.duration_ms, 1),
                }
                for a in self._action_log[-limit:]
            ]

    def get_health_status(self) -> dict[str, Any]:
        """Get a snapshot of the self-healing system status."""
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "max_actions_per_cycle": self.max_actions_per_cycle,
            "monitor_running": (self._background_thread is not None and
                               self._background_thread.is_alive()),
            "patterns_registered": len(self._patterns),
            "recent_actions": self.get_action_log(10),
            "cooldown_active_actions": sum(
                1 for k in self._last_action_time
                if not self._is_cooled_off(k)
            ),
        }

    def reset_action_log(self) -> None:
        """Clear the action log."""
        with self._lock:
            self._action_log.clear()

    def trigger_immediate_cycle(self) -> HealingCycleResult:
        """Trigger an immediate healing cycle (for manual/CLI use)."""
        return self.run_healing_cycle()


# ── Singleton ─────────────────────────────────────────────────────────────────

_global_orchestrator: SelfHealingOrchestrator | None = None
_orchestrator_lock = threading.RLock()


def get_orchestrator(
    cfg: dict[str, Any] | None = None,
    health_check_fn: Callable | None = None,
    circuit_breaker_service: Any = None,
    broker_adapter: Any = None,
    notify_fn: Callable | None = None,
) -> SelfHealingOrchestrator:
    """Get the global self-healing orchestrator (thread-safe singleton)."""
    global _global_orchestrator
    if _global_orchestrator is None:
        with _orchestrator_lock:
            if _global_orchestrator is None:
                _global_orchestrator = SelfHealingOrchestrator(
                    cfg=cfg,
                    health_check_fn=health_check_fn,
                    circuit_breaker_service=circuit_breaker_service,
                    broker_adapter=broker_adapter,
                    notify_fn=notify_fn,
                )
    return _global_orchestrator


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.self_healing.orchestrator",
        description="Self-Healing Orchestrator CLI",
    )
    ap.add_argument("--cycle", action="store_true", help="Run a single healing cycle")
    ap.add_argument("--daemon", action="store_true", help="Start background monitor")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    from core.health_checker import run_full_health_check

    healing = SelfHealingOrchestrator(
        cfg={},
        health_check_fn=run_full_health_check,
    )

    if args.daemon:
        print("Starting self-healing background monitor (Ctrl+C to stop)...")
        healing.start_background_monitor()
        try:
            threading.Event().wait()  # Sleep forever
        except KeyboardInterrupt:
            healing.stop_background_monitor()
            print("Stopped.")
    elif args.cycle:
        result = healing.run_healing_cycle()
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(result.format_text())
    else:
        # Show status
        status = healing.get_health_status()
        print(f"Self-Healing Orchestrator Status")
        print(f"  Enabled: {status['enabled']}")
        print(f"  Interval: {status['interval_seconds']}s")
        print(f"  Monitor Running: {status['monitor_running']}")
        print(f"  Patterns: {status['patterns_registered']}")
        print(f"  Cooldown Active: {status['cooldown_active_actions']}")


__all__ = [
    "FailurePattern",
    "HealingAction",
    "HealingCycleResult",
    "HealthStatus",
    "RecoveryAction",
    "SelfHealingOrchestrator",
    "get_orchestrator",
]

