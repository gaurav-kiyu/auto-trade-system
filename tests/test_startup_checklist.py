"""Tests for core.startup_checklist - pre-session startup checklist."""

from __future__ import annotations

from core.startup_checklist import (
    StartupCheckItem,
    StartupCheckResult,
    run_startup_checklist,
)

# ── StartupCheckItem ─────────────────────────────────────────────────────

def test_startup_check_item_default() -> None:
    item = StartupCheckItem(name="test", passed=True)
    assert item.name == "test"
    assert item.passed is True
    assert item.detail == ""


def test_startup_check_item_status_pass() -> None:
    item = StartupCheckItem(name="test", passed=True)
    assert item.status_str() == "PASS"


def test_startup_check_item_status_fail() -> None:
    item = StartupCheckItem(name="test", passed=False, detail="something wrong")
    assert item.status_str() == "FAIL"


# ── StartupCheckResult ───────────────────────────────────────────────────

def test_startup_check_result_all_passed() -> None:
    items = (
        StartupCheckItem("a", True),
        StartupCheckItem("b", True),
    )
    result = StartupCheckResult(passed=True, items=items, failed_count=0)
    assert result.passed is True
    assert result.failed_count == 0
    summary = result.summary()
    assert "ALL" in summary
    assert "2" in summary


def test_startup_check_result_some_failed() -> None:
    items = (
        StartupCheckItem("a", True),
        StartupCheckItem("b", False, detail="broken"),
    )
    result = StartupCheckResult(passed=False, items=items, failed_count=1)
    assert result.passed is False
    assert result.failed_count == 1
    summary = result.summary()
    assert "FAILED" in summary
    assert "broken" in summary


def test_startup_check_result_as_dict() -> None:
    items = (
        StartupCheckItem("zombie_pnl_clear", True),
        StartupCheckItem("hard_halt_clear", False, detail="HALT set"),
    )
    result = StartupCheckResult(passed=False, items=items, failed_count=1)
    d = result.as_dict()
    assert d["overall"] == "FAIL"
    assert d["failed_count"] == 1
    assert len(d["checks"]) == 2
    assert d["checks"][0]["name"] == "zombie_pnl_clear"
    assert d["checks"][0]["status"] == "PASS"
    assert d["checks"][1]["status"] == "FAIL"


# ── run_startup_checklist: all pass ──────────────────────────────────────

def test_run_startup_checklist_all_pass() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
        config_version=1,
        expected_config_version=1,
    )
    assert result.passed is True
    assert result.failed_count == 0


# ── Individual check failures ────────────────────────────────────────────

def test_check_zombie_pnl_fails() -> None:
    result = run_startup_checklist(
        capital_adj_pending=500.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    assert result.passed is False
    assert result.items[0].passed is False
    assert "capital_adj_pending" in result.items[0].detail


def test_check_hard_halt_fails() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=False,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    assert result.passed is False
    assert result.items[1].passed is False  # hard_halt_clear is item index 1
    assert "HARD_HALT" in result.items[1].detail


def test_check_vix_blocked() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=30.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    assert result.passed is False
    vix_item = result.items[2]  # vix_acceptable
    assert vix_item.passed is False
    assert "30.0" in vix_item.detail


def test_check_vix_unavailable() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=None,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    assert result.passed is False
    vix_item = result.items[2]
    assert vix_item.passed is False
    assert "unavailable" in vix_item.detail


def test_check_data_feed_stale() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=60.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    feed_item = result.items[3]  # data_feed_fresh
    assert feed_item.passed is False
    assert "exceeds max" in feed_item.detail


def test_check_data_feed_none_at_startup() -> None:
    """data_feed_age_sec=None (first fetch pending) must pass, not fail."""
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=None,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="MANUAL",
    )
    feed_item = result.items[3]
    assert feed_item.passed is True  # first fetch pending is OK
    assert "initial startup" in feed_item.detail


def test_check_positions_not_aligned() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=False,
        execution_mode="MANUAL",
    )
    pos_item = result.items[4]  # positions_aligned
    assert pos_item.passed is False
    assert "do not match" in pos_item.detail


def test_check_unknown_execution_mode() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="UNDERWATER",
    )
    mode_item = result.items[5]  # execution_mode_valid
    assert mode_item.passed is False
    assert "Unknown" in mode_item.detail


def test_check_config_version_mismatch() -> None:
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="PAPER",
        config_version=2,
        expected_config_version=1,
    )
    ver_item = result.items[6]  # config_version
    assert ver_item.passed is False
    assert "mismatch" in ver_item.detail


def test_check_config_version_skipped_when_none() -> None:
    """When expected_config_version is None, the config_version check is skipped."""
    result = run_startup_checklist(
        capital_adj_pending=0.0,
        hard_halt_clear=True,
        vix=15.0,
        vix_block_threshold=27.0,
        data_feed_age_sec=5.0,
        data_feed_max_age_sec=30.0,
        positions_aligned=True,
        execution_mode="PAPER",
    )
    # Only 6 items (config_version check not added)
    assert len(result.items) == 6
    assert result.passed is True
