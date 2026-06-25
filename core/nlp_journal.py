"""
NLP Trade Journal (v2.45 Item 17).

Generates a natural-language post-trade narrative using rule-based templates.
No API keys, no external AI dependency - runs fully offline.

Each closed trade is summarised: what happened, key signals, and a lesson.

Public API
----------
    generate_trade_narrative(trade_data, cfg) → TradeNarrative | None
    format_narrative(narrative)              → str

Config keys
-----------
    nlp_journal_enabled : bool  default false
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class TradeNarrative:
    trade_id:  int | str
    summary:   str
    sentiment: str   # "POSITIVE", "NEGATIVE", "NEUTRAL"
    model:     str   # always "template"


# ── Template helpers ──────────────────────────────────────────────────────────

_EXIT_LABELS = {
    "TARGET":  "hit the profit target",
    "SL":      "stopped out",
    "TRAIL":   "trailed out",
    "TIMEOUT": "timed out",
    "EOD":     "closed at end of day",
    "MANUAL":  "closed manually",
}

_REGIME_ADJ = {
    "TRENDING": "with the trend",
    "CHOPPY":   "in a choppy market",
    "RANGING":  "in a ranging market",
    "VOLATILE": "amid elevated volatility",
}

_SESSION_ADJ = {
    "MORNING":   "during the morning session",
    "MIDDAY":    "during the midday lull",
    "AFTERNOON": "in the afternoon session",
    "POWER":     "in the power hour",
}


def _build_prompt(trade: dict[str, Any]) -> str:
    """Build a structured narrative template from trade fields."""
    direction  = str(trade.get("direction",   "?")).upper()
    regime     = str(trade.get("regime",      "?")).upper()
    session    = str(trade.get("session",     "?")).upper()
    score      = trade.get("score")
    net_pnl    = float(trade.get("net_pnl",  0.0) or 0.0)
    exit_rsn   = str(trade.get("exit_reason","?")).upper()
    hold_mins  = trade.get("hold_mins")
    entry_px   = trade.get("entry_price")
    exit_px    = trade.get("exit_price")

    regime_txt  = _REGIME_ADJ.get(regime,  f"in a {regime.lower()} regime")
    session_txt = _SESSION_ADJ.get(session, f"during the {session.lower()} session")
    exit_txt    = _EXIT_LABELS.get(exit_rsn, f"exited ({exit_rsn.lower()})")
    score_txt   = f"score {score:.0f}" if score is not None else "unknown score"
    hold_txt    = f"after {hold_mins:.0f} min" if hold_mins is not None else ""
    pnl_txt     = f"net P&L {net_pnl:+.0f}"

    parts = [
        f"A {direction} trade was taken {regime_txt} {session_txt} with {score_txt}.",
        f"The position {exit_txt}{' ' + hold_txt if hold_txt else ''}, resulting in {pnl_txt}.",
    ]

    # Entry/exit prices
    if entry_px is not None and exit_px is not None:
        move_pct = (float(exit_px) - float(entry_px)) / float(entry_px) * 100
        parts.append(
            f"Premium moved from {entry_px:.1f} to {exit_px:.1f} ({move_pct:+.1f}%)."
        )

    # Lesson
    if net_pnl > 0:
        lesson = (
            "Signal aligned with regime - entry timing and score confirmation worked well."
        )
        sentiment_tag = "SENTIMENT: POSITIVE"
    elif net_pnl < 0:
        lesson = (
            "Review entry conditions; consider tighter score gate or waiting for clearer regime confirmation."
        )
        sentiment_tag = "SENTIMENT: NEGATIVE"
    else:
        lesson = "Breakeven trade - conditions were mixed."
        sentiment_tag = "SENTIMENT: NEUTRAL"

    parts.append(lesson)
    parts.append(sentiment_tag)
    return " ".join(parts)


def _extract_sentiment(text: str) -> str:
    upper = text.upper()
    if "SENTIMENT: POSITIVE" in upper:
        return "POSITIVE"
    if "SENTIMENT: NEGATIVE" in upper:
        return "NEGATIVE"
    return "NEUTRAL"


def _classify_sentiment(net_pnl: float) -> str:
    if net_pnl > 0:
        return "POSITIVE"
    if net_pnl < 0:
        return "NEGATIVE"
    return "NEUTRAL"


# ── Public API ────────────────────────────────────────────────────────────────

def generate_trade_narrative(
    trade_data: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> TradeNarrative | None:
    """
    Generate a rule-based post-trade narrative from trade data.

    No external API or credentials required.

    Args:
        trade_data: dict with trade fields (direction, regime, pnl, etc.).
        cfg:        config dict.

    Returns:
        TradeNarrative or None if disabled.
    """
    c = cfg or {}
    if not c.get("nlp_journal_enabled", False):
        return None

    text      = _build_prompt(trade_data)
    sentiment = _extract_sentiment(text)
    float(trade_data.get("net_pnl", 0.0) or 0.0)

    return TradeNarrative(
        trade_id=trade_data.get("id", "?"),
        summary=text,
        sentiment=sentiment,
        model="template",
    )


def format_narrative(narrative: TradeNarrative | None) -> str:
    """Format a TradeNarrative for display / Telegram."""
    if narrative is None:
        return ""
    return (
        f"[Trade #{narrative.trade_id} | {narrative.sentiment}]\n"
        f"{narrative.summary}"
    )


__all__ = [
    "TradeNarrative",
    "format_narrative",
    "generate_trade_narrative",
]

