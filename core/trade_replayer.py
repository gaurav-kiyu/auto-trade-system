"""
Trade Replay Visualizer (v2.44 Item 14).

Replays any closed trade bar-by-bar in the terminal using an ASCII chart,
showing price context around the entry/exit, signal conditions, and autopsy
verdict.  Falls back to a price-path simulation when yfinance data is
unavailable (offline / stale).

Public API
----------
    replay_trade(trade_id, db_path, frames_to_show, bar_width) → str

    load_trade(trade_id, db_path) → dict | None

    list_trades(db_path, *, last, worst, best, date_str) → list[dict]

    cli entry: python -m core.trade_replayer --id 42
               python -m core.trade_replayer --last 5
               python -m core.trade_replayer --worst 3
               python -m core.trade_replayer --best 3
               python -m core.trade_replayer --date 2024-01-15

Config keys (index_config.defaults.json)
-----------------------------------------
    trade_replayer_frames_to_show : int  default 20
    trade_replayer_bar_width      : int  default 50
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.db_utils import get_connection

_log = logging.getLogger(__name__)

_DEFAULT_DB           = "trades.db"
_DEFAULT_FRAMES       = 20
_DEFAULT_BAR_WIDTH    = 50
_INDEX_SYMBOLS: dict[str, str] = {
    "NIFTY":     "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY":  "NIFTY_FIN_SERVICE.NS",
    "SENSEX":    "^BSESN",
    "MIDCPNIFTY":"^NSEI",
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class ReplayFrame:
    bar_index: int
    timestamp: str
    open:      float
    high:      float
    low:       float
    close:     float
    is_entry:  bool  = False
    is_exit:   bool  = False


@dataclass
class TradeReplay:
    trade_id:     int
    index_name:   str
    direction:    str
    entry_price:  float
    exit_price:   float
    entry_ts:     str
    exit_ts:      str
    net_pnl:      float
    score:        int
    regime:       str
    reason:       str
    frames:       list[ReplayFrame] = field(default_factory=list)
    sl_price:     float = 0.0
    target_price: float = 0.0
    chart:        str   = ""
    verdict:      str   = ""


# ── DB helpers ────────────────────────────────────────────────────────────────

def load_trade(trade_id: int, db_path: str = _DEFAULT_DB) -> dict | None:
    """Load a single trade by id from trades.db."""
    p = Path(db_path)
    if not p.is_file():
        return None
    try:
        conn = get_connection(p, timeout=5)
        try:
            row = conn.execute(
                "SELECT * FROM trades WHERE id = ?", (trade_id,)
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row else None
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as exc:
        _log.warning("[REPLAYER] load_trade(%s) failed: %s", trade_id, exc)
        return None
    except (OSError, ConnectionError, TimeoutError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        _log.warning("[REPLAYER] load_trade(%s) failed: %s", trade_id, exc)
        return None


def list_trades(
    db_path: str = _DEFAULT_DB,
    *,
    last:     int | None = None,
    worst:    int | None = None,
    best:     int | None = None,
    date_str: str | None = None,
) -> list[dict]:
    """Return a list of trade dicts matching the given filter."""
    p = Path(db_path)
    if not p.is_file():
        return []
    try:
        conn = get_connection(p, timeout=5)
        try:
            where  = ["net_pnl IS NOT NULL"]
            params: list[Any] = []
            if date_str:
                where.append("ts LIKE ?")
                params.append(f"{date_str}%")

            if worst:
                sql = (
                    f"SELECT * FROM trades WHERE {' AND '.join(where)} "
                    f"ORDER BY net_pnl ASC LIMIT ?"
                )
                params.append(worst)
            elif best:
                sql = (
                    f"SELECT * FROM trades WHERE {' AND '.join(where)} "
                    f"ORDER BY net_pnl DESC LIMIT ?"
                )
                params.append(best)
            else:
                limit = last if last else 10
                sql = (
                    f"SELECT * FROM trades WHERE {' AND '.join(where)} "
                    f"ORDER BY ts DESC LIMIT ?"
                )
                params.append(limit)

            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        return [dict(r) for r in rows]
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError) as exc:
        _log.warning("[REPLAYER] list_trades failed: %s", exc)
        return []
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
        _log.warning("[REPLAYER] list_trades failed: %s", exc)
        return []


# ── Price data fetcher ────────────────────────────────────────────────────────

def _fetch_price_bars(
    index_name: str,
    entry_ts:   str,
    frames:     int,
) -> list[tuple[str, float, float, float, float]]:
    """
    Fetch (timestamp, open, high, low, close) tuples around entry_ts.

    Returns empty list on any failure so caller can fall back to simulation.
    """
    try:

        import pandas as pd
        import yfinance as yf

        symbol   = _INDEX_SYMBOLS.get(index_name.upper(), "^NSEI")
        entry_dt = pd.Timestamp(entry_ts)
        start    = entry_dt - pd.Timedelta(minutes=frames * 5)
        end      = entry_dt + pd.Timedelta(minutes=frames * 5)

        ticker   = yf.Ticker(symbol)
        df       = ticker.history(
            start=start.strftime("%Y-%m-%d"),
            end=(end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            interval="5m",
        )
        if df is None or df.empty:
            return []

        df.index = pd.to_datetime(df.index)
        df       = df[(df.index >= start) & (df.index <= end)]
        bars     = []
        for ts, row in df.iterrows():
            bars.append((
                str(ts),
                float(row.get("Open",  row.get("Close", 0))),
                float(row.get("High",  row.get("Close", 0))),
                float(row.get("Low",   row.get("Close", 0))),
                float(row.get("Close", 0)),
            ))
        return bars
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError) as exc:
        _log.warning("[REPLAYER] _fetch_price_bars failed: %s", exc)
        return []
    except Exception as exc:
        _log.warning("[REPLAYER] _fetch_price_bars failed (unexpected: %s): %s", type(exc).__name__, exc)
        return []


def _simulate_price_bars(
    entry_price: float,
    exit_price:  float,
    n_frames:    int,
) -> list[tuple[str, float, float, float, float]]:
    """
    Generate a synthetic price path between entry_price and exit_price
    using a simple random walk.  Used as fallback when yfinance is unavailable.
    """
    import random
    random.seed(42)

    move = exit_price - entry_price
    step = move / max(n_frames - 1, 1)
    bars = []
    price = entry_price
    for i in range(n_frames):
        noise = random.gauss(0, abs(step) * 0.3 + entry_price * 0.001)
        close = price + step + noise
        hi    = max(price, close) * (1 + random.uniform(0, 0.003))
        lo    = min(price, close) * (1 - random.uniform(0, 0.003))
        bars.append((f"T+{i}", price, hi, lo, close))
        price = close
    # Force last bar to exit_price
    if bars:
        ts, o, h, low_val, _ = bars[-1]
        bars[-1] = (ts, o, max(h, exit_price), min(low_val, exit_price), exit_price)
    return bars


# ── ASCII chart renderer ──────────────────────────────────────────────────────

def _render_bar_chart(
    frames:      list[ReplayFrame],
    entry_price: float,
    exit_price:  float,
    sl_price:    float,
    target_price: float,
    bar_width:   int = _DEFAULT_BAR_WIDTH,
) -> str:
    """
    Render an ASCII OHLC bar chart.

    Each bar occupies one line.  Entry/exit bars are highlighted.
    Horizontal reference lines show SL and Target.

    Returns a multi-line string ready to print.
    """
    if not frames:
        return "  (no price data available)"

    all_prices = []
    for f in frames:
        all_prices += [f.low, f.high]
    if sl_price > 0:
        all_prices.append(sl_price)
    if target_price > 0:
        all_prices.append(target_price)

    price_min = min(all_prices)
    price_max = max(all_prices)
    price_rng = price_max - price_min
    if price_rng == 0:
        price_rng = price_max * 0.01 or 1.0

    def to_col(p: float) -> int:
        return int((p - price_min) / price_rng * (bar_width - 1))

    lines = []
    # Header
    lines.append(
        f"  {'Low':>8}  {'High':>8}  {'Close':>8}  "
        f"  {price_min:>10.1f}"
        + " " * (bar_width - 22)
        + f"{price_max:>10.1f}"
    )
    lines.append("  " + "-" * (bar_width + 30))

    for f in frames:
        lo_col  = to_col(f.low)
        hi_col  = to_col(f.high)
        cls_col = to_col(f.close)

        row = [" "] * bar_width
        for c in range(lo_col, hi_col + 1):
            row[c] = "─"
        if 0 <= cls_col < bar_width:
            row[cls_col] = "█" if (f.close >= f.open) else "▒"

        # Mark SL / Target lines
        if sl_price > 0:
            sc = to_col(sl_price)
            if 0 <= sc < bar_width and row[sc] == " ":
                row[sc] = "s"
        if target_price > 0:
            tc = to_col(target_price)
            if 0 <= tc < bar_width and row[tc] == " ":
                row[tc] = "T"

        bar_str  = "".join(row)
        marker   = "►" if f.is_entry else ("◄" if f.is_exit else " ")
        ts_short = f.timestamp[:16] if len(f.timestamp) > 16 else f.timestamp
        lines.append(
            f"  {f.low:>8.1f}  {f.high:>8.1f}  {f.close:>8.1f}  "
            f"{marker} {bar_str} {marker}  {ts_short}"
        )

    lines.append("  " + "-" * (bar_width + 30))
    lines.append("  Legend: █=Bullish bar  ▒=Bearish bar  ►=Entry  ◄=Exit  s=SL  T=Target")
    return "\n".join(lines)


# ── Autopsy verdict ───────────────────────────────────────────────────────────

def _verdict(trade: dict) -> str:
    pnl    = float(trade.get("net_pnl") or 0)
    score  = int(trade.get("score") or 0)
    reason = str(trade.get("reason") or "")

    if pnl > 0:
        if score >= 80:
            return "WIN - High-confidence signal confirmed."
        return "WIN - Signal triggered correctly."
    else:
        if score >= 80:
            return "LOSS - High-confidence signal failed. Review regime / IV."
        if "STOP" in reason.upper():
            return "LOSS - Stopped out. SL may be too tight."
        if "THETA" in reason.upper() or "DECAY" in reason.upper():
            return "LOSS - Theta decay erosion. Entry may have been too late."
        return "LOSS - Signal did not follow through."


# ── Main replay function ──────────────────────────────────────────────────────

def replay_trade(
    trade_id:     int,
    db_path:      str = _DEFAULT_DB,
    frames_to_show: int = _DEFAULT_FRAMES,
    bar_width:    int = _DEFAULT_BAR_WIDTH,
    cfg:          dict[str, Any] | None = None,
) -> str:
    """
    Load a trade and return a full ASCII replay string.

    Args:
        trade_id      : Row id in trades.db.
        db_path       : Path to trades.db.
        frames_to_show: Number of price bars to display.
        bar_width     : Width of the ASCII chart in columns.
        cfg           : Config dict (overrides individual params if set).

    Returns:
        Multi-line string ready for print().  Includes header, chart, and verdict.
        Returns an error message string if trade_id is not found.
    """
    c           = cfg or {}
    frames_to_show = int(c.get("trade_replayer_frames_to_show", frames_to_show))
    bar_width      = int(c.get("trade_replayer_bar_width",      bar_width))

    trade = load_trade(trade_id, db_path)
    if trade is None:
        return f"[REPLAY] Trade id={trade_id} not found in {db_path}"

    entry  = float(trade.get("entry")      or 0)
    exit_p = float(trade.get("exit_price") or entry)
    pnl    = float(trade.get("net_pnl")    or 0)
    score  = int(trade.get("score")        or 0)
    entry_ts = str(trade.get("ts")         or "")
    regime   = str(trade.get("regime")     or "UNKNOWN")
    direction = str(trade.get("direction") or "")
    index_name = str(trade.get("index_name") or "")
    reason   = str(trade.get("reason")     or "")

    # Estimate SL / Target from config defaults
    sl_pct     = float(c.get("SL_PCT",     0.30))
    target_pct = float(c.get("TARGET_PCT", 0.60))
    sl_price     = round(entry * (1 - sl_pct),     2)
    target_price = round(entry * (1 + target_pct), 2)

    # Fetch real price bars; fall back to simulation
    raw_bars = _fetch_price_bars(index_name, entry_ts, frames_to_show)
    if not raw_bars:
        raw_bars = _simulate_price_bars(entry, exit_p, frames_to_show)
        source = "SIMULATED"
    else:
        source = "LIVE"
        # Trim to frames_to_show centred on entry
        mid = len(raw_bars) // 2
        half = frames_to_show // 2
        raw_bars = raw_bars[max(0, mid - half): mid + half + 1]

    # Build ReplayFrame list; mark entry at mid, exit at last
    frames: list[ReplayFrame] = []
    entry_marked = False
    for i, (ts, o, h, low_val, c_p) in enumerate(raw_bars):
        is_entry = (not entry_marked) and (
            abs(c_p - entry) / (entry or 1) < 0.005 or i == len(raw_bars) // 2
        )
        is_exit  = (i == len(raw_bars) - 1)
        if is_entry:
            entry_marked = True
        frames.append(ReplayFrame(i, ts, o, h, low_val, c_p, is_entry, is_exit))

    chart = _render_bar_chart(frames, entry, exit_p, sl_price, target_price, bar_width)
    verdict = _verdict(trade)

    # Compose output
    sep = "═" * (bar_width + 34)
    outcome = "WIN ✓" if pnl > 0 else "LOSS ✗"
    lines = [
        sep,
        f"  TRADE REPLAY  •  id={trade_id}  •  {index_name} {direction}  •  {outcome}",
        sep,
        f"  Entry:  ₹{entry:,.2f}  at  {entry_ts[:19]}",
        f"  Exit:   ₹{exit_p:,.2f}  ({reason})",
        f"  P&L:    ₹{pnl:+,.2f}",
        f"  Score:  {score}  |  Regime: {regime}",
        f"  SL:     ₹{sl_price:,.2f}  |  Target: ₹{target_price:,.2f}",
        f"  Price data source: {source}",
        "",
        chart,
        "",
        f"  VERDICT:  {verdict}",
        sep,
    ]
    return "\n".join(lines)


def replay_multiple(
    trades: list[dict],
    db_path: str = _DEFAULT_DB,
    frames_to_show: int = _DEFAULT_FRAMES,
    bar_width: int = _DEFAULT_BAR_WIDTH,
    cfg: dict[str, Any] | None = None,
) -> str:
    """Replay a list of trade dicts, joining results with blank lines."""
    parts = []
    for t in trades:
        tid = int(t.get("id") or 0)
        if tid:
            parts.append(replay_trade(tid, db_path, frames_to_show, bar_width, cfg))
    return "\n\n".join(parts) if parts else "[REPLAY] No trades to display."


# ── Web endpoint helper ───────────────────────────────────────────────────────

def get_replay_json(trade_id: int, db_path: str = _DEFAULT_DB) -> dict:
    """Return a JSON-serialisable replay payload for the web endpoint."""
    trade = load_trade(trade_id, db_path)
    if trade is None:
        return {"error": f"Trade {trade_id} not found"}
    raw_bars = _simulate_price_bars(
        float(trade.get("entry") or 0),
        float(trade.get("exit_price") or trade.get("entry") or 0),
        20,
    )
    return {
        "trade": {k: v for k, v in trade.items()},
        "bars": [
            {"ts": b[0], "open": b[1], "high": b[2], "low": b[3], "close": b[4]}
            for b in raw_bars
        ],
        "verdict": _verdict(trade),
    }


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="python -m core.trade_replayer",
        description="Replay a closed trade bar-by-bar in the terminal.",
    )
    ap.add_argument("--db",    default=_DEFAULT_DB, help="Path to trades.db")
    ap.add_argument("--frames", type=int, default=_DEFAULT_FRAMES)
    ap.add_argument("--width",  type=int, default=_DEFAULT_BAR_WIDTH)

    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--id",    type=int, help="Trade id to replay")
    grp.add_argument("--last",  type=int, metavar="N", help="Last N trades")
    grp.add_argument("--worst", type=int, metavar="N", help="N worst trades by P&L")
    grp.add_argument("--best",  type=int, metavar="N", help="N best trades by P&L")
    grp.add_argument("--date",  help="All trades on YYYY-MM-DD")

    args = ap.parse_args()

    if args.id:
        print(replay_trade(args.id, args.db, args.frames, args.width))
    else:
        kw: dict[str, Any] = {}
        if args.last:  kw["last"]     = args.last
        if args.worst: kw["worst"]    = args.worst
        if args.best:  kw["best"]     = args.best
        if args.date:  kw["date_str"] = args.date
        trades = list_trades(args.db, **kw)
        print(replay_multiple(trades, args.db, args.frames, args.width))


if __name__ == "__main__":
    _cli()


__all__ = [
    "ReplayFrame",
    "TradeReplay",
    "get_replay_json",
    "list_trades",
    "load_trade",
    "replay_multiple",
    "replay_trade",
]

