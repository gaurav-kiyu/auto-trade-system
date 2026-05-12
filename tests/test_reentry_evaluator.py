"""Tests for core/reentry_evaluator.py (v2.44 Item 2)."""
import time
import pytest
from core.reentry_evaluator import (
    ReentryDecision,
    ReentryTracker,
    build_reentry_trackers,
)

CFG = {
    "reentry_enabled": True,
    "reentry_cooldown_mins": 15,
    "reentry_score_boost": 5,
    "max_reentries_per_day": 2,
    "reentry_same_direction_only": True,
}


def fresh_tracker(name="NIFTY"):
    return ReentryTracker(index_name=name)


# ── Initial state ─────────────────────────────────────────────────────────────

def test_initial_no_sl_allows_reentry():
    t = fresh_tracker()
    d = t.evaluate_reentry(70, "CE", CFG)
    # No prior SL → this is first entry, not a re-entry situation
    assert isinstance(d, ReentryDecision)
    assert d.allowed is True


def test_initial_direction_intact_true_when_no_sl():
    t = fresh_tracker()
    d = t.evaluate_reentry(70, "CE", CFG)
    assert d.direction_intact is True


# ── After stop loss ───────────────────────────────────────────────────────────

def test_blocks_immediately_after_sl():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    d = t.evaluate_reentry(70, "CE", CFG)
    assert d.allowed is False
    assert d.cooldown_remaining_secs > 0


def test_allows_after_cooldown_expires():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    # Manually set last_sl_ts to past cooldown
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(70, "CE", CFG)
    assert d.allowed is True


# ── Score gate ────────────────────────────────────────────────────────────────

def test_requires_score_boost_after_sl():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(60, "CE", CFG)
    # original_score + boost required
    assert d.score_required == d.original_score + CFG["reentry_score_boost"]


def test_blocks_if_score_below_required():
    t = fresh_tracker()
    t.record_stop_loss("CE", 80)  # high SL score → high required
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(60, "CE", CFG)
    # 60 < 80+5 → blocked
    assert d.allowed is False


def test_allows_if_score_meets_requirement():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(70, "CE", CFG)  # 70 >= 60+5=65 → allowed
    assert d.allowed is True


# ── Direction check ───────────────────────────────────────────────────────────

def test_blocks_opposite_direction_when_same_dir_only():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(80, "PE", CFG)
    assert d.allowed is False
    assert d.direction_intact is False


def test_allows_opposite_direction_when_same_dir_disabled():
    cfg = dict(CFG, reentry_same_direction_only=False)
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.last_sl_ts = time.time() - (cfg["reentry_cooldown_mins"] * 60 + 10)
    d = t.evaluate_reentry(80, "PE", cfg)
    assert d.direction_intact is True


# ── Daily limit ───────────────────────────────────────────────────────────────

def test_blocks_when_daily_limit_reached():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.last_sl_ts = time.time() - (CFG["reentry_cooldown_mins"] * 60 + 10)
    t.reentries_today = CFG["max_reentries_per_day"]
    d = t.evaluate_reentry(90, "CE", CFG)
    assert d.allowed is False


def test_record_reentry_increments_counter():
    t = fresh_tracker()
    t.record_reentry()
    assert t.reentries_today == 1


# ── Disabled feature ─────────────────────────────────────────────────────────

def test_disabled_reentry_always_allowed():
    cfg = dict(CFG, reentry_enabled=False)
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    d = t.evaluate_reentry(40, "PE", cfg)
    assert d.allowed is True


# ── Reset daily ──────────────────────────────────────────────────────────────

def test_reset_daily_clears_reentries():
    t = fresh_tracker()
    t.reentries_today = 5
    t.reset_daily()
    assert t.reentries_today == 0


def test_reset_daily_clears_sl_ts():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    t.reset_daily()
    # Daily reset clears all state for new trading day
    assert t.last_sl_ts is None


# ── build_reentry_trackers ────────────────────────────────────────────────────

def test_build_creates_all_indices():
    trackers = build_reentry_trackers(["NIFTY", "BANKNIFTY", "FINNIFTY"])
    assert set(trackers.keys()) == {"NIFTY", "BANKNIFTY", "FINNIFTY"}


def test_build_returns_tracker_instances():
    trackers = build_reentry_trackers(["NIFTY"])
    assert isinstance(trackers["NIFTY"], ReentryTracker)


def test_build_empty_list():
    trackers = build_reentry_trackers([])
    assert trackers == {}


# ── Decision fields ───────────────────────────────────────────────────────────

def test_decision_has_cooldown_remaining():
    t = fresh_tracker()
    t.record_stop_loss("CE", 60)
    d = t.evaluate_reentry(70, "CE", CFG)
    assert d.cooldown_remaining_secs >= 0


def test_decision_has_current_score():
    t = fresh_tracker()
    d = t.evaluate_reentry(75, "CE", CFG)
    assert d.current_score == 75


def test_reason_is_string():
    t = fresh_tracker()
    d = t.evaluate_reentry(70, "CE", CFG)
    assert isinstance(d.reason, str)
    assert len(d.reason) > 0
