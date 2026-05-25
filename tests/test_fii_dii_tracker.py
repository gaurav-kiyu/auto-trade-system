"""Tests for core/fii_dii_tracker.py (v2.45 Item 1)."""
import time

from core.fii_dii_tracker import FIIDIIData, FIIDIITracker

# ── FIIDIIData ────────────────────────────────────────────────────────────────

def test_fiidii_data_fields():
    d = FIIDIIData(date="2026-04-30", fii_net=3500.0, dii_net=-1200.0, fetched_at=1.0)
    assert d.fii_net == 3500.0
    assert d.dii_net == -1200.0
    assert d.date == "2026-04-30"


def test_fiidii_data_positive_negative():
    d = FIIDIIData(date="2026-04-30", fii_net=-4000.0, dii_net=800.0, fetched_at=1.0)
    assert d.fii_net < 0
    assert d.dii_net > 0


# ── FIIDIITracker disabled ────────────────────────────────────────────────────

def test_tracker_disabled_returns_none():
    t = FIIDIITracker(cfg={"fii_dii_enabled": False})
    assert t.get_latest() is None


def test_tracker_disabled_score_adj_zero():
    t = FIIDIITracker(cfg={"fii_dii_enabled": False})
    assert t.score_adjustment("CALL") == 0


def test_tracker_disabled_eod_summary_empty():
    t = FIIDIITracker(cfg={"fii_dii_enabled": False})
    assert t.get_eod_summary() == ""


# ── Score adjustment logic ────────────────────────────────────────────────────

def _make_tracker_with_data(fii_net: float, dii_net: float = 0.0) -> FIIDIITracker:
    cfg = {"fii_dii_enabled": True, "fii_score_threshold": 2000.0, "fii_score_bonus": 5}
    t = FIIDIITracker(cfg=cfg)
    t._data = FIIDIIData(date="2026-04-30", fii_net=fii_net, dii_net=dii_net, fetched_at=time.time())
    t._last_fetch = time.time()
    return t


def test_score_adj_fii_buying_call_positive():
    t = _make_tracker_with_data(fii_net=3000.0)
    assert t.score_adjustment("CALL") == 5


def test_score_adj_fii_buying_put_negative():
    t = _make_tracker_with_data(fii_net=3000.0)
    assert t.score_adjustment("PUT") == -5


def test_score_adj_fii_selling_put_positive():
    t = _make_tracker_with_data(fii_net=-3000.0)
    assert t.score_adjustment("PUT") == 5


def test_score_adj_fii_selling_call_negative():
    t = _make_tracker_with_data(fii_net=-3000.0)
    assert t.score_adjustment("CALL") == -5


def test_score_adj_neutral_fii():
    t = _make_tracker_with_data(fii_net=500.0)   # below threshold
    assert t.score_adjustment("CALL") == 0
    assert t.score_adjustment("PUT") == 0


def test_score_adj_exactly_at_threshold():
    t = _make_tracker_with_data(fii_net=2000.0)   # at threshold (not above)
    assert t.score_adjustment("CALL") == 0


# ── Background thread ─────────────────────────────────────────────────────────

def test_background_thread_disabled_does_not_start():
    t = FIIDIITracker(cfg={"fii_dii_enabled": False})
    t.start_background_refresh()
    assert t._bg_thread is None


def test_stop_signals_thread():
    t = FIIDIITracker(cfg={"fii_dii_enabled": True, "fii_cache_hours": 24.0})
    t.stop()
    assert t._stop_event.is_set()


# ── EOD summary ───────────────────────────────────────────────────────────────

def test_eod_summary_format():
    t = _make_tracker_with_data(fii_net=3500.0, dii_net=-1200.0)
    summary = t.get_eod_summary()
    assert "FII" in summary
    assert "DII" in summary
    assert "3,500" in summary or "3500" in summary


def test_eod_summary_no_data():
    cfg = {"fii_dii_enabled": True}
    t = FIIDIITracker(cfg=cfg)
    # No data loaded
    t._data = None
    t._last_fetch = time.time()   # pretend fresh so no remote fetch
    result = t.get_eod_summary()
    # Should gracefully return unavailable message
    assert isinstance(result, str)
