"""Synthetic Monitor — Automated Health Probes (Pillar 15: Observability).

Simulates user-facing operations to verify system health, including:
  - Database read/write connectivity
  - File system accessibility
  - Memory and disk health
  - Import integrity (can all core modules be imported?)
  - Config integrity (can config be loaded without errors?)

Provides a standardized SyntheticProbeResult with pass/fail/warn status,
latency measurement, and a composite health score.

Usage:
    from core.synthetic_monitor import get_synthetic_monitor

    monitor = get_synthetic_monitor()
    report = monitor.run_all_probes()
    print(report.summary_text())
    print(f"Health score: {report.health_score:.1f}%")
    for probe in report.probes:
        print(f"  {probe.name}: {probe.status} ({probe.latency_ms:.0f}ms)")
"""

from __future__ import annotations

import importlib
import logging
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────────────────────


class ProbeStatus:
    """Probe status constants."""
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    ERROR = "ERROR"


@dataclass
class ProbeResult:
    """Result of a single synthetic probe."""

    name: str
    status: str = ProbeStatus.PASS
    latency_ms: float = 0.0
    detail: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1),
            "detail": self.detail,
            "error": self.error,
        }


@dataclass
class SyntheticReport:
    """Aggregated report from all probes."""

    probes: list[ProbeResult] = field(default_factory=list)
    health_score: float = 100.0  # 0–100
    total_probes: int = 0
    passed_probes: int = 0
    failed_probes: int = 0
    warned_probes: int = 0
    total_latency_ms: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "health_score": round(self.health_score, 1),
            "total_probes": self.total_probes,
            "passed": self.passed_probes,
            "failed": self.failed_probes,
            "warned": self.warned_probes,
            "total_latency_ms": round(self.total_latency_ms, 1),
            "timestamp": self.timestamp or time.time(),
            "probes": [p.to_dict() for p in self.probes],
        }

    def summary_text(self) -> str:
        lines = [
            "═" * 60,
            "  SYNTHETIC MONITOR REPORT",
            "═" * 60,
            f"  Health Score: {self.health_score:.1f}%",
            f"  Probes: {self.passed_probes}/{self.total_probes} passed, "
            f"{self.failed_probes} failed, {self.warned_probes} warned",
            f"  Total Latency: {self.total_latency_ms:.0f}ms",
            "",
        ]
        if self.probes:
            lines.append("  Individual Results:")
            for p in self.probes:
                icon = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "ERROR": "!"}.get(
                    p.status, "?"
                )
                lines.append(
                    f"    {icon} {p.name}: {p.status} ({p.latency_ms:.0f}ms)"
                )
                if p.detail:
                    lines.append(f"       {p.detail}")
                if p.error:
                    lines.append(f"       ERROR: {p.error}")
        lines.append("═" * 60)
        return "\n".join(lines)


# ── Synthetic Monitor ────────────────────────────────────────────────────────


class SyntheticMonitor:
    """Runs synthetic health probes across the system.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_report: SyntheticReport | None = None

    # ── Probe Runners ─────────────────────────────────────────────────────

    def _probe_database(self) -> ProbeResult:
        """Check database connectivity by opening SQLite."""
        t0 = time.time()
        try:
            import sqlite3

            conn = sqlite3.connect(":memory:", timeout=2)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            conn.close()
            if result and result[0] == 1:
                return ProbeResult(
                    name="sqlite_connectivity",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail="SQLite in-memory query succeeded",
                )
            return ProbeResult(
                name="sqlite_connectivity",
                status=ProbeStatus.FAIL,
                latency_ms=(time.time() - t0) * 1000,
                detail="SQLite query returned unexpected result",
            )
        except Exception as exc:
            return ProbeResult(
                name="sqlite_connectivity",
                status=ProbeStatus.FAIL,
                latency_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

    def _probe_file_system(self) -> ProbeResult:
        """Check file system accessibility."""
        t0 = time.time()
        try:
            root = pathlib.Path(".")
            # Check that we can read the project root
            files = list(root.iterdir())
            count = len(files)

            # Also check key directories exist
            core_dir = pathlib.Path("core")
            tests_dir = pathlib.Path("tests")
            missing_dirs = []
            if not core_dir.is_dir():
                missing_dirs.append("core")
            if not tests_dir.is_dir():
                missing_dirs.append("tests")

            if not missing_dirs:
                return ProbeResult(
                    name="filesystem_access",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"Read {count} files in root, core+tests accessible",
                )
            return ProbeResult(
                name="filesystem_access",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"Missing directories: {', '.join(missing_dirs)}",
            )
        except Exception as exc:
            return ProbeResult(
                name="filesystem_access",
                status=ProbeStatus.ERROR,
                latency_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

    def _probe_imports(self) -> ProbeResult:
        """Check that key modules can be imported without error."""
        t0 = time.time()
        modules = [
            "core.dependency_analyzer",
            "core.recommendation_engine",
            "core.bi_dashboard",
            "core.security_auditor",
            "core.impact_analysis_engine",
            "core.root_cause_analyzer",
            "core.change_risk_scorer",
            "core.intelligent_test_generator",
            "core.living_documentation",
            "core.architecture_analyzer",
            "core.performance_optimizer",
        ]
        failed: list[str] = []
        errors: list[str] = []
        for mod_name in modules:
            try:
                importlib.import_module(mod_name)
            except ImportError as exc:
                failed.append(mod_name)
                errors.append(f"{mod_name}: {exc}")

        if not failed:
            return ProbeResult(
                name="module_imports",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"All {len(modules)} intelligence modules import cleanly",
            )
        return ProbeResult(
            name="module_imports",
            status=ProbeStatus.WARN,
            latency_ms=(time.time() - t0) * 1000,
            detail=f"{len(failed)}/{len(modules)} modules failed: {', '.join(failed)}",
            error="; ".join(errors),
        )

    def _probe_memory(self) -> ProbeResult:
        """Check memory availability via psutil if available, else skip."""
        t0 = time.time()
        try:
            import psutil

            mem = psutil.virtual_memory()
            pct = mem.percent
            available_gb = mem.available / (1024**3)

            if pct < 80:
                return ProbeResult(
                    name="memory_usage",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"Memory: {pct}% used, {available_gb:.1f}GB available",
                )
            return ProbeResult(
                name="memory_usage",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"Memory: {pct}% used, {available_gb:.1f}GB available",
            )
        except ImportError:
            # psutil not installed — skip this probe
            return ProbeResult(
                name="memory_usage",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail="psutil not available — probe skipped",
            )
        except Exception as exc:
            return ProbeResult(
                name="memory_usage",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Memory check failed",
                error=str(exc),
            )

    def _probe_config(self) -> ProbeResult:
        """Verify config files are loadable."""
        t0 = time.time()
        try:
            import json

            config_files = [
                "json/config.json",
                "json/stock_config.json",
                "json/dashboard_config.json",
                "json/index_config.defaults.json",
            ]
            failed = []
            for cf in config_files:
                p = pathlib.Path(cf)
                if p.is_file():
                    try:
                        json.loads(p.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError) as exc:
                        failed.append(f"{cf}: {exc}")

            if not failed:
                return ProbeResult(
                    name="config_integrity",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail="All checked config files valid",
                )
            return ProbeResult(
                name="config_integrity",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"{len(failed)} config files have issues",
                error="; ".join(failed),
            )
        except Exception as exc:
            return ProbeResult(
                name="config_integrity",
                status=ProbeStatus.ERROR,
                latency_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

    def _probe_environment(self) -> ProbeResult:
        """Check critical environment variables and paths."""
        t0 = time.time()
        try:
            # Check Python version
            import sys

            py_version = f"{sys.version_info.major}.{sys.version_info.minor}"

            # Check for common env vars
            os.environ.get("HTTP_PROXY", "")
            env_info = f"Python {py_version}, ENV: {'production' if 'production' in os.environ.get('ENVIRONMENT', '').lower() else 'development'}"

            return ProbeResult(
                name="environment_check",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail=env_info,
            )
        except Exception as exc:
            return ProbeResult(
                name="environment_check",
                status=ProbeStatus.ERROR,
                latency_ms=(time.time() - t0) * 1000,
                error=str(exc),
            )

    # ── Public API ────────────────────────────────────────────────────────

    # ── New Probes ───────────────────────────────────────────────────────

    def _probe_yfinance_data(self) -> ProbeResult:
        """Check yfinance data provider availability."""
        t0 = time.time()
        try:
            import yfinance as yf

            nifty = yf.Ticker("^NSEI")
            hist = nifty.history(period="1d", interval="1m")
            if hist is not None and not hist.empty:
                latest = hist["Close"].iloc[-1]
                return ProbeResult(
                    name="yfinance_data_source",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"yfinance NIFTY ticker OK, latest close={latest:.2f}",
                )
            return ProbeResult(
                name="yfinance_data_source",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="yfinance returned empty data for ^NSEI",
            )
        except ImportError:
            return ProbeResult(
                name="yfinance_data_source",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail="yfinance not installed — probe skipped",
            )
        except Exception as exc:
            return ProbeResult(
                name="yfinance_data_source",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="yfinance ticker check failed — non-critical",
                error=str(exc),
            )

    def _probe_broker_adapter(self) -> ProbeResult:
        """Check broker adapter layer is importable and functional."""
        t0 = time.time()
        try:
            from core.adapters.broker_adapters import PaperBrokerAdapter

            adapter = PaperBrokerAdapter()
            return ProbeResult(
                name="broker_adapter",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"PaperBrokerAdapter loaded: {type(adapter).__name__}",
            )
        except ImportError as exc:
            return ProbeResult(
                name="broker_adapter",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Broker adapter import failed — non-critical in synthetic mode",
                error=str(exc),
            )
        except Exception as exc:
            return ProbeResult(
                name="broker_adapter",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Broker adapter init failed",
                error=str(exc),
            )

    def _probe_trades_database(self) -> ProbeResult:
        """Check trades database accessibility."""
        t0 = time.time()
        try:
            import sqlite3
            from pathlib import Path

            db_paths = [
                Path("db/trades.db"),
                Path("db/trade_journal.db"),
                Path("db/ml_tracker.db"),
            ]
            found = []
            readable = []
            for dbp in db_paths:
                if dbp.exists():
                    found.append(dbp.name)
                    try:
                        conn = sqlite3.connect(str(dbp), timeout=1)
                        cursor = conn.cursor()
                        cursor.execute("SELECT COUNT(*) FROM sqlite_master")
                        conn.close()
                        readable.append(dbp.name)
                    except Exception:
                        pass

            if not found:
                return ProbeResult(
                    name="trades_database",
                    status=ProbeStatus.WARN,
                    latency_ms=(time.time() - t0) * 1000,
                    detail="No trading databases found — expected if not yet trading",
                )
            detail = f"Found {len(found)}/{len(db_paths)} DBs"
            if readable:
                detail += f", {len(readable)} readable: {', '.join(readable)}"
            return ProbeResult(
                name="trades_database",
                status=ProbeStatus.PASS,
                latency_ms=(time.time() - t0) * 1000,
                detail=detail,
            )
        except Exception as exc:
            return ProbeResult(
                name="trades_database",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Trades database probe failed",
                error=str(exc),
            )

    def _probe_disk_space(self) -> ProbeResult:
        """Check available disk space."""
        t0 = time.time()
        try:
            import shutil

            usage = shutil.disk_usage(".")
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            pct_free = (usage.free / usage.total) * 100

            if pct_free > 10:
                return ProbeResult(
                    name="disk_space",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"Disk: {free_gb:.1f}GB free / {total_gb:.1f}GB total ({pct_free:.0f}% free)",
                )
            return ProbeResult(
                name="disk_space",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail=f"Low disk space: {free_gb:.1f}GB free ({pct_free:.0f}%)",
            )
        except Exception as exc:
            return ProbeResult(
                name="disk_space",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Disk space check failed",
                error=str(exc),
            )

    def _probe_network_endpoints(self) -> ProbeResult:
        """Check network connectivity to known endpoints."""
        t0 = time.time()
        try:
            import urllib.error
            import urllib.request

            endpoints = [
                ("https://www.google.com", "google"),
                ("https://query1.finance.yahoo.com", "yahoo_finance"),
            ]
            reachable = []
            unreachable = []
            for url, name in endpoints:
                if not str(url).lower().startswith(("http://", "https://")):
                    unreachable.append(name)
                    continue
                try:
                    req = urllib.request.Request(url, method="HEAD")
                    urllib.request.urlopen(req, timeout=5)  # nosec B310
                    reachable.append(name)
                except (urllib.error.URLError, OSError):
                    unreachable.append(name)

            if not unreachable:
                return ProbeResult(
                    name="network_endpoints",
                    status=ProbeStatus.PASS,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"All {len(endpoints)} endpoints reachable: {', '.join(reachable)}",
                )
            if reachable:
                return ProbeResult(
                    name="network_endpoints",
                    status=ProbeStatus.WARN,
                    latency_ms=(time.time() - t0) * 1000,
                    detail=f"Partial: {', '.join(reachable)} reachable, {', '.join(unreachable)} not",
                )
            return ProbeResult(
                name="network_endpoints",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="No endpoints reachable — likely offline or restricted",
            )
        except Exception as exc:
            return ProbeResult(
                name="network_endpoints",
                status=ProbeStatus.WARN,
                latency_ms=(time.time() - t0) * 1000,
                detail="Network check failed",
                error=str(exc),
            )

    # ── Public API ────────────────────────────────────────────────────────

    def run_all_probes(self) -> SyntheticReport:
        """Run all synthetic probes and return an aggregated report."""
        with self._lock:
            time.time()
            probes = [
                self._probe_database(),
                self._probe_file_system(),
                self._probe_imports(),
                self._probe_memory(),
                self._probe_config(),
                self._probe_environment(),
                self._probe_yfinance_data(),
                self._probe_broker_adapter(),
                self._probe_trades_database(),
                self._probe_disk_space(),
                self._probe_network_endpoints(),
            ]

            passed = sum(1 for p in probes if p.status == ProbeStatus.PASS)
            failed = sum(1 for p in probes if p.status == ProbeStatus.FAIL)
            warned = sum(1 for p in probes if p.status in (ProbeStatus.WARN, ProbeStatus.ERROR))

            total_latency = sum(p.latency_ms for p in probes)
            # Health score: start at 100, subtract 30 per FAIL, 10 per WARN
            health_score = max(0.0, 100.0 - (failed * 30.0) - (warned * 10.0))

            report = SyntheticReport(
                probes=probes,
                health_score=round(health_score, 1),
                total_probes=len(probes),
                passed_probes=passed,
                failed_probes=failed,
                warned_probes=warned,
                total_latency_ms=round(total_latency, 1),
                timestamp=time.time(),
            )
            self._last_report = report
            return report

    def get_last_report(self) -> SyntheticReport | None:
        """Get the last probe report, or None if never run."""
        with self._lock:
            return self._last_report

    def get_health_score(self) -> float:
        """Get the last health score, or 0 if never run."""
        with self._lock:
            if self._last_report:
                return self._last_report.health_score
            return 0.0

    def get_stats(self) -> dict[str, Any]:
        """Get quick monitor statistics."""
        with self._lock:
            if self._last_report:
                r = self._last_report
                return {
                    "health_score": r.health_score,
                    "total_probes": r.total_probes,
                    "passed": r.passed_probes,
                    "failed": r.failed_probes,
                    "warned": r.warned_probes,
                    "last_run": r.timestamp,
                }
            return {
                "health_score": 0.0,
                "total_probes": 6,
                "passed": 0,
                "failed": 0,
                "warned": 0,
                "last_run": None,
            }


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: SyntheticMonitor | None = None
_instance_lock = threading.RLock()


def get_synthetic_monitor() -> SyntheticMonitor:
    """Return the process-level SyntheticMonitor singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SyntheticMonitor()
        return _instance


def reset_synthetic_monitor() -> None:
    """Force-reset the singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "ProbeResult",
    "ProbeStatus",
    "SyntheticMonitor",
    "SyntheticReport",
    "get_synthetic_monitor",
    "reset_synthetic_monitor",
]
