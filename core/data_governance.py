"""Data governance — retention policies per category, cleanup scheduler, model artifact cleanup."""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    from core.retention_engine import RetentionEngine as _RetentionEngine, RetentionPolicy
except ImportError:
    _RetentionEngine = None
    # Define a minimal stub so the module can still be imported
    @dataclass
    class RetentionPolicy:  # type: ignore
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

        self._categories = [
            DataCategory(
                name="logs",
                path=logs_dir,
                glob_pattern="*.log*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_logs_max_files", 30),
                    max_age_days=self._cfg.get("data_retention_logs_days", 30),
                ),
                enabled=self._cfg.get("data_retention_logs_enabled", True),
            ),
            DataCategory(
                name="audit",
                path=logs_dir,
                glob_pattern="audit_*.jsonl*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_audit_max_files", 90),
                    max_age_days=self._cfg.get("data_retention_audit_days", 90),
                ),
                enabled=self._cfg.get("data_retention_audit_enabled", True),
            ),
            DataCategory(
                name="models",
                path=models_dir,
                glob_pattern="*.pkl*",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_models_max_files", 20),
                    max_age_days=self._cfg.get("data_retention_models_days", 180),
                ),
                enabled=self._cfg.get("data_retention_models_enabled", True),
            ),
            DataCategory(
                name="reports",
                path=reports_dir,
                glob_pattern="*.pdf",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_reports_max_files", 60),
                    max_age_days=self._cfg.get("data_retention_reports_days", 90),
                ),
                enabled=self._cfg.get("data_retention_reports_enabled", True),
            ),
            DataCategory(
                name="telemetry",
                path=data_dir,
                glob_pattern="*.csv",
                retention=RetentionPolicy(
                    max_files=self._cfg.get("data_retention_telemetry_max_files", 10),
                    max_age_days=self._cfg.get("data_retention_telemetry_days", 30),
                ),
                enabled=self._cfg.get("data_retention_telemetry_enabled", True),
            ),
        ]

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
            except Exception:
                log.exception("DataGovernor: failed to apply retention for %s", cat.name)
                results[cat.name] = -2
        return results

    def get_policy_summary(self) -> list[dict]:
        """Return human-readable policy summary for reporting/health check."""
        return [
            {
                "category": cat.name,
                "path": cat.path,
                "max_files": cat.retention.max_files,
                "max_age_days": cat.retention.max_age_days,
                "enabled": cat.enabled,
            }
            for cat in self._categories
        ]


class CleanupScheduler:
    """Background thread that runs data governance cleanup on a configurable schedule."""

    def __init__(self, governor: DataGovernor, interval_hours: int = 24) -> None:
        self._governor = governor
        self._interval_hours = interval_hours
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run_loop, name="cleanup-scheduler", daemon=True)
            self._thread.start()
        log.info("CleanupScheduler started (interval=%dh)", self._interval_hours)

    def stop(self, timeout: Optional[float] = None) -> None:
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
            except Exception:
                log.exception("CleanupScheduler: error during cleanup cycle")
            self._stop_event.wait(self._interval_hours * 3600)
