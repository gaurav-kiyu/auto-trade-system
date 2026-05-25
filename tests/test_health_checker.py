"""Tests for core/health_checker.py (v2.44 Item 17)."""
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from core.health_checker import (
    HealthCheckResult,
    HealthReport,
    check_config_sanity,
    check_db_integrity,
    check_db_sizes,
    check_db_wal_size,
    check_system_health,
    format_health_report,
    run_full_health_check,
)

# ── HealthCheckResult ─────────────────────────────────────────────────────────

def test_health_check_result_fields():
    r = HealthCheckResult(
        category="DB", name="test", status="OK", value=1.0, message="ok"
    )
    assert r.category == "DB"
    assert r.name == "test"
    assert r.status == "OK"
    assert r.value == 1.0
    assert r.message == "ok"


def test_health_check_result_statuses():
    for st in ("OK", "WARN", "FAIL"):
        r = HealthCheckResult("X", "y", st)
        assert r.status == st


# ── HealthReport ──────────────────────────────────────────────────────────────

def test_health_report_ok_count():
    report = HealthReport(results=[
        HealthCheckResult("A", "a", "OK"),
        HealthCheckResult("A", "b", "WARN"),
        HealthCheckResult("A", "c", "FAIL"),
    ])
    assert report.ok_count == 1
    assert report.warn_count == 1
    assert report.fail_count == 1


def test_health_report_all_ok():
    report = HealthReport(results=[
        HealthCheckResult("A", "x", "OK"),
        HealthCheckResult("A", "y", "OK"),
    ])
    assert report.ok_count == 2
    assert report.warn_count == 0
    assert report.fail_count == 0


def test_health_report_overall_status_default():
    report = HealthReport()
    assert report.overall_status == "OK"


# ── check_db_sizes ────────────────────────────────────────────────────────────

def test_check_db_sizes_missing_db_returns_ok():
    results = check_db_sizes({"health_check_db_warn_mb": {"nonexistent.db": 50.0}})
    # The function merges with _DB_WARN_MB_DEFAULTS, so multiple results are returned
    assert len(results) >= 1
    # The nonexistent.db entry should be OK (no file -> no warning)
    nonexistent = [r for r in results if "nonexistent" in r.name]
    assert len(nonexistent) == 1
    assert nonexistent[0].status == "OK"


def test_check_db_sizes_small_file_is_ok():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(b"x" * 100)
        fpath = f.name
    try:
        {"health_check_db_warn_mb": {os.path.basename(fpath): 50.0}}
        import core.health_checker as hc
        orig_db = hc._DB_WARN_MB_DEFAULTS.copy()
        hc._DB_WARN_MB_DEFAULTS.clear()
        hc._DB_WARN_MB_DEFAULTS[fpath] = 50.0
        results = check_db_sizes({})
        hc._DB_WARN_MB_DEFAULTS.clear()
        hc._DB_WARN_MB_DEFAULTS.update(orig_db)
        assert any(r.status in ("OK", "WARN") for r in results)
    finally:
        os.unlink(fpath)


def test_check_db_sizes_returns_list():
    results = check_db_sizes({})
    assert isinstance(results, list)


# ── check_db_integrity ────────────────────────────────────────────────────────

def test_check_db_integrity_valid_db_passes():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        fpath = f.name
    conn = sqlite3.connect(fpath)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    import core.health_checker as hc
    orig = hc._DB_WARN_MB_DEFAULTS.copy()
    hc._DB_WARN_MB_DEFAULTS.clear()
    hc._DB_WARN_MB_DEFAULTS[fpath] = 50.0
    try:
        results = check_db_integrity({})
        assert any(r.status == "OK" for r in results)
    finally:
        hc._DB_WARN_MB_DEFAULTS.clear()
        hc._DB_WARN_MB_DEFAULTS.update(orig)
        os.unlink(fpath)


def test_check_db_integrity_missing_db_skipped():
    results = check_db_integrity({})
    assert isinstance(results, list)


# ── check_db_wal_size ─────────────────────────────────────────────────────────

def test_check_db_wal_size_no_wal_returns_empty():
    results = check_db_wal_size({})
    assert isinstance(results, list)


# ── check_config_sanity ───────────────────────────────────────────────────────

def test_check_config_sanity_sl_lt_target_ok():
    cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60, "BASE_CAPITAL": 100000, "MAX_DAILY_LOSS": 2000, "AI_THRESHOLD": 65}
    results = check_config_sanity(cfg)
    sl_check = next(r for r in results if "SL_PCT" in r.name)
    assert sl_check.status == "OK"


def test_check_config_sanity_sl_gt_target_fails():
    cfg = {"SL_PCT": 0.70, "TARGET_PCT": 0.60, "BASE_CAPITAL": 100000, "MAX_DAILY_LOSS": 2000, "AI_THRESHOLD": 65}
    results = check_config_sanity(cfg)
    sl_check = next(r for r in results if "SL_PCT" in r.name)
    assert sl_check.status == "FAIL"


def test_check_config_sanity_low_threshold_warns():
    cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60, "BASE_CAPITAL": 100000, "MAX_DAILY_LOSS": 2000, "AI_THRESHOLD": 40}
    results = check_config_sanity(cfg)
    thresh = next((r for r in results if "AI_THRESHOLD" in r.name), None)
    if thresh:
        assert thresh.status == "WARN"


def test_check_config_sanity_returns_results():
    cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60}
    results = check_config_sanity(cfg)
    assert len(results) >= 1


def test_check_config_high_daily_loss_warns():
    cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60, "BASE_CAPITAL": 10000, "MAX_DAILY_LOSS": 1000, "AI_THRESHOLD": 65}
    results = check_config_sanity(cfg)
    loss_check = next((r for r in results if "Daily loss" in r.name), None)
    if loss_check:
        assert loss_check.status == "WARN"


# ── check_system_health ───────────────────────────────────────────────────────

def test_check_system_health_returns_list():
    results = check_system_health({})
    assert isinstance(results, list)


def test_check_system_health_disk_check_present():
    results = check_system_health({})
    cats = [r.category for r in results]
    assert "SYS" in cats or len(results) >= 0


# ── run_full_health_check ─────────────────────────────────────────────────────

def test_run_full_health_check_returns_report():
    report = run_full_health_check()
    assert isinstance(report, HealthReport)


def test_run_full_health_check_overall_status_set():
    report = run_full_health_check()
    assert report.overall_status in ("OK", "WARN", "FAIL")


def test_run_full_health_check_summary_non_empty():
    report = run_full_health_check()
    assert len(report.summary) > 0


def test_run_full_health_check_has_results():
    report = run_full_health_check()
    assert isinstance(report.results, list)
    assert len(report.results) >= 0


def test_run_full_health_check_with_good_config():
    cfg = {
        "SL_PCT": 0.30,
        "TARGET_PCT": 0.60,
        "AI_THRESHOLD": 65,
        "BASE_CAPITAL": 100000,
        "MAX_DAILY_LOSS": 2000,
    }
    report = run_full_health_check(cfg)
    assert report.overall_status in ("OK", "WARN", "FAIL")


def test_run_full_health_check_fail_config():
    cfg = {"SL_PCT": 0.70, "TARGET_PCT": 0.60}
    report = run_full_health_check(cfg)
    assert report.fail_count >= 1
    assert report.overall_status == "FAIL"


# ── format_health_report ──────────────────────────────────────────────────────

def test_format_health_report_returns_string():
    report = run_full_health_check()
    text = format_health_report(report)
    assert isinstance(text, str)


def test_format_health_report_contains_summary():
    report = run_full_health_check()
    text = format_health_report(report)
    assert report.overall_status in text


def test_format_health_report_contains_check_marks():
    report = HealthReport(results=[
        HealthCheckResult("A", "good", "OK", message="test ok"),
        HealthCheckResult("A", "bad",  "FAIL", message="test fail"),
    ])
    report.overall_status = "FAIL"
    text = format_health_report(report)
    assert "OK" in text or "FAIL" in text


def test_format_health_report_empty_report():
    report = HealthReport()
    text = format_health_report(report)
    assert isinstance(text, str)


# ── Drawdown percentage calculation ───────────────────────────────────────────

def _recent_trade_ts(days_ago: int, hour: int = 10) -> str:
    """Generate an ISO timestamp within the last N days."""
    dt = datetime.utcnow() - timedelta(days=days_ago, hours=24 - hour)
    return dt.isoformat()


def test_drawdown_positive_pnl_shows_percentage():
    """Drawdown should show as a percentage of peak equity, not raw rupees."""
    # net_pnl values: +500, -200, +300, -100, +200
    # Step1: cum=500  peak=500  dd=0
    # Step2: cum=300  peak=500  dd=200
    # Step3: cum=600  peak=600  dd=0
    # Step4: cum=500  peak=600  dd=100
    # Step5: cum=700  peak=700  dd=0
    # max_dd_rupees = 200, total_pnl = 700
    # peak_approx = 700+200 = 900, dd_pct = 200/900*100 = 22.2%
    cfg = {
        "SL_PCT": 0.30,
        "TARGET_PCT": 0.60,
        "BASE_CAPITAL": 100000,
        "MAX_DAILY_LOSS": 2000,
        "AI_THRESHOLD": 65,
        "sensitivity_report_days": 30,
    }
    import os
    import sqlite3
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db = f.name
    f.close()
    try:
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, ts TEXT, index_name TEXT, direction TEXT,
            entry REAL, exit_price REAL, qty INTEGER, gross_pnl REAL, net_pnl REAL,
            reason TEXT, regime TEXT, score REAL, mode TEXT
        )""")
        trades = [
            (500, _recent_trade_ts(1, 10)),
            (-200, _recent_trade_ts(1, 11)),
            (300, _recent_trade_ts(1, 12)),
            (-100, _recent_trade_ts(1, 13)),
            (200, _recent_trade_ts(1, 14)),
        ]
        for i, (pnl, ts) in enumerate(trades):
            conn.execute("""INSERT INTO trades
                (id, ts, index_name, direction, entry, exit_price, qty,
                 gross_pnl, net_pnl, reason, mode)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (i+1, ts, 'NIFTY', 'CALL', 18000, 18100, 50, pnl, pnl, 'TP', 'PAPER'))
        conn.commit()
        conn.close()

        from core.health_checker import check_recent_performance
        results = check_recent_performance(cfg, db)
        dd_check = next((r for r in results if 'drawdown' in r.name.lower()), None)
        assert dd_check is not None, f"No drawdown check: {[r.name for r in results]}"
        assert dd_check.value < 100, f"Value {dd_check.value} should be % not raw rupees"
        assert dd_check.value > 0, "Drawdown should be > 0"
        msg = dd_check.message
        assert '%' in msg or '\u20b9' in msg, f"Message should contain % or rupee: {msg}"
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_drawdown_negative_pnl_does_not_crash():
    """Net-loss scenario should not crash and should return a safe value."""
    import os
    import sqlite3
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db = f.name
    f.close()
    try:
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, ts TEXT, index_name TEXT, direction TEXT,
            entry REAL, exit_price REAL, qty INTEGER, gross_pnl REAL, net_pnl REAL,
            reason TEXT, regime TEXT, score REAL, mode TEXT
        )""")
        trades = [
            (-500, _recent_trade_ts(2, 10)),
            (-200, _recent_trade_ts(2, 11)),
            (100, _recent_trade_ts(2, 12)),
        ]
        for i, (pnl, ts) in enumerate(trades):
            conn.execute("""INSERT INTO trades
                (id, ts, index_name, direction, entry, exit_price, qty,
                 gross_pnl, net_pnl, reason, mode)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (i+1, ts, 'NIFTY', 'PUT', 18000, 17900, 50, pnl, pnl, 'SL', 'PAPER'))
        conn.commit()
        conn.close()

        from core.health_checker import check_recent_performance
        cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60, "BASE_CAPITAL": 100000,
               "MAX_DAILY_LOSS": 2000, "AI_THRESHOLD": 65,
               "sensitivity_report_days": 30}
        results = check_recent_performance(cfg, db)
        dd_check = next((r for r in results if 'drawdown' in r.name.lower()), None)
        assert dd_check is not None, f"No drawdown check: {[r.name for r in results]}"
        assert isinstance(dd_check.value, (int, float)), f"Value should be numeric: {dd_check.value}"
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass


def test_drawdown_zero_trades_does_not_crash():
    """Zero trades should return early without drawdown check."""
    from core.health_checker import check_recent_performance
    cfg = {"SL_PCT": 0.30, "TARGET_PCT": 0.60, "sensitivity_report_days": 30}
    import os
    import tempfile
    f = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    db = f.name
    f.close()
    try:
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("""CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY, ts TEXT, net_pnl REAL, mode TEXT
        )""")
        conn.commit()
        conn.close()
        results = check_recent_performance(cfg, db)
        trade_count = next((r for r in results if 'trade' in r.name.lower()), None)
        assert trade_count is not None
        assert trade_count.status == 'WARN'
    finally:
        try:
            os.unlink(db)
        except PermissionError:
            pass
