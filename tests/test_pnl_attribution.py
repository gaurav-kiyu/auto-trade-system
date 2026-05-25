"""Tests for core/pnl_attribution.py (v2.45 Item 13)."""
from core.pnl_attribution import (
    AttributionResult,
    _score_tier,
    _summarise,
    compute_pnl_attribution,
    format_attribution_table,
)


def _rows():
    return [
        {"direction": "CALL", "regime": "TRENDING", "session": "MORNING",
         "score": 85.0, "day_of_week": "Monday",   "net_pnl": 500.0},
        {"direction": "CALL", "regime": "TRENDING", "session": "MORNING",
         "score": 70.0, "day_of_week": "Monday",   "net_pnl": -200.0},
        {"direction": "PUT",  "regime": "CHOPPY",   "session": "AFTERNOON",
         "score": 90.0, "day_of_week": "Wednesday", "net_pnl": 300.0},
        {"direction": "PUT",  "regime": "CHOPPY",   "session": "AFTERNOON",
         "score": 50.0, "day_of_week": "Friday",   "net_pnl": -100.0},
        {"direction": "CALL", "regime": "TRENDING", "session": "MORNING",
         "score": 82.0, "day_of_week": "Tuesday",  "net_pnl": 400.0},
    ]


# ── _score_tier ───────────────────────────────────────────────────────────────

def test_score_tier_high():
    assert _score_tier(85.0) == "HIGH(80+)"


def test_score_tier_medium():
    assert _score_tier(72.0) == "MED(65-79)"


def test_score_tier_low():
    assert _score_tier(55.0) == "LOW(<65)"


def test_score_tier_none():
    assert _score_tier(None) == "UNKNOWN"


def test_score_tier_boundary_80():
    assert _score_tier(80.0) == "HIGH(80+)"


def test_score_tier_boundary_65():
    assert _score_tier(65.0) == "MED(65-79)"


# ── _summarise ────────────────────────────────────────────────────────────────

def test_summarise_win_rate():
    rows = [{"net_pnl": 100.0}, {"net_pnl": -50.0}, {"net_pnl": 200.0}]
    r = _summarise("direction", "CALL", rows)
    assert abs(r.win_rate - 2/3) < 0.01


def test_summarise_total_pnl():
    rows = [{"net_pnl": 100.0}, {"net_pnl": 50.0}]
    r = _summarise("session", "MORNING", rows)
    assert r.total_pnl == 150.0


def test_summarise_avg_pnl():
    rows = [{"net_pnl": 100.0}, {"net_pnl": 200.0}]
    r = _summarise("regime", "TRENDING", rows)
    assert r.avg_pnl == 150.0


def test_summarise_empty_rows():
    r = _summarise("regime", "CHOPPY", [])
    assert r.trades == 0
    assert r.win_rate == 0.0


# ── compute_pnl_attribution — offline (no DB) ─────────────────────────────────

def test_attribution_disabled_returns_empty():
    result = compute_pnl_attribution(cfg={"pnl_attribution_enabled": False})
    assert result == []


def test_attribution_no_db_returns_empty():
    result = compute_pnl_attribution(
        db_path="nonexistent_db_xyz.db",
        days=30,
        cfg={"pnl_attribution_enabled": True},
    )
    assert result == []


# ── format_attribution_table ──────────────────────────────────────────────────

def _make_results():
    return [
        AttributionResult("direction", "CALL",    3, 2, 2/3, 900.0, 300.0),
        AttributionResult("direction", "PUT",     2, 1, 0.5, 200.0, 100.0),
        AttributionResult("regime",    "TRENDING",3, 2, 2/3, 700.0, 233.0),
    ]


def test_format_table_not_empty():
    out = format_attribution_table(_make_results())
    assert len(out) > 0


def test_format_table_has_direction():
    out = format_attribution_table(_make_results())
    assert "DIRECTION" in out


def test_format_table_has_regime():
    out = format_attribution_table(_make_results())
    assert "REGIME" in out


def test_format_table_no_results():
    out = format_attribution_table([])
    assert "no data" in out
