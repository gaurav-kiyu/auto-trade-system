"""Tests for core/underlying_analyzer.py (v2.45 Item 16)."""
from core.underlying_analyzer import (
    StockAnalysis,
    analyze_banknifty_constituents,
    format_breadth_summary,
    get_sector_breadth,
)


def _make_analyses(n_above=3, n_total=5):
    result = []
    for i in range(n_total):
        above = i < n_above
        result.append(StockAnalysis(
            symbol=f"STOCK{i}.NS",
            price=1000.0 + i * 10,
            change_pct=1.0 if above else -1.0,
            volume_ratio=1.2,
            above_ma20=above,
            relative_strength=0.5 if above else -0.5,
        ))
    return result


# ── get_sector_breadth ────────────────────────────────────────────────────────

def test_breadth_all_above():
    analyses = _make_analyses(n_above=5, n_total=5)
    assert get_sector_breadth(analyses) == 1.0


def test_breadth_none_above():
    analyses = _make_analyses(n_above=0, n_total=5)
    assert get_sector_breadth(analyses) == 0.0


def test_breadth_partial():
    analyses = _make_analyses(n_above=3, n_total=5)
    assert abs(get_sector_breadth(analyses) - 0.6) < 0.01


def test_breadth_empty_returns_half():
    assert get_sector_breadth([]) == 0.5


# ── format_breadth_summary ────────────────────────────────────────────────────

def test_format_no_data():
    out = format_breadth_summary([])
    assert "unavailable" in out


def test_format_bullish():
    analyses = _make_analyses(n_above=4, n_total=5)
    out = format_breadth_summary(analyses)
    assert "BULLISH" in out


def test_format_bearish():
    analyses = _make_analyses(n_above=1, n_total=5)
    out = format_breadth_summary(analyses)
    assert "BEARISH" in out


def test_format_has_breadth_pct():
    analyses = _make_analyses(n_above=3, n_total=5)
    out = format_breadth_summary(analyses)
    assert "60%" in out or "breadth" in out.lower()


def test_format_mentions_top_mover():
    analyses = _make_analyses(n_above=3, n_total=5)
    # largest absolute change is first
    out = format_breadth_summary(analyses)
    assert "STOCK" in out


# ── analyze_banknifty_constituents ────────────────────────────────────────────

def test_disabled_returns_empty():
    result = analyze_banknifty_constituents({"underlying_analyzer_enabled": False})
    assert result == []


def test_default_disabled():
    # default is disabled - no config key means disabled
    result = analyze_banknifty_constituents({})
    assert result == []


# ── StockAnalysis dataclass ───────────────────────────────────────────────────

def test_stock_analysis_fields():
    a = StockAnalysis("HDFCBANK.NS", 1800.0, 1.5, 1.3, True, 0.8)
    assert a.symbol == "HDFCBANK.NS"
    assert a.above_ma20 is True
    assert a.relative_strength == 0.8
