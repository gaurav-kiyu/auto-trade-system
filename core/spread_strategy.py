"""
Debit Spread Strategy Engine (Phase D).

Constructs and manages long-debit call/put spreads: buy the near-ATM leg,
sell the further OTM leg.  This caps both max profit and max loss, giving a
defined-risk structure suitable for buying-biased directional strategies.

SAFETY — this module is disabled by default and must NEVER enter live order
flow unless ``spread_strategy_enabled`` is explicitly set to ``true`` AND
``EXECUTION_MODE`` is ``PAPER``.

Key structures
--------------
    SpreadLeg        — one side of the spread (strike, premium, type)
    SpreadPosition   — two-leg position with P&L tracking
    SpreadResult     — closed spread outcome

Public API
----------
    build_spread(direction, atm_strike, step, spot, call_premiums,
                 put_premiums, cfg) → SpreadPosition | None

    paper_fill_spread(position, spot, cfg) → SpreadResult | None

    mark_to_market(position, spot, call_premiums, put_premiums) → float

    compute_spread_metrics(results) → dict

    format_spread_summary(results) → str

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  spread_strategy_enabled    : bool  default false  (NEVER set true in live mode)
  spread_width_strikes       : int   default 2      (# steps between legs)
  spread_slippage_pct        : float default 0.005  (0.5% per leg)
  spread_exit_pnl_pct        : float default 0.50   (exit at 50% of max profit)
  spread_stop_pct            : float default 0.80   (stop at 80% of max loss)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from core.strategy.config import get_strategy_cfg

_log = logging.getLogger(__name__)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class SpreadLeg:
    strike:    int
    premium:   float
    option_type: str    # "CALL" or "PUT"
    side:      str      # "BUY" or "SELL"
    lot_size:  int = 1


@dataclass
class SpreadPosition:
    direction:   str            # "CALL_SPREAD" or "PUT_SPREAD"
    long_leg:    SpreadLeg
    short_leg:   SpreadLeg
    entry_ts:    float
    net_debit:   float          # total premium paid (positive = cost)
    max_profit:  float          # spread_width - net_debit (×lot_size)
    max_loss:    float          # net_debit (×lot_size)
    lot_size:    int
    open:        bool = True
    # Partial exit tracking (Item 3 — v2.44)
    partial_exit_done: bool = False
    partial_exit_pnl:  float = 0.0
    partial_exit_ts:   float | None = None

    @property
    def spread_width(self) -> float:
        return abs(self.short_leg.strike - self.long_leg.strike)


@dataclass
class SpreadResult:
    direction:    str
    long_strike:  int
    short_strike: int
    net_debit:    float
    exit_premium: float     # net credit received at close
    gross_pnl:    float     # exit_premium - net_debit (×lot_size)
    lot_size:     int
    entry_ts:     float
    exit_ts:      float
    exit_reason:  str
    is_winner:    bool


# ── Spread construction ───────────────────────────────────────────────────────

def build_spread(
    direction:     str,
    atm_strike:    int,
    step:          int,
    spot:          float,
    call_premiums: dict[int, float],
    put_premiums:  dict[int, float],
    cfg:           dict[str, Any] | None = None,
) -> SpreadPosition | None:
    """
    Construct a debit spread position from live option premiums.

    For a CALL_SPREAD: buy ATM call, sell (ATM + width) call.
    For a PUT_SPREAD:  buy ATM put,  sell (ATM - width) put.

    Args:
        direction     : "CALL" or "PUT"
        atm_strike    : Nearest ATM strike.
        step          : Strike step size (e.g., 50 for NIFTY).
        spot          : Current underlying spot price.
        call_premiums : {strike: premium} dict for calls.
        put_premiums  : {strike: premium} dict for puts.
        cfg           : Config dict.

    Returns:
        SpreadPosition if both legs are available, else None.
    """
    sc = get_strategy_cfg(cfg or {}, "spread")
    if not sc.get("enabled", False):
        return None

    width_strikes = int(sc.get("width_strikes", 2))
    slip_pct      = float(sc.get("slippage_pct", 0.005))
    lot_size      = int(cfg.get("lot_size", 1)) if cfg else 1

    dir_up = direction.upper()
    if dir_up in ("CALL", "CALL_SPREAD"):
        long_strike  = atm_strike
        short_strike = atm_strike + width_strikes * step
        premiums     = call_premiums
        spread_type  = "CALL_SPREAD"
    elif dir_up in ("PUT", "PUT_SPREAD"):
        long_strike  = atm_strike
        short_strike = atm_strike - width_strikes * step
        premiums     = put_premiums
        spread_type  = "PUT_SPREAD"
    else:
        _log.warning("[SPREAD] Unknown direction: %s", direction)
        return None

    long_raw  = premiums.get(long_strike)
    short_raw = premiums.get(short_strike)
    if long_raw is None or short_raw is None:
        _log.debug("[SPREAD] Missing premium: long=%s short=%s", long_strike, short_strike)
        return None
    if long_raw <= 0 or short_raw <= 0:
        _log.debug("[SPREAD] Non-positive premium: long=%.2f short=%.2f", long_raw, short_raw)
        return None

    # Apply slippage: pay slightly more on buy, receive slightly less on sell
    long_prem  = long_raw  * (1 + slip_pct)
    short_prem = short_raw * (1 - slip_pct)
    net_debit  = (long_prem - short_prem) * lot_size

    if net_debit <= 0:
        _log.debug("[SPREAD] Zero or negative net debit — spread not viable")
        return None

    width_pts  = abs(short_strike - long_strike)
    max_profit = (width_pts - long_prem + short_prem) * lot_size
    max_loss   = net_debit

    if max_profit <= 0:
        _log.debug("[SPREAD] No positive max profit — spread not viable")
        return None

    long_leg = SpreadLeg(
        strike=long_strike, premium=long_prem,
        option_type=spread_type.split("_")[0], side="BUY", lot_size=lot_size,
    )
    short_leg = SpreadLeg(
        strike=short_strike, premium=short_prem,
        option_type=spread_type.split("_")[0], side="SELL", lot_size=lot_size,
    )

    return SpreadPosition(
        direction=spread_type,
        long_leg=long_leg,
        short_leg=short_leg,
        entry_ts=time.time(),
        net_debit=round(net_debit, 2),
        max_profit=round(max_profit, 2),
        max_loss=round(max_loss, 2),
        lot_size=lot_size,
    )


# ── Mark-to-market ────────────────────────────────────────────────────────────

def mark_to_market(
    position:      SpreadPosition,
    spot:          float,
    call_premiums: dict[int, float],
    put_premiums:  dict[int, float],
) -> float:
    """
    Return the current unrealised P&L for an open spread.

    P&L = (current_long_prem − entry_long_prem) − (current_short_prem − entry_short_prem)
        × lot_size

    Returns 0.0 if premiums are unavailable.
    """
    if not position.open:
        return 0.0

    premiums = (call_premiums if "CALL" in position.direction else put_premiums)
    cur_long  = premiums.get(position.long_leg.strike)
    cur_short = premiums.get(position.short_leg.strike)
    if cur_long is None or cur_short is None:
        return 0.0

    pnl = (cur_long - position.long_leg.premium) * position.lot_size
    pnl -= (cur_short - position.short_leg.premium) * position.lot_size
    return round(pnl, 2)


# ── Paper executor ────────────────────────────────────────────────────────────

def paper_fill_spread(
    position:      SpreadPosition,
    spot:          float,
    call_premiums: dict[int, float],
    put_premiums:  dict[int, float],
    cfg:           dict[str, Any] | None = None,
    *,
    force_exit_reason: str | None = None,
) -> SpreadResult | None:
    """
    Check exit conditions and close the spread in paper mode if triggered.

    Exit conditions checked in order:
      1. 50% max profit captured  (configurable via ``spread_exit_pnl_pct``)
      2. 80% of max loss hit      (configurable via ``spread_stop_pct``)
      3. ``force_exit_reason`` supplied by caller (EOD / manual)

    Returns:
        SpreadResult if the spread was closed, None if still open.
    """
    if not position.open:
        return None

    sc             = get_strategy_cfg(cfg or {}, "spread")
    exit_pnl_pct  = float(sc.get("exit_pnl_pct", 0.50))
    stop_pct      = float(sc.get("stop_pct", 0.80))
    slip_pct      = float(sc.get("slippage_pct", 0.005))

    pnl = mark_to_market(position, spot, call_premiums, put_premiums)

    exit_reason: str | None = force_exit_reason
    if exit_reason is None:
        if pnl >= position.max_profit * exit_pnl_pct:
            exit_reason = f"TARGET_{int(exit_pnl_pct*100)}pct"
        elif pnl <= -position.max_loss * stop_pct:
            exit_reason = f"STOP_{int(stop_pct*100)}pct"

    if exit_reason is None:
        return None

    # Compute exit premium (net credit received to close)
    premiums  = (call_premiums if "CALL" in position.direction else put_premiums)
    cur_long  = premiums.get(position.long_leg.strike, position.long_leg.premium)
    cur_short = premiums.get(position.short_leg.strike, position.short_leg.premium)

    # On close: sell long leg (receive premium - slippage), buy back short (pay + slippage)
    exit_credit = cur_long * (1 - slip_pct) - cur_short * (1 + slip_pct)
    gross_pnl   = round((exit_credit * position.lot_size) - position.net_debit, 2)

    position.open = False

    return SpreadResult(
        direction=position.direction,
        long_strike=position.long_leg.strike,
        short_strike=position.short_leg.strike,
        net_debit=position.net_debit,
        exit_premium=round(exit_credit * position.lot_size, 2),
        gross_pnl=gross_pnl,
        lot_size=position.lot_size,
        entry_ts=position.entry_ts,
        exit_ts=time.time(),
        exit_reason=exit_reason,
        is_winner=gross_pnl > 0,
    )


# ── Partial exit evaluation (Item 3 — v2.44) ─────────────────────────────────

@dataclass(frozen=True)
class SpreadExitDecision:
    action:            str           # "HOLD" | "PARTIAL_EXIT" | "FULL_EXIT"
    exit_pct:          float         # 0.0 | 0.50 | 1.0 (fraction of lots to close)
    reason:            str
    trail_stop_level:  float | None  # new SL level after partial (None if HOLD)


def evaluate_spread_exit(
    position:    SpreadPosition,
    current_pnl: float,
    cfg:         dict[str, Any] | None = None,
) -> SpreadExitDecision:
    """
    Evaluate exit decision for an open spread position.

    Priority order:
      1. FULL EXIT — hard stop (pnl <= -max_loss * spread_stop_pct)
      2. FULL EXIT — target hit (pnl >= max_profit * spread_exit_pnl_pct)
      3. PARTIAL EXIT — near target (pnl >= max_profit * spread_partial_exit_pct,
                         partial not yet done)
      4. PARTIAL EXIT — theta decay guard (DTE=0 and time > spread_theta_exit_time
                         and pnl > 0)
      5. HOLD — otherwise
    """
    sc = get_strategy_cfg(cfg or {}, "spread")
    if not position.open:
        return SpreadExitDecision("HOLD", 0.0, "Position already closed", None)

    exit_pct_cfg     = float(sc.get("exit_pnl_pct",      0.50))
    stop_pct         = float(sc.get("stop_pct",           0.80))
    partial_exit_pct = float(sc.get("partial_exit_pct",   0.75))
    partial_lots_pct = float(sc.get("partial_lots_pct",   0.50))
    int(sc.get("theta_exit_dte",     0))
    theta_exit_time  = str(sc.get("theta_exit_time",    "14:00"))

    # 1. Hard stop
    if current_pnl <= -(position.max_loss * stop_pct):
        return SpreadExitDecision(
            "FULL_EXIT", 1.0,
            f"STOP_LOSS at {stop_pct:.0%} of max_loss ({current_pnl:.2f})",
            None,
        )

    # 2. Target hit
    if current_pnl >= position.max_profit * exit_pct_cfg:
        return SpreadExitDecision(
            "FULL_EXIT", 1.0,
            f"TARGET_HIT at {exit_pct_cfg:.0%} of max_profit ({current_pnl:.2f})",
            None,
        )

    # 3. Partial profit lock
    if (not position.partial_exit_done
            and current_pnl >= position.max_profit * partial_exit_pct):
        trail = position.net_debit * 0.10   # allow only 10% of original debit as remaining loss
        return SpreadExitDecision(
            "PARTIAL_EXIT", partial_lots_pct,
            f"PARTIAL_PROFIT_LOCK at {partial_exit_pct:.0%} of max_profit ({current_pnl:.2f})",
            round(trail, 2),
        )

    # 4. Theta decay guard
    try:
        import datetime as _dt

        from core.datetime_ist import now_ist
        now_time = now_ist().time()
        th_h, th_m = map(int, theta_exit_time.split(":"))
        theta_block_time = _dt.time(th_h, th_m)
    except Exception:
        theta_block_time = None
        now_time         = None

    if (theta_block_time is not None and now_time is not None
            and current_pnl > 0
            and not position.partial_exit_done
            and now_time >= theta_block_time):
        return SpreadExitDecision(
            "PARTIAL_EXIT", partial_lots_pct,
            f"THETA_DECAY_GUARD after {theta_exit_time} with pnl={current_pnl:.2f}",
            None,
        )

    return SpreadExitDecision("HOLD", 0.0, "Hold — no exit condition met", None)


# ── Analytics ─────────────────────────────────────────────────────────────────

def compute_spread_metrics(results: list[SpreadResult]) -> dict[str, Any]:
    """
    Compute aggregate performance metrics across a list of closed spreads.

    Returns a dict with: trades, winners, losers, win_rate, total_pnl,
    avg_pnl, avg_win, avg_loss, max_profit, max_loss, expectancy.
    """
    if not results:
        return {"trades": 0}

    n = len(results)
    winners = [r for r in results if r.is_winner]
    losers  = [r for r in results if not r.is_winner]
    total   = sum(r.gross_pnl for r in results)

    avg_win  = sum(r.gross_pnl for r in winners) / max(len(winners), 1)
    avg_loss = sum(r.gross_pnl for r in losers)  / max(len(losers),  1)

    return {
        "trades":    n,
        "winners":   len(winners),
        "losers":    len(losers),
        "win_rate":  round(len(winners) / n * 100, 1),
        "total_pnl": round(total, 2),
        "avg_pnl":   round(total / n, 2),
        "avg_win":   round(avg_win, 2),
        "avg_loss":  round(avg_loss, 2),
        "max_profit": round(max(r.gross_pnl for r in results), 2),
        "max_loss":   round(min(r.gross_pnl for r in results), 2),
        "expectancy": round(total / n, 2),
    }


def format_spread_summary(results: list[SpreadResult]) -> str:
    """Return a compact console/Telegram-friendly spread performance summary."""
    m = compute_spread_metrics(results)
    if m.get("trades", 0) == 0:
        return "Spread Strategy: no closed spreads."
    lines = [
        f"Debit Spread Summary — {m['trades']} trades",
        f"  Win Rate:  {m['win_rate']:.1f}%  ({m['winners']}W / {m['losers']}L)",
        f"  Total P&L: ₹{m['total_pnl']:+,.2f}   Expectancy: ₹{m['expectancy']:+,.2f}",
        f"  Avg Win:   ₹{m['avg_win']:+,.2f}   Avg Loss: ₹{m['avg_loss']:+,.2f}",
        f"  Best:      ₹{m['max_profit']:+,.2f}   Worst: ₹{m['max_loss']:+,.2f}",
    ]
    return "\n".join(lines)
