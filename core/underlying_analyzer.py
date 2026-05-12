"""
Underlying Stock Analyzer (v2.45 Item 16).

Analyzes the top constituent stocks of BANKNIFTY (and optionally NIFTY50)
to measure breadth, relative strength, and whether index options entry is
supported by the underlying basket.

Sector breadth > 0.6 → supportive of trending moves.
Sector breadth < 0.4 → mixed / choppy underlying.

Public API
----------
    analyze_banknifty_constituents(cfg) → list[StockAnalysis]
    get_sector_breadth(analyses)        → float
    format_breadth_summary(analyses)    → str

Config keys
-----------
    underlying_analyzer_enabled : bool  default false
    underlying_top_n            : int   default 5
    underlying_index            : str   default "BANKNIFTY"
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)

_BANKNIFTY_CONSTITUENTS = [
    "HDFCBANK.NS", "ICICIBANK.NS", "AXISBANK.NS", "KOTAKBANK.NS",
    "SBIN.NS", "INDUSINDBK.NS", "BANKBARODA.NS", "FEDERALBNK.NS",
    "IDFCFIRSTB.NS", "AUBANK.NS",
]

_NIFTY50_SAMPLE = [
    "RELIANCE.NS", "TCS.NS", "INFY.NS", "HDFC.NS", "HDFCBANK.NS",
    "ICICIBANK.NS", "BAJFINANCE.NS", "LT.NS", "ITC.NS", "TITAN.NS",
]


@dataclass
class StockAnalysis:
    symbol:            str
    price:             float
    change_pct:        float   # today's % change
    volume_ratio:      float   # today vol / 20-day avg vol
    above_ma20:        bool    # price > 20-day SMA
    relative_strength: float   # change_pct relative to index change


def _fetch_stock_data(symbols: list[str]) -> list[StockAnalysis]:
    """
    Fetch price/volume data via yfinance.
    Returns partial list on partial failure.
    """
    try:
        import yfinance as yf
    except ImportError:
        _log.debug("[UNDER] yfinance not available")
        return []

    results: list[StockAnalysis] = []
    for sym in symbols:
        try:
            tk = yf.Ticker(sym)
            hist = tk.history(period="25d", interval="1d", auto_adjust=True)
            if hist.empty or len(hist) < 2:
                continue
            closes = hist["Close"].tolist()
            vols   = hist["Volume"].tolist()

            price   = float(closes[-1])
            prev    = float(closes[-2])
            chg_pct = (price - prev) / prev * 100.0 if prev > 0 else 0.0

            ma20 = sum(closes[-20:]) / min(20, len(closes))
            v20  = sum(vols[-20:]) / min(20, len(vols)) if vols else 1.0
            v_ratio = float(vols[-1]) / v20 if v20 > 0 else 1.0

            results.append(StockAnalysis(
                symbol=sym,
                price=round(price, 2),
                change_pct=round(chg_pct, 3),
                volume_ratio=round(v_ratio, 2),
                above_ma20=price > ma20,
                relative_strength=round(chg_pct, 3),   # refined below
            ))
        except Exception as e:
            _log.debug("[UNDER] %s fetch failed: %s", sym, e)

    # Normalise relative_strength vs median
    if results:
        med = sorted(r.change_pct for r in results)[len(results) // 2]
        for r in results:
            object.__setattr__(r, "relative_strength", round(r.change_pct - med, 3)) \
                if hasattr(r, "__setattr__") else None
            try:
                r.relative_strength = round(r.change_pct - med, 3)
            except Exception:
                pass

    return results


def analyze_banknifty_constituents(
    cfg: dict[str, Any] | None = None,
) -> list[StockAnalysis]:
    """
    Analyze the top N BANKNIFTY constituent stocks.

    Args:
        cfg: config dict.

    Returns:
        List of StockAnalysis sorted by absolute change (largest movers first).
        Empty list if disabled or data unavailable.
    """
    c = cfg or {}
    if not c.get("underlying_analyzer_enabled", False):
        return []

    index = str(c.get("underlying_index", "BANKNIFTY")).upper()
    top_n = int(c.get("underlying_top_n", 5))

    pool = _NIFTY50_SAMPLE if index == "NIFTY" else _BANKNIFTY_CONSTITUENTS
    syms = pool[:top_n]

    analyses = _fetch_stock_data(syms)
    return sorted(analyses, key=lambda a: abs(a.change_pct), reverse=True)


def get_sector_breadth(analyses: list[StockAnalysis]) -> float:
    """
    Return fraction of stocks above their 20-day MA.

    Args:
        analyses: list of StockAnalysis.

    Returns:
        Float 0–1 (1 = all stocks bullish, 0 = all bearish).
    """
    if not analyses:
        return 0.5
    return sum(1 for a in analyses if a.above_ma20) / len(analyses)


def format_breadth_summary(analyses: list[StockAnalysis]) -> str:
    """One-line breadth summary for EOD report / Telegram."""
    if not analyses:
        return "[underlying] data unavailable"
    breadth = get_sector_breadth(analyses)
    label = "BULLISH" if breadth >= 0.6 else "BEARISH" if breadth <= 0.4 else "MIXED"
    top = analyses[0]
    return (
        f"[underlying] breadth={breadth:.0%} {label} | "
        f"top mover {top.symbol}: {top.change_pct:+.2f}%"
    )
