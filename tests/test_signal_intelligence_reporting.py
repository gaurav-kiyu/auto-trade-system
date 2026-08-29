from pathlib import Path

from core.reporting.signal_intelligence import build_signal_intelligence_report
from core.reporting.exporter import signal_report_excel, signal_report_pdf
from core.signals.signal_tracker import SignalTracker


def test_signal_intelligence_reports_recorded_sl_vs_t1(tmp_path: Path):
    db = tmp_path / "signals.db"
    tracker = SignalTracker(db_path=db)
    with tracker._get_conn() as conn:
        conn.execute("DELETE FROM user_deliveries")
        conn.execute("DELETE FROM system_signals")
        conn.commit()
    ids = []
    statuses = ["TARGET_1_HIT"] * 3 + ["SL_HIT"] * 2
    for i, status in enumerate(statuses):
        sid = tracker.record_generated_signal({
            "symbol": f"TEST{i}", "category": "LARGE_CAP_EQUITY", "direction": "CALL",
            "score": 80 + i, "tier": "STRONG", "price": 100.0,
            "stop_loss": 95.0, "target_1": 105.0, "target_2": 110.0,
        }, eligible_users=[])
        ids.append(sid)
    with tracker._get_conn() as conn:
        for sid, status in zip(ids, statuses):
            conn.execute("UPDATE system_signals SET status=? WHERE signal_id=?", (status, sid))
        conn.commit()
    report = build_signal_intelligence_report(db_path=db, days=3650)
    assert report["summary"]["t1_or_better_rate_pct"] == 60.0
    assert report["summary"]["recorded_sl_before_t1_pct"] == 40.0
    assert report["data_quality"]["resolved_signals"] == 5
    assert report["recommendations"]


def test_signal_report_exports_are_real_files(tmp_path: Path):
    report = build_signal_intelligence_report(db_path=tmp_path / "missing.db")
    pdf = signal_report_pdf(report)
    xlsx = signal_report_excel(report)
    assert pdf.startswith(b"%PDF")
    assert xlsx.startswith(b"PK")

def test_generic_report_exporters(tmp_path: Path):
    from core.reporting.generic_exporter import export_generic_excel, export_generic_pdf
    payload = {"report_name": "Demo", "summary": {"count": 3}, "rows": [{"a": 1}, {"a": 2}]}
    assert export_generic_pdf(payload).startswith(b"%PDF")
    assert export_generic_excel(payload).startswith(b"PK")

def test_first_touch_t1_then_sl_remains_t1_first():
    """A later SL must never overwrite an earlier T1 first-touch outcome."""
    from core.reporting.signal_intelligence import _canonical_outcome

    row = {
        "first_touch": "T1",
        "first_touch_at": "2026-08-28T09:00:00+05:30",
        "status": "SL_HIT",
        "outcome_confidence": "EXACT_OBSERVATION",
    }

    assert _canonical_outcome(row) == "T1"


def test_first_touch_sl_then_t1_remains_sl_first():
    """A later T1 must never overwrite an earlier SL first-touch outcome."""
    from core.reporting.signal_intelligence import _canonical_outcome

    row = {
        "first_touch": "SL",
        "first_touch_at": "2026-08-28T09:00:00+05:30",
        "status": "TARGET_1_HIT",
        "outcome_confidence": "EXACT_OBSERVATION",
    }

    assert _canonical_outcome(row) == "SL"


def test_first_touch_t1_then_t2_remains_t1_first():
    """T2 is a later target achievement and cannot replace T1 first-touch."""
    from core.reporting.signal_intelligence import _canonical_outcome

    row = {
        "first_touch": "T1",
        "first_touch_at": "2026-08-28T09:00:00+05:30",
        "status": "TARGET_2_HIT",
        "outcome_confidence": "EXACT_OBSERVATION",
    }

    assert _canonical_outcome(row) == "T1"


def test_missing_first_touch_uses_legacy_terminal_status_only():
    """Legacy records remain reportable without inventing chronological ordering."""
    from core.reporting.signal_intelligence import (
        _canonical_first_touch,
        _canonical_outcome,
    )

    row = {
        "first_touch": None,
        "status": "SL_HIT",
        "outcome_confidence": None,
    }

    assert _canonical_first_touch(row) == ""
    assert _canonical_outcome(row) == "SL"


def test_explicit_first_touch_overrides_conflicting_latest_status():
    """Modern first_touch is authoritative even when latest status conflicts."""
    from core.reporting.signal_intelligence import _canonical_outcome

    row = {
        "first_touch": "T1",
        "first_touch_at": "2026-08-28T09:00:00+05:30",
        "status": "SL_HIT",
        "outcome_confidence": "EXACT_OBSERVATION",
    }

    assert _canonical_outcome(row) == "T1"
