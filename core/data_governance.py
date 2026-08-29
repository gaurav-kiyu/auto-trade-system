"""Data governance - retention policies per category, cleanup scheduler, model artifact cleanup."""

import logging
import os
import threading
from dataclasses import dataclass

__all__ = [
    "CleanupScheduler",
    "DataCategory",
    "DataGovernor",
    "log",
]

try:
    from core.retention_engine import RetentionEngine as _RetentionEngine
    from core.retention_engine import RetentionPolicy
except ImportError:
    _RetentionEngine = None
    # Define a minimal stub so the module can still be imported
    @dataclass
    class RetentionPolicy:
        max_files: int = 30
        max_age_days: int = 30

log = logging.getLogger(__name__)


@dataclass
class DataCategory:
    name: str
    path: str
    glob_pattern: str
    retention: RetentionPolicy
    enabled: bool = True


class DataGovernor:
    """Enforces retention policies per data category. Runs cleanup on demand or via scheduler."""

    def __init__(self, cfg: dict) -> None:
        if not isinstance(cfg, dict):
            cfg = {}
        self._categories: list[DataCategory] = []
        self._cfg = cfg
        self._build_categories()

    def _build_categories(self) -> None:
        logs_dir = self._cfg.get("log_dir", "logs")
        data_dir = self._cfg.get("data_dir", "data")
        models_dir = self._cfg.get("models_dir", "models")
        reports_dir = self._cfg.get("reports_dir", "reports")

        # RETENTION_ENABLED is a global emergency kill-switch (default True =
        # today's per-category behavior, unchanged). Only when an admin
        # explicitly sets it False does it force every category off,
        # overriding the per-category data_retention_*_enabled flags below.
        retention_enabled = self._cfg.get("RETENTION_ENABLED", True)

        self._categories = [
            DataCategory(
                name="logs",
                path=logs_dir,
                glob_pattern="*.log*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_logs_max_files", 30),
                    max_age_days=self._cfg.get("data_retention_logs_days", 30),
                ),
                enabled=retention_enabled and self._cfg.get("data_retention_logs_enabled", True),
            ),
            DataCategory(
                name="audit",
                path=logs_dir,
                glob_pattern="audit_*.jsonl*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_audit_max_files", 90),
                    max_age_days=self._cfg.get("data_retention_audit_days", 90),
                ),
                enabled=retention_enabled and self._cfg.get("data_retention_audit_enabled", True),
            ),
            DataCategory(
                name="models",
                path=models_dir,
                glob_pattern="*.pkl*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_models_max_files", 20),
                    max_age_days=self._cfg.get("data_retention_models_days", 180),
                ),
                enabled=retention_enabled and self._cfg.get("data_retention_models_enabled", True),
            ),
            DataCategory(
                name="reports",
                path=reports_dir,
                glob_pattern="*.pdf",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_reports_max_files", 60),
                    max_age_days=self._cfg.get("data_retention_reports_days", 90),
                ),
                enabled=retention_enabled and self._cfg.get("data_retention_reports_enabled", True),
            ),
            DataCategory(
                name="telemetry",
                path=data_dir,
                glob_pattern="*.csv",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_telemetry_max_files", 10),
                    max_age_days=self._cfg.get("data_retention_telemetry_days", 30),
                ),
                enabled=retention_enabled and self._cfg.get("data_retention_telemetry_enabled", True),
            ),
        ]

        # SQLite row-level retention for db/signals_history.db - not a
        # DataCategory since those are file-glob only and can't reach into a
        # database. Kept as separate attributes and applied in apply_all().
        self._signals_retention_days = int(self._cfg.get("data_retention_signals_days", 365))
        self._signals_retention_enabled = (
            retention_enabled and self._cfg.get("data_retention_signals_enabled", True)
        )
        self._signals_archive_dir = str(
            self._cfg.get("data_retention_signals_archive_dir", "backups/signal_archives")
        )

    def apply_all(self) -> dict[str, int]:
        """Apply all enabled retention policies.

        Returns {category_name: files_removed} with sentinel values:
            -1 = category disabled in config
             0 = no files found or directory missing
            -2 = error during retention application (logged)
        """
        if _RetentionEngine is None:
            log.warning("DataGovernor: retention_engine unavailable, skipping cleanup")
            return {cat.name: -2 for cat in self._categories}
        engine = _RetentionEngine()
        results: dict[str, int] = {}
        for cat in self._categories:
            if not cat.enabled:
                results[cat.name] = -1
                continue
            if not os.path.isdir(cat.path):
                results[cat.name] = 0
                continue
            try:
                removed = engine.apply(cat.path, [cat.glob_pattern], cat.retention)
                results[cat.name] = len(removed)
                if removed:
                    log.info("DataGovernor: removed %d files from %s (%s)", len(removed), cat.name, cat.path)
            except (OSError, ValueError, TypeError, AttributeError):
                log.exception("DataGovernor: failed to apply retention for %s", cat.name)
                results[cat.name] = -2
        results["signals_history"] = self._prune_signal_history()
        return results

    def _prune_signal_history(self) -> int:
        """Row-level counterpart to the file-glob categories above, for
        db/signals_history.db. See SignalTracker.prune_old_signals() for why
        this can't just be another DataCategory. Same sentinel convention:
        -1 = disabled, -2 = error, else = rows removed."""
        if not self._signals_retention_enabled:
            return -1
        try:
            from core.signals.signal_tracker import SignalTracker
            tracker = SignalTracker.get_instance()
            removed = tracker.prune_old_signals(self._signals_retention_days, archive_dir=self._signals_archive_dir)
            if removed:
                log.info("DataGovernor: pruned %d resolved signal(s) older than %d days",
                         removed, self._signals_retention_days)
            return removed
        except (ImportError, OSError, ValueError, TypeError, AttributeError):
            log.exception("DataGovernor: failed to prune signal history")
            return -2

    def get_policy_summary(self) -> list[dict]:
        """Return human-readable policy summary for reporting/health check."""
        summary = [
            {
                "category": cat.name,
                "path": cat.path,
                "max_files": cat.retention.max_files,
                "max_age_days": cat.retention.max_age_days,
                "enabled": cat.enabled,
            }
            for cat in self._categories
        ]
        summary.append({
            "category": "signals_history",
            "path": "db/signals_history.db",
            "max_files": None,
            "max_age_days": self._signals_retention_days,
            "enabled": self._signals_retention_enabled,
        })
        return summary


class CleanupScheduler:
    """Background thread that runs data governance cleanup on a configurable schedule."""

    def __init__(self, governor: DataGovernor, interval_hours: int = 24) -> None:
        self._governor = governor
        self._interval_hours = interval_hours
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="cleanup-scheduler", daemon=True)
            self._thread.start()
        log.info("CleanupScheduler started (interval=%dh)", self._interval_hours)

    def stop(self, timeout: float | None = None) -> None:
        """Signal the scheduler to stop and wait for the thread to finish.

        After a successful stop(), start() can be called again to restart
        the scheduler.

        Args:
            timeout: Max seconds to wait for thread completion. None = no limit.
                     If timeout elapses, the thread is not joined but the stop
                     event remains set for the next loop iteration.

        """
        self._stop_event.set()
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=timeout)
            if self._thread is None or not self._thread.is_alive():
                self._thread = None

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                results = self._governor.apply_all()
                total_removed = sum(v for v in results.values() if v > 0)
                if total_removed:
                    log.info("CleanupScheduler: removed %d files across %d categories",
                             total_removed, sum(1 for v in results.values() if v > 0))
                # Trigger EOD database WAL checkpoint and snapshot backup
                try:
                    from scripts.backup_databases import backup_databases
                    ret_days = int(self._governor._cfg.get("DB_BACKUP_RETENTION_DAYS", 7))
                    do_maint = bool(self._governor._cfg.get("DB_MAINTENANCE_ENABLED", True))
                    success, fail, _ = backup_databases(retain=ret_days, run_maint=do_maint)
                    log.info("CleanupScheduler: DB backup completed (success=%d, fail=%d, retain=%dd)", success, fail, ret_days)
                except Exception as db_err:
                    log.warning("CleanupScheduler: DB backup warning: %s", db_err)
            except (OSError, ValueError, TypeError, AttributeError):
                log.exception("CleanupScheduler: error during cleanup cycle")
            self._stop_event.wait(self._interval_hours * 3600)
