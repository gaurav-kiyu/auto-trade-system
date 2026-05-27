"""Tests for core/nlp_journal.py (v2.45 Item 17) — template-based, no AI API required."""
from core.nlp_journal import (
    TradeNarrative,
    _build_prompt,
    _classify_sentiment,
    _extract_sentiment,
    format_narrative,
    generate_trade_narrative,
)


def _trade():
    return {
        "id": 42,
        "direction": "CALL",
        "regime": "TRENDING",
        "session": "MORNING",
        "score": 85.0,
        "entry_price": 200.0,
        "exit_price": 280.0,
        "net_pnl": 4000.0,
        "exit_reason": "TARGET",
        "hold_mins": 45,
    }


# ── _build_prompt ─────────────────────────────────────────────────────────────

def test_prompt_contains_direction():
    p = _build_prompt(_trade())
    assert "CALL" in p


def test_prompt_contains_pnl():
    p = _build_prompt(_trade())
    assert "4000" in p


def test_prompt_non_empty():
    p = _build_prompt(_trade())
    assert len(p) > 50


def test_prompt_contains_sentiment_instruction():
    p = _build_prompt(_trade())
    assert "SENTIMENT" in p.upper()


# ── _extract_sentiment ────────────────────────────────────────────────────────

def test_extract_positive():
    assert _extract_sentiment("Good trade. SENTIMENT: POSITIVE") == "POSITIVE"


def test_extract_negative():
    assert _extract_sentiment("Bad call. SENTIMENT: NEGATIVE here.") == "NEGATIVE"


def test_extract_neutral_default():
    assert _extract_sentiment("No signal detected.") == "NEUTRAL"


def test_extract_case_insensitive():
    assert _extract_sentiment("sentiment: positive at end") == "POSITIVE"


# ── generate_trade_narrative ──────────────────────────────────────────────────

def test_disabled_returns_none():
    result = generate_trade_narrative(_trade(), cfg={"nlp_journal_enabled": False})
    assert result is None


def test_enabled_returns_narrative_without_api_key():
    # Template-based: no API key needed — returns narrative when enabled
    result = generate_trade_narrative(
        _trade(),
        cfg={"nlp_journal_enabled": True},
    )
    assert result is not None
    assert isinstance(result.summary, str)
    assert len(result.summary) > 20


def test_default_disabled():
    result = generate_trade_narrative(_trade(), cfg={})
    assert result is None


# ── format_narrative ──────────────────────────────────────────────────────────

def test_format_none_returns_empty():
    assert format_narrative(None) == ""


def test_format_contains_trade_id():
    n = TradeNarrative(trade_id=42, summary="Good trade.", sentiment="POSITIVE", model="test")
    out = format_narrative(n)
    assert "42" in out


def test_format_contains_sentiment():
    n = TradeNarrative(trade_id=1, summary="Bad exit.", sentiment="NEGATIVE", model="test")
    out = format_narrative(n)
    assert "NEGATIVE" in out


def test_format_contains_summary():
    n = TradeNarrative(trade_id=1, summary="Trend was strong.", sentiment="POSITIVE", model="test")
    out = format_narrative(n)
    assert "Trend was strong." in out


# ── _build_prompt — negative / breakeven P&L branches ─────────────────────────
# Lines 98-105: elif net_pnl < 0 / else (breakeven)


def test_prompt_negative_pnl():
    trade = _trade()
    trade["net_pnl"] = -1000.0
    trade["exit_price"] = 150.0
    p = _build_prompt(trade)
    assert "NEGATIVE" in p.upper()
    assert "Review entry conditions" in p


def test_prompt_breakeven_zero():
    trade = _trade()
    trade["net_pnl"] = 0.0
    trade["exit_price"] = 200.0
    p = _build_prompt(trade)
    assert "NEUTRAL" in p.upper()
    assert "Breakeven" in p


def test_prompt_breakeven_missing_key():
    trade = _trade()
    trade.pop("net_pnl", None)
    p = _build_prompt(trade)
    assert "NEUTRAL" in p.upper()
    assert "Breakeven" in p


# ── _classify_sentiment — all three branches (lines 122-126) ───────────────────


def test_classify_sentiment_positive():
    assert _classify_sentiment(100.0) == "POSITIVE"


def test_classify_sentiment_negative():
    assert _classify_sentiment(-50.0) == "NEGATIVE"


def test_classify_sentiment_neutral():
    assert _classify_sentiment(0.0) == "NEUTRAL"


# ── generate_trade_narrative — negative PnL end-to-end ─────────────────────────


def test_enabled_negative_pnl_returns_negative_sentiment():
    trade = _trade()
    trade["net_pnl"] = -2000.0
    trade["exit_price"] = 100.0
    result = generate_trade_narrative(trade, cfg={"nlp_journal_enabled": True})
    assert result is not None
    assert result.sentiment == "NEGATIVE"
    assert "Review entry conditions" in result.summary


def test_enabled_zero_pnl_returns_neutral_sentiment():
    trade = _trade()
    trade["net_pnl"] = 0.0
    trade["exit_price"] = 200.0
    result = generate_trade_narrative(trade, cfg={"nlp_journal_enabled": True})
    assert result is not None
    assert result.sentiment == "NEUTRAL"
    assert "Breakeven" in result.summary
