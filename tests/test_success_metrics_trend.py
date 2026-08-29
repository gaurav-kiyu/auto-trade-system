"""Tests for core/success_metrics_trend.py.

Covers:
  - Snapshot capture + persistence round-trip
  - Direction computation (DOWN/UP/STABLE/NO_DATA) for MET-07 / MET-08
  - Metric validation verdicts
  - Constitution integration (validate_metric_trend)
  - Register regeneration integration (real generator output <-> tracker counts)
  - Corrupt storage tolerance
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest
from core.success_metrics_trend import (
    SuccessMetricsTrend,
    get_metrics_trend,
    reset_metrics_trend,
)


@pytest.fixture(autouse=True)
def _clean_state(tmp_path):
    reset_metrics_trend()
    yield tmp_path
    reset_metrics_trend()


def _new_trend(tmp_path) -> SuccessMetricsTrend:
    return SuccessMetricsTrend(str(tmp_path / "success_metrics_trend.json"))


def _inject(trend: SuccessMetricsTrend, indicators: dict[str, float], captured_at: float) -> None:
    from core.success_metrics_trend import TrendSnapshot
    with trend._lock:
        trend._snapshots.append(
            TrendSnapshot(captured_at=captured_at, release_label="v1", indicators=indicators)
        )


# ── Capture & persistence ────────────────────────────────────────────────────


def test_capture_creates_snapshot(tmp_path):
    trend = _new_trend(tmp_path)
    snap = trend.capture(release_label="v2.58.0")
    assert snap.release_label == "v2.58.0"
    assert "dead_code_findings" in snap.indicators
    assert "open_regressions" in snap.indicators
    assert "evidence_items" in snap.indicators
    assert "test_files" in snap.indicators


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "success_metrics_trend.json"
    t1 = SuccessMetricsTrend(str(path))
    t1.capture(release_label="v1")
    t1.capture(release_label="v2")

    t2 = SuccessMetricsTrend(str(path))
    snaps = t2.list_snapshots()
    assert len(snaps) == 2
    assert snaps[0].release_label == "v2"


def test_corrupt_storage_tolerated(tmp_path):
    path = tmp_path / "success_metrics_trend.json"
    path.write_text("{ not valid json", encoding="utf-8")
    trend = SuccessMetricsTrend(str(path))  # must not raise
    assert trend.get_stats()["total_snapshots"] == 0


def test_singleton():
    assert get_metrics_trend() is get_metrics_trend()


# ── Direction computation ────────────────────────────────────────────────────


def test_no_data_without_two_snapshots(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 100.0, "open_regressions": 5.0}, 1000.0)
    assert trend.compute_direction("MET-07") == "NO_DATA"


def test_met07_down_is_good(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 120.0, "duplicate_code": 30.0,
                    "config_drift": 4.0, "doc_drift": 2.0, "open_regressions": 3.0}, 1000.0)
    _inject(trend, {"dead_code_findings": 100.0, "duplicate_code": 25.0,
                    "config_drift": 3.0, "doc_drift": 2.0, "open_regressions": 1.0}, 2000.0)
    assert trend.compute_direction("MET-07") == "DOWN"
    assert trend.validate_metric("MET-07")["passed"] is True


def test_met07_up_is_bad(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 100.0, "duplicate_code": 20.0,
                    "config_drift": 2.0, "doc_drift": 1.0, "open_regressions": 0.0}, 1000.0)
    _inject(trend, {"dead_code_findings": 150.0, "duplicate_code": 40.0,
                    "config_drift": 5.0, "doc_drift": 3.0, "open_regressions": 2.0}, 2000.0)
    assert trend.compute_direction("MET-07") == "UP"
    assert trend.validate_metric("MET-07")["passed"] is False


def test_met08_up_is_good(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"test_files": 100.0, "evidence_items": 1500.0,
                    "commits_30d": 40.0, "engineering_velocity": 9.0}, 1000.0)
    _inject(trend, {"test_files": 130.0, "evidence_items": 1900.0,
                    "commits_30d": 60.0, "engineering_velocity": 12.0}, 2000.0)
    assert trend.compute_direction("MET-08") == "UP"
    assert trend.validate_metric("MET-08")["passed"] is True


def test_met08_down_is_bad(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"test_files": 130.0, "evidence_items": 1900.0,
                    "commits_30d": 60.0, "engineering_velocity": 12.0}, 1000.0)
    _inject(trend, {"test_files": 90.0, "evidence_items": 1200.0,
                    "commits_30d": 20.0, "engineering_velocity": 4.0}, 2000.0)
    assert trend.compute_direction("MET-08") == "DOWN"
    assert trend.validate_metric("MET-08")["passed"] is False


def test_stable_direction(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 100.0, "open_regressions": 1.0}, 1000.0)
    _inject(trend, {"dead_code_findings": 100.0, "open_regressions": 1.0}, 2000.0)
    assert trend.compute_direction("MET-07") == "STABLE"


# ── Reports & stats ──────────────────────────────────────────────────────────


def test_report_contains_verdicts(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 100.0, "open_regressions": 1.0}, 1000.0)
    _inject(trend, {"dead_code_findings": 90.0, "open_regressions": 0.0}, 2000.0)
    report = trend.get_report()
    assert report["total_snapshots"] == 2
    assert set(report["verdicts"]) == {"MET-07", "MET-08"}


def test_stats_has_directions(tmp_path):
    trend = _new_trend(tmp_path)
    _inject(trend, {"dead_code_findings": 100.0, "open_regressions": 1.0}, 1000.0)
    _inject(trend, {"dead_code_findings": 90.0, "open_regressions": 0.0}, 2000.0)
    stats = trend.get_stats()
    assert stats["MET-07_direction"] == "DOWN"
    assert stats["has_enough_data"] is True


# ── Indicator collection ─────────────────────────────────────────────────────


@patch("core.success_metrics_trend._count_commits", return_value=42.0)
def test_collect_indicators_all_keys(mock_commits, tmp_path):
    from core.success_metrics_trend import collect_indicators
    ind = collect_indicators()
    for key in ["dead_code_findings", "duplicate_code", "config_drift", "doc_drift",
                "open_regressions", "test_files", "evidence_items",
                "commits_30d", "engineering_velocity"]:
        assert key in ind
    assert ind["commits_30d"] == 42.0


# ── Indicator availability (None handling) ───────────────────────────────────


def test_unavailable_indicator_skipped_in_composite(tmp_path):
    """None-valued indicators must be excluded, not treated as 0."""
    trend = _new_trend(tmp_path)
    # Same dead-code signal but commits_30d is None in the latest snapshot.
    _inject(trend, {"test_files": 100.0, "evidence_items": 1500.0,
                    "commits_30d": 40.0, "engineering_velocity": 9.0}, 1000.0)
    _inject(trend, {"test_files": 130.0, "evidence_items": 1900.0,
                    "commits_30d": None, "engineering_velocity": None}, 2000.0)
    # commits_30d weight 1/3, engineering_velocity weight 1/4 — unavailable
    # indicators must not push the composite down toward a false DOWN.
    assert trend.compute_direction("MET-08") == "UP"


def test_none_indicator_round_trip(tmp_path):
    """None indicators survive JSON persistence round-trip."""
    path = tmp_path / "success_metrics_trend.json"
    t1 = SuccessMetricsTrend(str(path))
    with t1._lock:
        from core.success_metrics_trend import TrendSnapshot
        t1._snapshots.append(TrendSnapshot(
            captured_at=1000.0, release_label="v1",
            indicators={"commits_30d": None, "test_files": 5.0},
        ))
        t1._save()
    t2 = SuccessMetricsTrend(str(path))
    snap = t2.get_latest()
    assert snap is not None
    assert snap.indicators["commits_30d"] is None
    assert snap.indicators["test_files"] == 5.0


@patch("core.success_metrics_trend.subprocess.run", side_effect=OSError("no git"))
def test_count_commits_none_when_git_unavailable(mock_run):
    """Git unavailability must yield None, never a false 0."""
    from core.success_metrics_trend import _count_commits
    assert _count_commits(30) is None


# ── Register-pattern consistency ─────────────────────────────────────────────


def test_parse_register_ids_live_registers():
    """The live register files must exist and any parsed IDs must use the expected prefixes."""
    from core.success_metrics_trend import (
        REGISTER_ID_PATTERNS,
        parse_register_ids,
    )
    for register_path, expected_prefix in REGISTER_ID_PATTERNS.items():
        from pathlib import Path

        assert (Path(__file__).resolve().parent.parent / register_path).is_file(), (
            f"{register_path} register file missing"
        )
        ids = parse_register_ids(register_path)
        # An empty register is healthy (no tracked drift); a non-empty one
        # must only contain IDs with the expected prefix.
        for i in ids:
            assert i.startswith(expected_prefix), (
                f"{register_path}: {i} does not start with {expected_prefix}"
            )


def test_check_register_consistency_live_registers_ok():
    """The live registers must pass the consistency check end-to-end."""
    from core.success_metrics_trend import check_register_consistency
    result = check_register_consistency()
    assert result["ok"] is True
    for rp, detail in result["registers"].items():
        assert detail["ok"] is True, rp
        assert detail["foreign_ids"] == [], rp
        assert detail["count_agrees"] is True, rp
        assert int(detail["tracker_count"]) == detail["parsed_count"], rp


def test_check_register_consistency_detects_foreign_ids(tmp_path, monkeypatch):
    """A foreign (non-prefixed) row ID must flip the register to drift."""
    from core.success_metrics_trend import check_register_consistency
    reg = tmp_path / "config_drift_register.md"
    reg.write_text(
        "| ID | Detail |\n"
        "|----|--------|\n"
        "| CDR-001 | drift one |\n"
        "| OLD-999 | old scheme |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.success_metrics_trend.REGISTER_ID_PATTERNS",
        {str(reg): "CDR-"},
    )
    result = check_register_consistency()
    assert result["ok"] is False
    detail = next(iter(result["registers"].values()))
    assert detail["foreign_ids"] == ["OLD-999"]
    assert detail["ok"] is False


def test_check_register_consistency_detects_count_mismatch(tmp_path, monkeypatch):
    """A prefix appearing outside table rows must be flagged as count drift."""
    from core.success_metrics_trend import check_register_consistency
    reg = tmp_path / "doc_drift_register.md"
    reg.write_text(
        "| ID | Detail |\n"
        "|----|--------|\n"
        "| DDR-001 | drift one |\n"
        "| DDR-002 | drift two |\n"
        "Regenerated from DDR-001 and DDR-002.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "core.success_metrics_trend.REGISTER_ID_PATTERNS",
        {str(reg): "DDR-"},
    )
    result = check_register_consistency()
    assert result["ok"] is False
    detail = next(iter(result["registers"].values()))
    assert detail["count_agrees"] is False
    assert detail["foreign_ids"] == []


def test_check_register_consistency_missing_file_flagged(tmp_path, monkeypatch):
    """A missing register must be flagged as drift, not silently pass (0==0)."""
    from core.success_metrics_trend import check_register_consistency
    missing = tmp_path / "does_not_exist_register.md"
    monkeypatch.setattr(
        "core.success_metrics_trend.REGISTER_ID_PATTERNS",
        {str(missing): "CDR-"},
    )
    result = check_register_consistency()
    assert result["ok"] is False
    detail = next(iter(result["registers"].values()))
    assert detail["file_exists"] is False
    assert detail["ok"] is False


def test_cli_check_registers_exit_zero_when_aligned(tmp_path, monkeypatch):
    """--check-registers must exit 0 when the registers are aligned."""
    from core import success_metrics_trend as smt
    reg = tmp_path / "aligned_register.md"
    reg.write_text(
        "| ID | Detail |\n"
        "|----|--------|\n"
        "| CDR-001 | drift one |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(smt, "REGISTER_ID_PATTERNS", {str(reg): "CDR-"})
    monkeypatch.setattr(sys, "argv", ["prog", "--check-registers"])
    with pytest.raises(SystemExit) as exc:
        smt._cli()
    assert exc.value.code == 0


def test_cli_check_registers_exit_nonzero_on_drift(tmp_path, monkeypatch):
    """--check-registers must exit non-zero on drift so it can gate releases."""
    from core import success_metrics_trend as smt
    reg = tmp_path / "drifted_register.md"
    reg.write_text(
        "| ID | Detail |\n"
        "|----|--------|\n"
        "| CDR-001 | drift one |\n"
        "| OLD-999 | foreign |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(smt, "REGISTER_ID_PATTERNS", {str(reg): "CDR-"})
    monkeypatch.setattr(sys, "argv", ["prog", "--check-registers"])
    with pytest.raises(SystemExit) as exc:
        smt._cli()
    assert exc.value.code == 1


def test_capture_warns_on_register_drift(tmp_path, monkeypatch, caplog):
    """capture() must log a warning when register patterns drift."""
    import logging

    from core.success_metrics_trend import SuccessMetricsTrend
    monkeypatch.setattr(
        "core.success_metrics_trend.check_register_consistency",
        lambda: {
            "ok": False,
            "registers": {
                "docs/config_drift_register.md": {"ok": False},
            },
        },
    )
    trend = SuccessMetricsTrend(str(tmp_path / "trend.json"))
    with caplog.at_level(logging.WARNING, logger="core.success_metrics_trend"):
        trend.capture(release_label="v2.59.0")
    assert any(
        "Register-pattern drift" in r.message
        for r in caplog.records
    )


# ── Register regeneration integration ────────────────────────────────────────


def _regen_registers(tmp_path, monkeypatch, dead_count: int = 5, dup_count: int = 3):
    """Regenerate the dead/duplicate code registers with the REAL generator.

    Runs scripts.scan_dead_code.update_dead_code_register() and
    update_duplicate_code_register() (the actual production generators) with
    synthetic findings, writing into a temp docs/ dir (ROOT is monkeypatched so
    the real docs/ is never touched). Returns the generated register paths.
    """
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import scripts.scan_dead_code as sdc

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(exist_ok=True)

    dead = [
        sdc.DeadCodeFinding(
            category="UNUSED_IMPORT", file_path="core/foo.py", line=i,
            name=f"import_{i}",
            description=f"Import 'import_{i}' appears unused in foo.py",
            severity="LOW",
        )
        for i in range(1, dead_count + 1)
    ]
    dup = [
        sdc.DuplicateFinding(
            category="DUPLICATE_SYMBOL", file_a="core/a.py", line_a=i,
            file_b="core/b.py", line_b=i, name=f"sym_{i}", similarity=1.0,
            description=f"'{f'sym_{i}'}' defined in both a.py and b.py",
            severity="MEDIUM",
        )
        for i in range(1, dup_count + 1)
    ]

    monkeypatch.setattr(sdc, "ROOT", tmp_path)
    assert sdc.update_dead_code_register(dead) is True
    assert sdc.update_duplicate_code_register(dup) is True
    return docs_dir / "dead_code_register.md", docs_dir / "duplicate_code_register.md"


def test_regenerated_registers_match_tracker_counts(tmp_path, monkeypatch):
    """Real generator output must parse and count exactly as the tracker expects."""
    from core.success_metrics_trend import (
        check_register_consistency,
        parse_register_ids,
    )
    dc_path, dup_path = _regen_registers(tmp_path, monkeypatch, dead_count=5, dup_count=3)

    monkeypatch.setattr(
        "core.success_metrics_trend.REGISTER_ID_PATTERNS",
        {str(dc_path): "DC-", str(dup_path): "DUP-"},
    )
    result = check_register_consistency()
    assert result["ok"] is True

    dc = result["registers"][str(dc_path)]
    dup = result["registers"][str(dup_path)]
    # Tracker's line-count and the parser's row-count must both equal the
    # number of findings the generator wrote — any format drift breaks this.
    assert int(dc["tracker_count"]) == 5 == dc["parsed_count"]
    assert int(dup["tracker_count"]) == 3 == dup["parsed_count"]
    assert dc["foreign_ids"] == []
    assert dup["foreign_ids"] == []

    # IDs are zero-padded exactly as the generator emits them (DC-001, ...).
    assert parse_register_ids(str(dc_path)) == [f"DC-{i:03d}" for i in range(1, 6)]
    assert parse_register_ids(str(dup_path)) == [f"DUP-{i:03d}" for i in range(1, 4)]


def test_regeneration_updated_counts_stay_aligned(tmp_path, monkeypatch):
    """Re-running the generator with a new finding set updates counts consistently."""
    from core.success_metrics_trend import (
        check_register_consistency,
        parse_register_ids,
    )
    # First pass: 5 dead-code findings.
    dc_path, dup_path = _regen_registers(tmp_path, monkeypatch, dead_count=5, dup_count=2)
    monkeypatch.setattr(
        "core.success_metrics_trend.REGISTER_ID_PATTERNS",
        {str(dc_path): "DC-", str(dup_path): "DUP-"},
    )
    result = check_register_consistency()
    assert int(result["registers"][str(dc_path)]["tracker_count"]) == 5

    # Re-run the generator against the same temp docs dir — the update
    # functions replace the "## Scan Results" section in-place, so this
    # simulates the next scan producing fewer findings (2 dead, 0 duplicate).
    dc_path, dup_path = _regen_registers(tmp_path, monkeypatch, dead_count=2, dup_count=0)

    result2 = check_register_consistency()
    assert result2["ok"] is True
    assert int(result2["registers"][str(dc_path)]["tracker_count"]) == 2
    assert result2["registers"][str(dc_path)]["parsed_count"] == 2
    # Empty-but-present duplicate register: no rows, still consistent (0 == 0)
    # only because the file genuinely exists (generator wrote a placeholder).
    dup_detail = result2["registers"][str(dup_path)]
    assert dup_detail["file_exists"] is True
    assert int(dup_detail["tracker_count"]) == 0
    assert parse_register_ids(str(dup_path)) == []


# ── Constitution integration ─────────────────────────────────────────────────


def _empty_trend(tmp_path):
    """A fresh SuccessMetricsTrend with no snapshots (isolated storage)."""
    from core.success_metrics_trend import SuccessMetricsTrend
    return SuccessMetricsTrend(str(tmp_path / "isolated_metrics_trend.json"))


def test_validate_metric_trend_no_data(tmp_path, monkeypatch):
    from core.constitution import get_validator

    monkeypatch.setattr("core.success_metrics_trend.get_metrics_trend",
                        lambda *a, **k: _empty_trend(tmp_path))
    v = get_validator()
    result = v.validate_metric_trend("MET-07")
    # Without two snapshots, trend validation must fail with actionable detail.
    assert not result.passed
    assert "insufficient time-series data" in result.detail


def test_validate_metric_trend_unknown():
    from core.constitution import get_validator
    v = get_validator()
    result = v.validate_metric_trend("MET-99")
    assert not result.passed
    assert "trend" in result.detail.lower()
