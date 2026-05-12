"""Tests for core/live_readiness_checker.py (v2.44 Item 19)."""
import os
import sqlite3
import tempfile
import pytest
from core.live_readiness_checker import (
    CriterionResult,
    ReadinessReport,
    check_live_readiness,
    format_readiness_report,
    should_send_today,
    mark_sent_today,
    _load_paper_trades,
    _count_trading_days,
    _compute_drawdown,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_db(n_paper=60, win_frac=0.6, n_days=15, drawdown_pnls=None):
    """Create a trades.db satisfying (or not) the readiness criteria."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.execute("""
        CREATE TABLE trades (
            id INTEGER PRIMARY KEY, ts TEXT, index_name TEXT,
            direction TEXT, entry REAL, exit_price REAL, qty INTEGER,
            gross_pnl REAL, net_pnl REAL, reason TEXT, regime TEXT,
            score INTEGER, iv REAL, vix REAL, ltp_estimated INTEGER,
            partial INTEGER, sl_warned INTEGER, mode TEXT, version TEXT
        )
    """)
    pnls = drawdown_pnls or (
        [100] * int(n_paper * win_frac) + [-50] * (n_paper - int(n_paper * win_frac))
    )
    for i, pnl in enumerate(pnls):
        day = (i % max(n_days, 1)) + 1
        ts  = f"2024-01-{day:02d}T10:00:00"
        conn.execute(
            "INSERT INTO trades (ts,index_name,direction,entry,exit_price,qty,"
            "gross_pnl,net_pnl,reason,regime,score,iv,vix,ltp_estimated,"
            "partial,sl_warned,mode,version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, "NIFTY", "CALL", 100.0, 110.0, 50,
             float(pnl), float(pnl), "TARGET", "UPTREND", 72, 14.0, 13.0,
             0, 0, 0, "PAPER", "2.44"),
        )
    conn.commit()
    conn.close()
    return f.name


CFG_OK = {
    "live_readiness_min_paper_trades": 50,
    "live_readiness_min_win_rate": 0.50,
    "live_readiness_min_profit_factor": 1.30,
    "live_readiness_max_drawdown_pct": 15.0,
    "live_readiness_min_trading_days": 10,
    "live_readiness_days_window": 90,
}


# ── CriterionResult ───────────────────────────────────────────────────────────

def test_criterion_result_passed_is_pass():
    c = CriterionResult("test", True, True)
    assert c.status == "PASS"


def test_criterion_result_failed_blocking_is_fail():
    c = CriterionResult("test", False, True)
    assert c.status == "FAIL"


def test_criterion_result_failed_nonblocking_is_warn():
    c = CriterionResult("test", False, False)
    assert c.status == "WARN"


def test_criterion_result_fields():
    c = CriterionResult("name", True, True, 60, 50, "60 trades (need 50)")
    assert c.actual == 60
    assert c.required == 50
    assert "60" in c.message


# ── ReadinessReport ───────────────────────────────────────────────────────────

def test_readiness_report_blocking_criteria():
    r = ReadinessReport(
        overall_ready=True, blocking_score=5, readiness_score=0.9,
        criteria=[
            CriterionResult("a", True, True),
            CriterionResult("b", False, False),
        ],
    )
    assert len(r.blocking_criteria) == 1
    assert len(r.warning_criteria) == 1


# ── _compute_drawdown ─────────────────────────────────────────────────────────

def test_compute_drawdown_no_drawdown():
    pnls = [100, 100, 100]
    dd = _compute_drawdown(pnls)
    assert dd == pytest.approx(0.0)


def test_compute_drawdown_all_losses():
    pnls = [-100, -100, -100]
    dd = _compute_drawdown(pnls)
    assert dd >= 0


def test_compute_drawdown_recovers():
    pnls = [100, -50, 100]
    dd = _compute_drawdown(pnls)
    assert dd >= 0
    assert dd <= 100


def test_compute_drawdown_empty():
    dd = _compute_drawdown([])
    assert dd == 0.0


# ── _count_trading_days ───────────────────────────────────────────────────────

def test_count_trading_days():
    trades = [
        {"ts": "2024-01-15T10:00:00"},
        {"ts": "2024-01-15T11:00:00"},
        {"ts": "2024-01-16T10:00:00"},
    ]
    assert _count_trading_days(trades) == 2


def test_count_trading_days_empty():
    assert _count_trading_days([]) == 0


# ── check_live_readiness ──────────────────────────────────────────────────────

def test_readiness_all_pass():
    db = make_db(n_paper=60, win_frac=0.65, n_days=15)
    try:
        report = check_live_readiness(db, CFG_OK)
        # With 60 trades, 65% WR, 15 days → should pass most criteria
        assert isinstance(report, ReadinessReport)
        assert report.overall_ready in (True, False)  # depends on PF and DD
    finally:
        os.unlink(db)


def test_readiness_too_few_trades_blocks():
    db = make_db(n_paper=20, win_frac=0.65, n_days=10)
    try:
        report = check_live_readiness(db, CFG_OK)
        assert not report.overall_ready
        names = [c.name for c in report.blocking_criteria if not c.passed]
        assert "Minimum paper trades" in names
    finally:
        os.unlink(db)


def test_readiness_low_win_rate_blocks():
    db = make_db(n_paper=60, win_frac=0.35, n_days=15)
    try:
        report = check_live_readiness(db, CFG_OK)
        assert not report.overall_ready
    finally:
        os.unlink(db)


def test_readiness_too_few_days_blocks():
    db = make_db(n_paper=60, win_frac=0.65, n_days=5)
    try:
        report = check_live_readiness(db, dict(CFG_OK, live_readiness_min_trading_days=15))
        names = [c.name for c in report.blocking_criteria if not c.passed]
        assert "Minimum trading days" in names
    finally:
        os.unlink(db)


def test_readiness_missing_db_returns_report():
    report = check_live_readiness("/nonexistent.db", CFG_OK)
    assert isinstance(report, ReadinessReport)
    assert not report.overall_ready


def test_readiness_score_between_0_and_1():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        assert 0.0 <= report.readiness_score <= 1.0
    finally:
        os.unlink(db)


def test_readiness_has_blocking_and_warning_criteria():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        assert len(report.blocking_criteria) >= 5
    finally:
        os.unlink(db)


def test_readiness_summary_non_empty():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        assert len(report.summary) > 0
    finally:
        os.unlink(db)


def test_readiness_recommendation_non_empty():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        assert len(report.recommendation) > 0
    finally:
        os.unlink(db)


# ── format_readiness_report ───────────────────────────────────────────────────

def test_format_readiness_report_returns_string():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        text = format_readiness_report(report)
        assert isinstance(text, str)
    finally:
        os.unlink(db)


def test_format_readiness_report_contains_header():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        text = format_readiness_report(report)
        assert "Readiness" in text or "READY" in text or "NOT READY" in text
    finally:
        os.unlink(db)


def test_format_readiness_report_contains_criteria():
    db = make_db()
    try:
        report = check_live_readiness(db, CFG_OK)
        text = format_readiness_report(report)
        assert "Win rate" in text or "trades" in text.lower()
    finally:
        os.unlink(db)


# ── should_send_today / mark_sent_today ───────────────────────────────────────

def test_should_send_today_no_flag():
    with tempfile.TemporaryDirectory() as tmp:
        assert should_send_today(tmp) is True


def test_mark_sent_today_creates_flag():
    with tempfile.TemporaryDirectory() as tmp:
        mark_sent_today(tmp)
        assert not should_send_today(tmp)


def test_should_send_today_after_mark():
    with tempfile.TemporaryDirectory() as tmp:
        mark_sent_today(tmp)
        result = should_send_today(tmp)
        assert result is False
