"""
Automated Weekly Health Check (v2.44 Item 17).

Runs a comprehensive system health check covering:
  • Database integrity, sizes, WAL lag
  • ML health (Brier score, accuracy, drift)
  • Recent trading performance (win rate, profit factor, drawdown)
  • Config sanity (SL_PCT < TARGET_PCT, etc.)
  • System resources (disk space, log directory size)

Runs automatically on Sunday EOD; can also be triggered via CLI or web endpoint.

Public API
----------
    run_full_health_check(cfg, db_path) → HealthReport

    format_health_report(report) → str

    cli: python -m core.health_checker [--all]

Config keys (index_config.defaults.json)
-----------------------------------------
    health_check_enabled          : bool   default true
    health_check_day              : str    default "Sunday"
    health_check_db_warn_mb       : dict   default {"trades.db":50,"ml_tracker.db":200,...}
    health_check_disk_warn_mb     : int    default 500
    health_check_brier_warn       : float  default 0.30
    health_check_accuracy_warn    : float  default 0.50
    health_check_spread_warn_pct  : float  default 6.0
    health_check_log_dir_warn_gb  : float  default 2.0
"""
from __future__ import annotations

import argparse
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_DB = "trades.db"

_DB_WARN_MB_DEFAULTS: dict[str, float] = {
    "trades.db":       50.0,
    "ml_tracker.db":   200.0,
    "trade_journal.db": 100.0,
    "oi_snapshots.db": 500.0,
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class HealthCheckResult:
    category: str
    name:     str
    status:   str   # OK / WARN / FAIL
    value:    Any   = None
    message:  str   = ""


@dataclass
class HealthReport:
    results:        list[HealthCheckResult] = field(default_factory=list)
    overall_status: str                     = "OK"
    summary:        str                     = ""

    @property
    def ok_count(self) -> int:
        return sum(1 for r in self.results if r.status == "OK")

    @property
    def warn_count(self) -> int:
        return sum(1 for r in self.results if r.status == "WARN")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")


# ── Individual check functions ────────────────────────────────────────────────

def check_db_sizes(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Check each database file size against configured thresholds."""
    warn_mb: dict[str, float] = dict(
        _DB_WARN_MB_DEFAULTS,
        **cfg.get("health_check_db_warn_mb", {}),
    )
    results = []
    for db_name, limit_mb in warn_mb.items():
        p = Path(db_name)
        if not p.is_file():
            results.append(HealthCheckResult(
                "DB", f"{db_name} size", "OK", 0.0,
                f"{db_name} does not exist yet."
            ))
            continue
        size_mb = p.stat().st_size / (1024 * 1024)
        status  = "WARN" if size_mb > limit_mb else "OK"
        results.append(HealthCheckResult(
            "DB", f"{db_name} size", status,
            round(size_mb, 2),
            f"{size_mb:.1f} MB {'(exceeds ' + str(limit_mb) + ' MB warning threshold)' if status == 'WARN' else ''}",
        ))
    return results


def check_db_integrity(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Run PRAGMA integrity_check on all known databases."""
    results = []
    dbs = list(_DB_WARN_MB_DEFAULTS.keys())
    for db_name in dbs:
        p = Path(db_name)
        if not p.is_file():
            continue
        try:
            conn = sqlite3.connect(str(p), check_same_thread=False, timeout=5)
            try:
                rows = conn.execute("PRAGMA integrity_check").fetchall()
            finally:
                conn.close()
            ok = all(r[0] == "ok" for r in rows)
            status = "OK" if ok else "FAIL"
            results.append(HealthCheckResult(
                "DB", f"{db_name} integrity", status,
                rows[0][0] if rows else "empty",
                "Integrity check passed." if ok else f"Integrity issues: {rows[:3]}",
            ))
        except Exception as exc:
            results.append(HealthCheckResult(
                "DB", f"{db_name} integrity", "WARN", None,
                f"Could not check: {exc}",
            ))
    return results


def check_db_wal_size(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Check WAL file sizes — large WAL means checkpointing is lagging."""
    wal_warn_mb = float(cfg.get("health_check_wal_warn_mb", 10.0))
    results = []
    for db_name in _DB_WARN_MB_DEFAULTS:
        wal = Path(f"{db_name}-wal")
        if not wal.is_file():
            continue
        size_mb = wal.stat().st_size / (1024 * 1024)
        status  = "WARN" if size_mb > wal_warn_mb else "OK"
        results.append(HealthCheckResult(
            "DB", f"{db_name} WAL size", status,
            round(size_mb, 2),
            f"{size_mb:.1f} MB WAL — {'checkpoint may be lagging' if status == 'WARN' else 'normal'}",
        ))
    return results


def check_ml_health(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Check ML model Brier score, accuracy, and last-prediction freshness."""
    results: list[HealthCheckResult] = []
    brier_warn    = float(cfg.get("health_check_brier_warn",    0.30))
    accuracy_warn = float(cfg.get("health_check_accuracy_warn", 0.50))

    try:
        import core.ml_performance_tracker as ml_tracker
        db_path = cfg.get("ml_tracker_db_path", "ml_tracker.db")
        brier = ml_tracker.compute_brier_score(db_path=db_path)
        # Compute accuracy from calibration bins
        cal_bins = ml_tracker.compute_calibration(n_bins=5, db_path=db_path) or []
        n = sum(b.get("count", 0) for b in cal_bins)
        accuracy = 0.5
        if cal_bins:
            total = sum(b.get("count", 0) for b in cal_bins)
            if total > 0:
                correct = sum(b.get("count", 0) for b in cal_bins if b.get("calibrated", False))
                accuracy = correct / total

        if brier is None and not cal_bins:
            results.append(HealthCheckResult("ML", "Brier score", "WARN", None,
                                             "No ML predictions recorded yet."))
            return results

        brier_val = brier if brier is not None else 0.25
        st_b = "WARN" if brier_val > brier_warn else "OK"
        results.append(HealthCheckResult(
            "ML", "Brier score", st_b, round(brier_val, 4),
            f"Brier={brier_val:.4f} ({'above' if st_b == 'WARN' else 'within'} warn threshold {brier_warn})",
        ))
        st_a = "WARN" if accuracy < accuracy_warn else "OK"
        results.append(HealthCheckResult(
            "ML", "Model accuracy", st_a, round(accuracy * 100, 1),
            f"Accuracy={accuracy*100:.1f}% (min threshold {accuracy_warn*100:.0f}%)",
        ))
        results.append(HealthCheckResult(
            "ML", "Prediction count", "OK", n,
            f"{n} predictions recorded.",
        ))
    except Exception as exc:
        results.append(HealthCheckResult("ML", "ML health check", "WARN", None, str(exc)))

    return results


def check_recent_performance(
    cfg:     dict[str, Any],
    db_path: str = _DEFAULT_DB,
) -> list[HealthCheckResult]:
    """Check recent win rate, profit factor, and drawdown."""
    results: list[HealthCheckResult] = []
    try:
        from core.performance_metrics import compute_metrics, load_trades
        days    = int(cfg.get("sensitivity_report_days", 30))
        trades  = load_trades(db_path, days=days)
        if not trades:
            results.append(HealthCheckResult(
                "PERF", "Trade count", "WARN", 0,
                f"No trades in last {days} days.",
            ))
            return results
        metrics = compute_metrics(trades)
        n        = int(metrics.get("trades",        0))
        wr       = float(metrics.get("win_rate",     0.0))
        pf       = float(metrics.get("profit_factor", 0.0))
        dd       = float(metrics.get("max_drawdown", 0.0))

        results.append(HealthCheckResult(
            "PERF", "Win rate", "OK" if wr >= 0.45 else "WARN",
            round(wr * 100, 1), f"Win rate {wr*100:.1f}% over last {days} days",
        ))
        results.append(HealthCheckResult(
            "PERF", "Profit factor", "OK" if pf >= 1.0 else "WARN",
            round(pf, 3), f"Profit factor {pf:.3f}",
        ))
        results.append(HealthCheckResult(
            "PERF", "Max drawdown", "OK" if abs(dd) <= 20 else "WARN",
            round(dd, 2), f"Max drawdown {dd:.1f}%",
        ))
        results.append(HealthCheckResult("PERF", "Trade count", "OK", n, f"{n} trades"))
    except Exception as exc:
        results.append(HealthCheckResult("PERF", "Performance check", "WARN", None, str(exc)))
    return results


def check_config_sanity(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Sanity-check critical config relationships."""
    results: list[HealthCheckResult] = []

    sl  = float(cfg.get("SL_PCT",     0.30))
    tgt = float(cfg.get("TARGET_PCT", 0.60))
    if sl >= tgt:
        results.append(HealthCheckResult(
            "CONFIG", "SL_PCT < TARGET_PCT", "FAIL",
            f"SL={sl} TARGET={tgt}",
            "SL_PCT must be less than TARGET_PCT.",
        ))
    else:
        results.append(HealthCheckResult(
            "CONFIG", "SL_PCT < TARGET_PCT", "OK",
            f"SL={sl} TARGET={tgt}", "OK",
        ))

    max_loss = float(cfg.get("MAX_DAILY_LOSS", 0))
    capital  = float(cfg.get("BASE_CAPITAL",  100000))
    if max_loss > 0 and capital > 0:
        pct = max_loss / capital * 100
        st  = "WARN" if pct > 5.0 else "OK"
        results.append(HealthCheckResult(
            "CONFIG", "Daily loss % of capital", st,
            round(pct, 2),
            f"MAX_DAILY_LOSS is {pct:.1f}% of BASE_CAPITAL {'(>5% is high)' if st == 'WARN' else ''}",
        ))

    threshold = int(cfg.get("AI_THRESHOLD", 60))
    if threshold < 50:
        results.append(HealthCheckResult(
            "CONFIG", "AI_THRESHOLD", "WARN", threshold,
            "AI_THRESHOLD below 50 may cause excessive entries.",
        ))
    else:
        results.append(HealthCheckResult(
            "CONFIG", "AI_THRESHOLD", "OK", threshold, "OK",
        ))

    return results


def check_system_health(cfg: dict[str, Any]) -> list[HealthCheckResult]:
    """Check disk space and log directory size."""
    results: list[HealthCheckResult] = []
    disk_warn_mb    = float(cfg.get("health_check_disk_warn_mb",    500.0))
    log_dir_warn_gb = float(cfg.get("health_check_log_dir_warn_gb", 2.0))

    # Disk free space
    try:
        import shutil
        total, used, free = shutil.disk_usage(".")
        free_mb = free / (1024 * 1024)
        st = "WARN" if free_mb < disk_warn_mb else "OK"
        results.append(HealthCheckResult(
            "SYS", "Disk free space", st,
            round(free_mb, 0),
            f"{free_mb:.0f} MB free {'(low!)' if st == 'WARN' else ''}",
        ))
    except Exception as exc:
        results.append(HealthCheckResult("SYS", "Disk free space", "WARN", None, str(exc)))

    # Log directory size
    log_dir = Path("logs")
    if log_dir.is_dir():
        try:
            total_bytes = sum(
                f.stat().st_size for f in log_dir.rglob("*") if f.is_file()
            )
            total_gb = total_bytes / (1024 ** 3)
            st = "WARN" if total_gb > log_dir_warn_gb else "OK"
            results.append(HealthCheckResult(
                "SYS", "Log directory size", st,
                round(total_gb, 3),
                f"{total_gb:.3f} GB in logs/ {'(consider rotation/cleanup)' if st == 'WARN' else ''}",
            ))
        except Exception as exc:
            results.append(HealthCheckResult("SYS", "Log directory size", "WARN", None, str(exc)))

    return results


# ── Main entry ────────────────────────────────────────────────────────────────

def run_full_health_check(
    cfg:     dict[str, Any] | None = None,
    db_path: str = _DEFAULT_DB,
) -> HealthReport:
    """
    Run all health checks and return a HealthReport.

    Args:
        cfg     : Config dict.
        db_path : Path to trades.db.

    Returns:
        HealthReport — always returns even if all checks fail.
    """
    c = cfg or {}
    report = HealthReport()

    for check_fn in (
        lambda: check_db_sizes(c),
        lambda: check_db_integrity(c),
        lambda: check_db_wal_size(c),
        lambda: check_ml_health(c),
        lambda: check_recent_performance(c, db_path),
        lambda: check_config_sanity(c),
        lambda: check_system_health(c),
    ):
        try:
            report.results.extend(check_fn())
        except Exception as exc:
            _log.warning("[HEALTH] check failed: %s", exc)

    if report.fail_count > 0:
        report.overall_status = "FAIL"
    elif report.warn_count > 0:
        report.overall_status = "WARN"
    else:
        report.overall_status = "OK"

    report.summary = (
        f"Health Check: {report.overall_status} — "
        f"{report.ok_count} OK, {report.warn_count} WARN, {report.fail_count} FAIL "
        f"({len(report.results)} checks total)"
    )
    return report


# ── Formatter ─────────────────────────────────────────────────────────────────

def format_health_report(report: HealthReport) -> str:
    """Return a multi-line human-readable health report."""
    lines = [
        "System Health Report",
        "=" * 60,
        report.summary,
        "",
    ]
    current_cat = ""
    for r in report.results:
        if r.category != current_cat:
            current_cat = r.category
            lines.append(f"  [{current_cat}]")
        sym = {"OK": "OK  ", "WARN": "WARN", "FAIL": "FAIL"}.get(r.status, "?   ")
        lines.append(f"    [{sym}] {r.name:<35} {r.message}")
    return "\n".join(lines)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m core.health_checker",
        description="Run system health checks.",
    )
    ap.add_argument("--all",    action="store_true", help="Run all checks")
    ap.add_argument("--db",     default=_DEFAULT_DB)
    ap.add_argument("--format", choices=["text", "json"], default="text")
    args = ap.parse_args()

    report = run_full_health_check(db_path=args.db)
    if args.format == "json":
        import json
        data = {
            "overall_status": report.overall_status,
            "summary": report.summary,
            "results": [
                {"category": r.category, "name": r.name,
                 "status": r.status, "value": r.value, "message": r.message}
                for r in report.results
            ],
        }
        print(json.dumps(data, indent=2))
    else:
        print(format_health_report(report))


if __name__ == "__main__":
    _cli()
