"""Success Metrics Time-Series Trend Tracking — Constitution v4.0 MET-07 / MET-08.

Provides provable time-series evidence for the two *trend* success metrics:

  - MET-07 "Technical Debt Trending Down"  (lower-is-better indicators)
  - MET-08 "Developer Productivity Trending Up" (higher-is-better indicators)

The tracker captures periodic snapshots of trend indicators (release-based), persists
them to ``json/success_metrics_trend.json``, and computes direction (DOWN / UP / STABLE)
by comparing consecutive snapshots. This turns the trend metrics from aspirational
targets into measurable, provable evidence across releases.

Indicators
----------
MET-07 (technical debt; lower is better):
  - dead_code_findings   (docs/dead_code_register.md   — "DC-" rows)
  - duplicate_code       (docs/duplicate_code_register.md — "DUP-" rows)
  - config_drift         (docs/config_drift_register.md)
  - doc_drift            (docs/doc_drift_register.md)
  - open_regressions     (ConstitutionValidator open regressions)

MET-08 (productivity; higher is better):
  - test_files           (tests/test_*.py count)
  - evidence_items       (ConstitutionValidator total evidence)
  - commits_30d          (git commits in last 30 days)
  - engineering_velocity (commits/week from engineering analytics, if available)

Usage:
    from core.success_metrics_trend import get_metrics_trend

    trend = get_metrics_trend()
    snap = trend.capture(release_label="v2.58.0")
    direction = trend.compute_direction("MET-07")
    result = trend.validate_metric("MET-07")

CLI:
    python -m core.success_metrics_trend --capture --release v2.58.0
    python -m core.success_metrics_trend --report
    python -m core.success_metrics_trend --validate MET-07
    python -m core.success_metrics_trend --check-registers
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

TREND_STATE_FILE = "json/success_metrics_trend.json"
# Minimum consecutive snapshots required to compute a direction.
MIN_SNAPSHOTS = 2

# Canonical register file -> expected ID prefix. This is the single source of
# truth shared by collect_indicators() and check_register_consistency() so the
# trend tracker and its consistency check can never drift apart.
REGISTER_ID_PATTERNS: dict[str, str] = {
    "docs/dead_code_register.md": "DC-",
    "docs/duplicate_code_register.md": "DUP-",
    "docs/config_drift_register.md": "CDR-",
    "docs/doc_drift_register.md": "DDR-",
}

# Register table rows carry an ID cell of the form PREFIX-### (e.g. CDR-001).
_REGISTER_ID_CELL_RE = re.compile(r"^[A-Z]{2,4}-\d{3,}$")


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class TrendSnapshot:
    """A single point-in-time capture of trend indicators."""

    captured_at: float
    release_label: str = ""
    # ``None`` means the indicator was unavailable at capture time (excluded
    # from composite computation) — distinct from a genuine 0 value.
    indicators: dict[str, float | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "captured_at": self.captured_at,
            "captured_at_iso": datetime.fromtimestamp(self.captured_at, tz=timezone.utc).isoformat(),
            "release_label": self.release_label,
            "indicators": dict(self.indicators),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrendSnapshot:
        return cls(
            captured_at=float(data.get("captured_at", 0)),
            release_label=str(data.get("release_label", "")),
            indicators={
                k: (None if v is None else float(v))
                for k, v in data.get("indicators", {}).items()
            },
        )


# ── Indicator collection ─────────────────────────────────────────────────────


def _count_pattern(path: str, pattern: str) -> float:
    """Count lines matching ``pattern`` in a file (0 if missing/unreadable)."""
    p = Path(__file__).resolve().parent.parent / path
    if not p.is_file():
        return 0.0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        return float(sum(1 for line in text.splitlines() if pattern in line))
    except OSError:
        return 0.0


def _register_row_count(register_path: str) -> float:
    """Count rows in a register file using its canonical ID prefix."""
    prefix = REGISTER_ID_PATTERNS.get(register_path)
    if prefix is None:
        _log.warning("[TREND] Unknown register path for counting: %s", register_path)
        return 0.0
    return _count_pattern(register_path, prefix)


def parse_register_ids(register_path: str) -> list[str]:
    """Parse the leading ID cell of each markdown table row in a register file.

    A register row is a line beginning with ``|`` whose first cell matches the
    register ID shape (e.g. ``CDR-001``). Missing or unreadable files yield an
    empty list.

    Args:
        register_path: Path to a register markdown file, relative to the repo root.

    Returns:
        List of parsed ID cells in file order.
    """
    p = Path(__file__).resolve().parent.parent / register_path
    if not p.is_file():
        return []
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    ids: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            continue
        first = cells[0]
        if _REGISTER_ID_CELL_RE.match(first):
            ids.append(first)
    return ids


def check_register_consistency() -> dict[str, Any]:
    """Verify the register files still use the ID prefixes the tracker counts.

    Guards against silent drift: if a register starts using a different ID
    scheme (e.g. ``CD-`` instead of ``CDR-``) or the tracker pattern is changed
    without updating the register, the trend indicators would silently count
    0/wrong values. This check parses the actual table rows and compares them
    against the expected prefix and the tracker's own count.

    Returns a dict with an overall ``ok`` flag and per-register detail.
    """
    results: dict[str, Any] = {}
    all_ok = True
    for register_path, expected_prefix in REGISTER_ID_PATTERNS.items():
        p = Path(__file__).resolve().parent.parent / register_path
        file_exists = p.is_file()
        row_ids = parse_register_ids(register_path)
        tracker_count = _register_row_count(register_path)
        matching = [i for i in row_ids if i.startswith(expected_prefix)]
        foreign = [i for i in row_ids if not i.startswith(expected_prefix)]
        count_agrees = int(tracker_count) == len(row_ids)
        # A missing register is the worst kind of silent drift — the tracker
        # would count 0 and 0==0 would otherwise look "aligned". Flag it.
        ok = file_exists and (not foreign) and count_agrees
        all_ok = all_ok and ok
        results[register_path] = {
            "expected_prefix": expected_prefix,
            "file_exists": file_exists,
            "row_ids": row_ids,
            "tracker_count": tracker_count,
            "parsed_count": len(row_ids),
            "matching_count": len(matching),
            "foreign_ids": foreign,
            "count_agrees": count_agrees,
            "ok": ok,
        }
    return {
        "ok": all_ok,
        "registers": results,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _count_files(path: str) -> float:
    p = Path(__file__).resolve().parent.parent / path
    if not p.is_dir():
        return 0.0
    return float(len(list(p.glob("test_*.py"))))


def _count_commits(days: int = 30) -> float | None:
    """Count git commits in the last ``days`` days.

    Returns ``None`` when git is unavailable (so the indicator is excluded
    from composite computation rather than recorded as a false 0).
    """
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={days} days ago", "HEAD"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return float(result.stdout.strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def collect_indicators() -> dict[str, float | None]:
    """Collect all trend indicators from the current repo state.

    Unavailable indicators (e.g. git not present) are ``None`` so they never
    masquerade as a genuine 0 in direction computation.
    """
    try:
        from core.constitution import get_validator
        v = get_validator()
        report = v.generate_report()
        open_regressions = float(report.open_regressions)
        evidence_items = float(report.total_evidence_items)
    except (ImportError, AttributeError, TypeError, ValueError):
        open_regressions = 0.0
        evidence_items = 0.0

    # Engineering velocity (commits/week) from analytics when available
    engineering_velocity: float | None = None
    try:
        from core.engineering_analytics import get_engineering_analytics
        analytics = get_engineering_analytics()
        eng_report = analytics.get_report(days=30)
        engineering_velocity = float(getattr(eng_report, "engineering_velocity", 0.0))
    except (ImportError, AttributeError, TypeError, ValueError):
        pass

    return {
        # MET-07: technical debt (lower is better)
        "dead_code_findings": _register_row_count("docs/dead_code_register.md"),
        "duplicate_code": _register_row_count("docs/duplicate_code_register.md"),
        "config_drift": _register_row_count("docs/config_drift_register.md"),
        "doc_drift": _register_row_count("docs/doc_drift_register.md"),
        "open_regressions": open_regressions,
        # MET-08: productivity (higher is better)
        "test_files": _count_files("tests"),
        "evidence_items": evidence_items,
        "commits_30d": _count_commits(30),
        "engineering_velocity": engineering_velocity,
    }


# ── Trend computation ────────────────────────────────────────────────────────

_METRIC_INDICATORS: dict[str, list[str]] = {
    "MET-07": ["dead_code_findings", "duplicate_code", "config_drift",
               "doc_drift", "open_regressions"],
    "MET-08": ["test_files", "evidence_items", "commits_30d", "engineering_velocity"],
}

_METRIC_LOWER_IS_BETTER: dict[str, bool] = {
    "MET-07": True,
    "MET-08": False,
}


def _composite(snapshot: TrendSnapshot, metric_id: str) -> float:
    """Weighted composite score of a metric's indicators in a snapshot.

    Indicators marked ``None`` (unavailable at capture time) are skipped so
    they neither inflate nor deflate the composite.
    """
    total = 0.0
    for idx, name in enumerate(_METRIC_INDICATORS.get(metric_id, [])):
        value = snapshot.indicators.get(name)
        if value is None:
            continue
        # Weight later indicators less; the first listed is the primary signal.
        weight = 1.0 / (1 + idx)
        total += weight * value
    return total


# ── Tracker ──────────────────────────────────────────────────────────────────


class SuccessMetricsTrend:
    """Time-series trend tracker for constitution success metrics.

    Thread-safe. Persists snapshots to ``json/success_metrics_trend.json``.
    """

    def __init__(self, storage_path: str = TREND_STATE_FILE) -> None:
        self._storage_path = storage_path
        self._lock = threading.RLock()
        self._snapshots: list[TrendSnapshot] = []
        self._load()

    # ── Capture ────────────────────────────────────────────────────────────

    def capture(self, release_label: str = "") -> TrendSnapshot:
        """Capture the current indicator values as a new snapshot."""
        indicators = collect_indicators()
        # Guard against register-pattern drift: warn (don't fail) when the
        # registers no longer match the prefixes the tracker counts, so the
        # captured indicators are never silently wrong.
        try:
            consistency = check_register_consistency()
            if not consistency["ok"]:
                drift = [
                    rp for rp, r in consistency["registers"].items()
                    if not r["ok"]
                ]
                _log.warning(
                    "[TREND] Register-pattern drift detected in %d file(s): %s. "
                    "Trend indicators may be inaccurate. Run "
                    "`python -m core.success_metrics_trend --check-registers`.",
                    len(drift), ", ".join(drift),
                )
        except Exception:  # pragma: no cover - defensive
            _log.warning("[TREND] Register consistency check failed", exc_info=True)
        with self._lock:
            snap = TrendSnapshot(
                captured_at=time.time(),
                release_label=release_label,
                indicators=indicators,
            )
            self._snapshots.append(snap)
            # Cap history to the most recent 500 snapshots.
            if len(self._snapshots) > 500:
                self._snapshots = self._snapshots[-500:]
            self._save()
            _log.info("[TREND] Captured snapshot release=%s indicators=%d",
                      release_label, len(indicators))
            return snap

    # ── Queries ────────────────────────────────────────────────────────────

    def list_snapshots(self, limit: int = 50) -> list[TrendSnapshot]:
        """Return the most recent snapshots (newest first)."""
        with self._lock:
            return list(reversed(self._snapshots[-limit:]))

    def get_latest(self) -> TrendSnapshot | None:
        """Return the most recent snapshot, if any."""
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_previous(self) -> TrendSnapshot | None:
        """Return the second-most-recent snapshot, if any."""
        with self._lock:
            if len(self._snapshots) >= 2:
                return self._snapshots[-2]
            return None

    def has_enough_data(self) -> bool:
        """True when at least MIN_SNAPSHOTS exist for direction computation."""
        return len(self._snapshots) >= MIN_SNAPSHOTS

    # ── Direction ──────────────────────────────────────────────────────────

    def compute_direction(self, metric_id: str) -> str:
        """Compute the direction of a metric: "DOWN", "UP", "STABLE" or "NO_DATA".

        Compares the composite score of the latest two snapshots.
        For lower-is-better metrics (MET-07), a fall means DOWN (good).
        For higher-is-better metrics (MET-08), a rise means UP (good).
        """
        latest = self.get_latest()
        prev = self.get_previous()
        if not latest or not prev:
            return "NO_DATA"
        current = _composite(latest, metric_id)
        previous = _composite(prev, metric_id)
        lower_is_better = _METRIC_LOWER_IS_BETTER.get(metric_id, False)
        delta = current - previous
        if abs(delta) < 1e-9:
            return "STABLE"
        if lower_is_better:
            return "DOWN" if delta < 0 else "UP"
        return "UP" if delta > 0 else "DOWN"

    def validate_metric(self, metric_id: str) -> dict[str, Any]:
        """Validate a trend metric, returning a verdict with evidence.

        Returns a dict with keys: metric_id, name, passed, direction, snapshots,
        latest_composite, previous_composite, detail.
        """
        names = {
            "MET-07": "Technical Debt Trending Down",
            "MET-08": "Developer Productivity Trending Up",
        }
        name = names.get(metric_id, metric_id)
        direction = self.compute_direction(metric_id)

        if direction == "NO_DATA":
            return {
                "metric_id": metric_id,
                "name": name,
                "passed": False,
                "direction": direction,
                "snapshots": len(self._snapshots),
                "detail": (f"Metric '{name}' has insufficient time-series data "
                           f"({len(self._snapshots)} snapshot(s); need >= {MIN_SNAPSHOTS}). "
                           f"Run `python -m core.success_metrics_trend --capture` on each release."),
                "evidence_required": ["time_series_snapshots"],
            }

        latest = self.get_latest()
        prev = self.get_previous()
        good = direction == "DOWN" if _METRIC_LOWER_IS_BETTER.get(metric_id, False) else direction == "UP"

        return {
            "metric_id": metric_id,
            "name": name,
            "passed": good,
            "direction": direction,
            "snapshots": len(self._snapshots),
            "latest_composite": round(_composite(latest, metric_id), 2),
            "previous_composite": round(_composite(prev, metric_id), 2),
            "detail": (f"Metric '{name}' trending {direction} "
                       f"({len(self._snapshots)} snapshots, latest release={latest.release_label or 'n/a'}). "
                       f"Direction {'satisfies' if good else 'violates'} the constitutional target."),
        }

    def get_report(self) -> dict[str, Any]:
        """Full trend report: snapshots, directions, and per-metric verdicts."""
        with self._lock:
            snapshots = [s.to_dict() for s in self._snapshots]
        verdicts = {mid: self.validate_metric(mid) for mid in _METRIC_INDICATORS}
        return {
            "metric_ids": list(_METRIC_INDICATORS),
            "total_snapshots": len(self._snapshots),
            "snapshots": snapshots,
            "verdicts": verdicts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_stats(self) -> dict[str, Any]:
        """Quick statistics for dashboard display."""
        with self._lock:
            latest = self._snapshots[-1] if self._snapshots else None
        return {
            "total_snapshots": len(self._snapshots),
            "latest_captured_at": latest.captured_at if latest else 0.0,
            "latest_release": latest.release_label if latest else "",
            "MET-07_direction": self.compute_direction("MET-07"),
            "MET-08_direction": self.compute_direction("MET-08"),
            "has_enough_data": self.has_enough_data(),
        }

    # ── Persistence ───────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            path = Path(self._storage_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {"snapshots": [s.to_dict() for s in self._snapshots]}
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            _log.warning("[TREND] Failed to save: %s", exc)

    def _load(self) -> None:
        path = Path(self._storage_path)
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._snapshots = [
                TrendSnapshot.from_dict(s) for s in data.get("snapshots", [])
            ]
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            _log.warning("[TREND] Failed to load: %s", exc)


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: SuccessMetricsTrend | None = None
_instance_lock = threading.RLock()


def get_metrics_trend(storage_path: str = TREND_STATE_FILE) -> SuccessMetricsTrend:
    """Return the process-level SuccessMetricsTrend singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = SuccessMetricsTrend(storage_path)
        return _instance


def reset_metrics_trend() -> None:
    """Force-reset the singleton (for testing).

    Does NOT delete the persisted history file — it is tracked governance
    evidence, so it must survive test runs and CI checkouts.
    """
    global _instance
    with _instance_lock:
        _instance = None


# ── CLI ──────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m core.success_metrics_trend")
    ap.add_argument("--capture", action="store_true", help="Capture a new trend snapshot")
    ap.add_argument("--release", type=str, default="", help="Release label for the snapshot")
    ap.add_argument("--report", action="store_true", help="Show full trend report")
    ap.add_argument("--validate", metavar="MET-07|MET-08", help="Validate a single trend metric")
    ap.add_argument("--stats", action="store_true", help="Show quick statistics")
    ap.add_argument("--check-registers", action="store_true",
                    help="Verify register ID patterns match what the tracker counts")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    trend = get_metrics_trend()

    if args.check_registers:
        consistency = check_register_consistency()
        if args.json:
            print(json.dumps(consistency, indent=2, default=str))
        else:
            print("Register pattern consistency check")
            for rp, r in consistency["registers"].items():
                status = "OK" if r["ok"] else "DRIFT"
                print(f"  [{status}] {rp}: expected '{r['expected_prefix']}'",
                      f"rows={r['parsed_count']} tracker_count={int(r['tracker_count'])}",
                      f"foreign_ids={r['foreign_ids']}")
            print("Result:", "ALL REGISTERS ALIGNED" if consistency["ok"]
                  else "DRIFT DETECTED — registers no longer match tracker patterns")
        # Exit non-zero on drift so the flag doubles as a CI / release-pipeline
        # gate (release_governance runs it before permitting a release).
        raise SystemExit(0 if consistency["ok"] else 1)

    if args.capture:
        snap = trend.capture(release_label=args.release)
        print(f"Captured snapshot ({snap.to_dict()['captured_at_iso']}) release={args.release or 'n/a'}")
        return

    if args.validate:
        verdict = trend.validate_metric(args.validate.upper())
        if args.json:
            print(json.dumps(verdict, indent=2))
        else:
            status = "PASS" if verdict["passed"] else "FAIL"
            print(f"{verdict['metric_id']} {verdict['name']}: {status}")
            print(f"  Direction: {verdict['direction']}  Snapshots: {verdict['snapshots']}")
            print(f"  {verdict['detail']}")
        return

    if args.report:
        report = trend.get_report()
        if args.json:
            print(json.dumps(report, indent=2, default=str))
        else:
            print(f"Success Metrics Trend: {report['total_snapshots']} snapshots")
            for mid, verdict in report["verdicts"].items():
                status = "PASS" if verdict["passed"] else "FAIL"
                print(f"  {mid} ({verdict['name']}): {status} — {verdict['direction']}")
        return

    if args.stats or args.json:
        stats = trend.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print(f"Snapshots: {stats['total_snapshots']}  "
                  f"MET-07: {stats['MET-07_direction']}  "
                  f"MET-08: {stats['MET-08_direction']}")
        return

    print(f"Success Metrics Trend: {trend.get_stats()['total_snapshots']} snapshots "
          f"(MET-07: {trend.get_stats()['MET-07_direction']}, "
          f"MET-08: {trend.get_stats()['MET-08_direction']})")


if __name__ == "__main__":
    _cli()


__all__ = [
    "MIN_SNAPSHOTS",
    "REGISTER_ID_PATTERNS",
    "TREND_STATE_FILE",
    "SuccessMetricsTrend",
    "TrendSnapshot",
    "check_register_consistency",
    "collect_indicators",
    "get_metrics_trend",
    "parse_register_ids",
    "reset_metrics_trend",
]
