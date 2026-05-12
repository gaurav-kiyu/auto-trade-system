#!/usr/bin/env python3
"""
Deep strategy validation — all 9 analysis tasks.

Usage
-----
  python run_analysis.py --yf-quarter                     # live Yahoo data
  python run_analysis.py --yf-quarter --yf-days 30        # 30-day window
  python run_analysis.py tests/fixtures/replay_minute_bars.csv
  python run_analysis.py --yf-quarter --json              # machine-readable

Output
------
  Task 1  Simulation summary + config
  Task 2  Per-trade signal quality log
  Task 3  Score segment table (Weak / Medium / Strong)
  Task 4  Expectancy analysis (gross, net, per-day)
  Task 5  Directional + breakout analysis
  Task 6  Market regime performance
  Task 7  Risk/reward validation (SL/TP/trail ratio, configured vs actual)
  Task 8  Failure analysis (worst trades + pattern tags)
  Task 9  Verdict + top-3 improvements
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import numpy as np
from core.simulation_engine import (
    SimConfig, SimulationResult, TradeRecord, SegmentStats,
    run_simulation,
)
from core.pure_index_signal import PureIndexRegimeParams

# ── Formatting helpers ────────────────────────────────────────────────────
W   = 72
SEP = "=" * W
SEP2 = "-" * W
LN  = "-" * 44

def _h(title: str) -> None:
    print(f"\n{SEP2}")
    print(f"  {title}")
    print(SEP2)

def _sign(v: float, unit: str = "") -> str:
    return (f"+{v:.2f}" if v >= 0 else f"{v:.2f}") + unit

def _pct(v: float) -> str:
    return f"+{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _bar(wr: float, w: int = 28) -> str:
    n = int(round(wr / 100 * w))
    return "[" + "#" * n + "." * (w - n) + f"] {wr:.1f}%"

def _seg_stat(s: SegmentStats, records: list[TradeRecord]) -> tuple:
    ts = [r for r in records if r.score_segment == s.label]
    w_t = [r.net_pnl for r in ts if r.is_winner]
    l_t = [r.net_pnl for r in ts if not r.is_winner]
    pf  = 0.0
    if l_t:
        pf = round(abs(sum(w_t)) / abs(sum(l_t)), 3) if w_t else 0.0
    wr_v = float(len(w_t) / len(ts) * 100) if ts else 0.0
    avg_w = round(float(np.mean(w_t)), 2) if w_t else 0.0
    avg_l = round(float(np.mean(l_t)), 2) if l_t else 0.0
    exp   = round(wr_v/100 * avg_w - (1 - wr_v/100) * abs(avg_l), 2)
    return wr_v, avg_w, avg_l, pf, exp, len(ts)


# ── Argument parser ───────────────────────────────────────────────────────
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="OPBuying deep strategy analysis")
    p.add_argument("csv", type=Path, nargs="?", default=None)
    p.add_argument("--yf-quarter", action="store_true")
    p.add_argument("--yf-5m",     action="store_true",
                   help="Use 5m bars (60-day window) instead of 1m (30-day)")
    p.add_argument("--yf-symbol", type=str, default="^NSEI")
    p.add_argument("--yf-days",   type=int, default=None,
                   help="Override lookback window (default: 30d for 1m, 60d for 5m)")
    p.add_argument("--threshold", type=int, default=None)
    p.add_argument("--score-gap", type=int, default=None)
    p.add_argument("--symbol",    type=str, default=None)
    p.add_argument("--vix",       type=float, default=None)
    p.add_argument("--dte",       type=int,   default=3)
    p.add_argument("--no-session-skip", action="store_true",
                   help="Disable opening 15-min session skip filter")
    p.add_argument("--tiered", action="store_true",
                   help="Enable tiered adaptive framework (STRONG/MODERATE/WEAK tiers)")
    p.add_argument("--trade-weak", action="store_true",
                   help="Include WEAK-tier signals (score 60-69) when --tiered is set")
    p.add_argument("--adaptive-threshold", action="store_true",
                   help="Shift entry threshold by market regime when --tiered is set")
    p.add_argument("--json",        action="store_true")
    p.add_argument("--live-report", action="store_true",
                   help="Print live-trade performance from trades.db instead of simulation")
    p.add_argument("--live-mode",   type=str, default=None,
                   help="Filter live report by mode (PAPER / LIVE)")
    p.add_argument("--live-days",   type=int, default=None,
                   help="Filter live report to last N days")
    p.add_argument("--live-export", type=str, default=None,
                   help="Export live trades to a JSONL file")
    return p


# ── Config loader ─────────────────────────────────────────────────────────
def _load_config(root: Path) -> dict:
    sig_cfg: dict = {}
    dp = root / "index_config.defaults.json"
    if dp.exists():
        sig_cfg = json.loads(dp.read_text(encoding="utf-8"))
    mp = root / "config.json"
    if mp.exists():
        try:
            mc = json.loads(mp.read_text(encoding="utf-8"))
            for k in (
                "AI_THRESHOLD", "SIGNAL_ENTRY_SCORE_GAP", "ATR_SL_MULTIPLIER",
                "FIB_TP2_RATIO", "ADX_CHOP_THRESHOLD", "ADX_TREND_THRESHOLD",
                "VIX_BLOCK_THRESHOLD", "IV_SPIKE_THRESHOLD", "VOL_RATIO_MIN",
                "BREAKOUT_BONUS", "ADX_PENALTY_THRESHOLD", "ADX_PENALTY_POINTS",
                "INDEX_RSI_BONUS", "INDEX_RSI_PENALTY", "INDEX_RSI_OVERBOUGHT",
                "INDEX_RSI_OVERSOLD", "INDEX_RSI_HEALTHY_HIGH_CALL",
                "INDEX_RSI_HEALTHY_LOW_CALL", "INDEX_RSI_HEALTHY_HIGH_PUT",
                "INDEX_RSI_HEALTHY_LOW_PUT", "OPTION_DELTA_SCALE",
                "OPTION_DTE_DEFAULT", "BACKTEST_VIX", "MACD_BONUS",
            ):
                if k in mc:
                    sig_cfg[k] = mc[k]
        except Exception:
            pass
    return sig_cfg


# ── Print full analysis ───────────────────────────────────────────────────
def _print_analysis(res: SimulationResult, symbol: str) -> None:
    cfg  = res.config
    recs = res.records

    print()
    print(SEP)
    print(f"  STRATEGY EDGE ANALYSIS  |  {symbol}  |  Option Premium Model")
    print(SEP)

    # ─────────────────────────────────────────────────────────────────
    # TASK 1 — Simulation summary
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 1 — SIMULATION SUMMARY")
    print(f"  Config: threshold={cfg.score_threshold}  gap={cfg.score_gap}  "
          f"SL={cfg.sl_atr_mult}x  TP={cfg.tp_atr_mult:.3f}x  "
          f"trail_activate={cfg.trail_activate_pct*100:.0f}%  trail_from_peak={cfg.trail_from_peak_pct*100:.0f}%")
    print(f"  DTE={cfg.dte}d  VIX={cfg.vix}  delta_scale={cfg.delta_scale}x  "
          f"fee/lot=Rs{cfg.fee_per_lot:.0f}  bid-ask=3% round-trip")
    print()
    # Signal pipeline diagnostics — always shown
    attempts = res.signal_attempts
    rejects  = res.signal_rejections
    traded   = res.total_trades
    if attempts > 0:
        top_blocks = sorted(rejects.items(), key=lambda x: -x[1])[:5]
        print(f"  Signal pipeline  ({attempts} bar-level attempts):")
        for reason, cnt in top_blocks:
            pct = cnt / attempts * 100
            print(f"    {reason:<22}: {cnt:>5} ({pct:.1f}%)")
        # In tiered mode tf_mismatch/choppy are soft-converted (not hard blocks),
        # so only count genuinely unrecoverable gates as structural blocks.
        if cfg.use_tiered:
            hard_blocks = ["1m_short","5m_short","15m_short","frame_align","partial_drop","bad_price","iv_spike"]
        else:
            hard_blocks = ["1m_short","5m_short","15m_short","frame_align","partial_drop","tf_mismatch","choppy","bad_price","iv_spike"]
        structural_pass = attempts - sum(rejects.get(r, 0) for r in hard_blocks)
        print(f"    {'→ reached scoring':<22}: {structural_pass:>5} ({structural_pass/attempts*100:.1f}%)")
        print(f"    {'→ above threshold':<22}: {traded:>5} ({traded/attempts*100:.2f}%)")

    # Score distribution for scored-but-rejected bars
    if res.score_distribution:
        total_scored = sum(res.score_distribution.values())
        buckets = sorted(res.score_distribution.items())
        print(f"\n  Score distribution (scored-but-below-threshold, n={total_scored}):")
        # Show as bar chart
        max_cnt = max(v for _, v in buckets)
        for bk, cnt in buckets:
            bar_w = int(cnt / max_cnt * 24)
            pct = cnt / total_scored * 100
            marker = " ← near threshold" if int(bk.split("-")[0]) >= cfg.score_threshold - 10 else ""
            print(f"    score {bk}: {'█' * bar_w}{'░' * (24 - bar_w)} {cnt:>4} ({pct:.1f}%){marker}")
    print()

    if res.total_trades == 0:
        print("  [!] No trades generated.")
        print(f"      Try: python run_analysis.py --yf-quarter --threshold {cfg.score_threshold - 5} --score-gap 0")
        return

    print(f"  {'Total trades':<28}: {res.total_trades}  ({res.wins}W / {res.losses}L)")
    print(f"  {'Win rate':<28}: {_bar(res.win_rate)}")
    print(f"  {'Profit factor':<28}: {res.profit_factor:.3f}  (>1.5 = strong edge)")
    print(f"  {'Avg winner  (net, Rs)':<28}: {res.avg_win_net:>+,.2f}")
    print(f"  {'Avg loser   (net, Rs)':<28}: {res.avg_loss_net:>+,.2f}")
    print(f"  {'Avg winner  (%)':<28}: {res.avg_win_pct:>+.1f}%  on option premium")
    print(f"  {'Avg loser   (%)':<28}: {res.avg_loss_pct:>+.1f}%  on option premium")
    print(f"  {'RR ratio':<28}: {res.rr_ratio:.3f}  (avg_win / |avg_loss|; >1.0 needed)")
    print(f"  {'Avg RR achieved':<28}: {res.avg_rr_achieved:.3f}x")
    print(f"  {'Net expectancy / trade':<28}: Rs{res.expectancy_net:>+,.2f}")
    print(f"  {'Gross expectancy / trade':<28}: Rs{res.expectancy_gross:>+,.2f}")
    print(f"  {'Max drawdown':<28}: {res.max_drawdown_pct:.2f}%")
    print(f"  {'Sharpe ratio':<28}: {res.sharpe:.3f}  (trade-level; >0.5 = acceptable)")
    print(f"  {'Calmar ratio':<28}: {res.calmar:.3f}  (return / drawdown)")
    print(f"  {'Net return':<28}: {_pct(res.net_return_pct)}")
    print(f"  {'Ending capital':<28}: Rs{res.ending_capital:>,.0f}  (start: Rs{res.initial_capital:>,.0f})")

    # ─────────────────────────────────────────────────────────────────
    # TASK 2 — Per-trade signal quality log
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 2 — SIGNAL QUALITY LOG  (all trades)")
    hdr = f"  {'#':>3}  {'Time':>16}  {'Dir':>4}  {'Sc':>4}  {'Type':<10}  {'Regime':<9}  {'Seg':<16}  {'PnL(Rs)':>9}  {'%Pnl':>7}  {'RR':>5}  {'Exit':<12}  Features"
    print(hdr)
    print(f"  {'-'*3}  {'-'*16}  {'-'*4}  {'-'*4}  {'-'*10}  {'-'*9}  {'-'*16}  {'-'*9}  {'-'*7}  {'-'*5}  {'-'*12}  --------")
    for r in recs:
        side     = "CE" if r.direction == "CALL" else "PE"
        feat_str = ",".join(r.features_triggered[:4]) or "—"
        marker   = "+" if r.is_winner else "-"
        print(f"  {r.trade_id:>3}  {r.entry_time[:16]:>16}  {side:>4}  "
              f"{r.score:>4}  {r.signal_type:<10}  {r.regime:<9}  "
              f"{r.score_segment:<16}  {marker}Rs{abs(r.net_pnl):>7,.0f}  "
              f"{r.pct_pnl:>+6.1f}%  {r.rr_achieved:>5.2f}  "
              f"{r.exit_reason:<12}  {feat_str}")

    # ─────────────────────────────────────────────────────────────────
    # TASK 3 — Score segment analysis
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 3 — SCORE SEGMENT ANALYSIS")
    print(f"  {'Segment':<18} {'N':>4} {'WR':>8} {'Avg Win':>10} {'Avg Loss':>10} "
          f"{'Exp/trade':>11} {'PF':>7}  Bar")
    print(f"  {LN}")
    for seg_key in ["Weak (60-69)", "Moderate (70-79)", "Strong (80+)"]:
        s = res.by_segment.get(seg_key)
        if s and s.trades > 0:
            wr, avg_w, avg_l, pf, exp, n = _seg_stat(s, recs)
            print(f"  {seg_key:<18} {n:>4} {wr:>7.1f}%  Rs{avg_w:>+7,.0f}  Rs{avg_l:>+7,.0f}  "
                  f"Rs{exp:>+8,.0f}  {pf:>6.3f}  {_bar(wr, 18)}")
        else:
            print(f"  {seg_key:<18} {'0':>4}  — no trades in this segment")
    print()
    print("  Interpretation:")
    print("  Strong (80+) should have the highest win rate and best expectancy.")
    print("  If Weak (60-69) has negative expectancy → raise threshold to 70 or score_gap=5.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 4 — Expectancy analysis
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 4 — EXPECTANCY ANALYSIS")
    wr_f = res.win_rate / 100
    lr_f = 1 - wr_f
    print(f"  Formula: E = WR × AvgWin − LR × |AvgLoss|")
    print(f"           E = {wr_f:.2f} × Rs{res.avg_win_net:,.2f} − {lr_f:.2f} × Rs{abs(res.avg_loss_net):,.2f}")
    print(f"  Gross expectancy : Rs{res.expectancy_gross:>+,.2f} / trade")
    print(f"  Fees per trade   : Rs{cfg.fee_per_lot:.0f} + ~Rs{res.avg_win_net * 0.03:.0f} bid-ask (est.)")
    print(f"  Net expectancy   : Rs{res.expectancy_net:>+,.2f} / trade")
    print()

    # Per-day P&L
    if res.daily_pnl:
        day_vals = list(res.daily_pnl.values())
        avg_daily = round(float(np.mean(day_vals)), 2)
        pos_days  = sum(1 for v in day_vals if v > 0)
        neg_days  = sum(1 for v in day_vals if v < 0)
        print(f"  Per-day analysis ({len(day_vals)} trading days with trades):")
        print(f"    Avg daily PnL    : Rs{avg_daily:>+,.2f}")
        print(f"    Positive days    : {pos_days}")
        print(f"    Negative days    : {neg_days}")
        if len(day_vals) > 1:
            best_day  = max(res.daily_pnl, key=res.daily_pnl.get)
            worst_day = min(res.daily_pnl, key=res.daily_pnl.get)
            print(f"    Best day         : {best_day}  Rs{res.daily_pnl[best_day]:>+,.2f}")
            print(f"    Worst day        : {worst_day}  Rs{res.daily_pnl[worst_day]:>+,.2f}")
    print()
    if res.expectancy_net > 0:
        monthly_est = res.expectancy_net * res.total_trades
        print(f"  Monthly estimate ({res.total_trades} trades): Rs{monthly_est:>+,.0f}")
    else:
        print(f"  [!] Negative net expectancy — strategy is losing money on average.")
        print(f"      Need higher WR or better RR to reach breakeven.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 5 — Directional + breakout analysis
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 5 — DIRECTIONAL & BREAKOUT ANALYSIS")
    print(f"  {'Direction':<16} {'N':>4} {'WR':>8} {'Avg PnL':>10} {'Avg %':>8}")
    print(f"  {LN}")
    for d_key in ("CALL", "PUT"):
        s = res.by_direction.get(d_key)
        if s and s.trades > 0:
            avg_pct = round(float(np.mean(s.pct_pnls)), 2) if s.pct_pnls else 0.0
            print(f"  {d_key:<16} {s.trades:>4} {s.win_rate:>7.1f}%  Rs{s.avg_net:>+8,.0f}  {avg_pct:>+7.1f}%")
    print()
    print(f"  {'Breakout':<16} {'N':>4} {'WR':>8} {'Avg PnL':>10}")
    print(f"  {LN}")
    for b_key in ("Breakout", "No-Breakout"):
        s = res.by_breakout.get(b_key)
        if s and s.trades > 0:
            print(f"  {b_key:<16} {s.trades:>4} {s.win_rate:>7.1f}%  Rs{s.avg_net:>+8,.0f}")
    bk = res.by_breakout.get("Breakout")
    nb = res.by_breakout.get("No-Breakout")
    if bk and nb and bk.trades > 0 and nb.trades > 0:
        diff = bk.win_rate - nb.win_rate
        print(f"\n  Breakout edge: {_sign(diff, '%')} win-rate advantage for breakout signals.")
        if diff > 10:
            print("  [+] Strong breakout filter — keep BREAKOUT_BONUS high (8+)")
        elif diff < 0:
            print("  [-] No breakout edge in this period — may be mean-reversion market")

    # CALL vs PUT insight
    call_s = res.by_direction.get("CALL")
    put_s  = res.by_direction.get("PUT")
    call_n = call_s.trades if call_s else 0
    put_n  = put_s.trades  if put_s  else 0
    total_n = call_n + put_n
    if total_n > 0:
        print(f"\n  CALL/PUT split: {call_n/total_n*100:.0f}% CALL / {put_n/total_n*100:.0f}% PUT")
        if call_n / max(total_n, 1) > 0.80:
            print("  [!] Heavy CALL bias — test window is mostly bullish.")
            print("      Run on 2025-Oct–Dec (bear period) to validate PUT performance.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 6 — Market regime analysis
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 6 — MARKET REGIME PERFORMANCE")
    print(f"  {'Regime':<12} {'N':>4} {'WR':>8} {'Avg PnL':>10}  Verdict")
    print(f"  {LN}")
    regime_verdicts = {
        "TRENDING": "Best regime — follow trend signals",
        "NEUTRAL":  "Moderate — trade only confirmed signals",
        "CHOPPY":   "Worst regime — consider blocking entries",
        "EVENT":    "Avoid — extreme vol, unpredictable",
    }
    for rg in ("TRENDING", "NEUTRAL", "CHOPPY", "EVENT"):
        s = res.by_regime.get(rg)
        if s and s.trades > 0:
            verdict = regime_verdicts.get(rg, "")
            print(f"  {rg:<12} {s.trades:>4} {s.win_rate:>7.1f}%  Rs{s.avg_net:>+8,.0f}  {verdict}")
    for rg, s in res.by_regime.items():
        if rg not in regime_verdicts and s.trades > 0:
            print(f"  {rg:<12} {s.trades:>4} {s.win_rate:>7.1f}%  Rs{s.avg_net:>+8,.0f}")
    print()
    choppy_s = res.by_regime.get("CHOPPY")
    trend_s  = res.by_regime.get("TRENDING")
    if choppy_s and choppy_s.trades > 0 and trend_s and trend_s.trades > 0:
        if choppy_s.win_rate < trend_s.win_rate - 15:
            print("  [+] TRENDING >> CHOPPY — regime filter is effective.")
            print("      Consider adding ADX_MIN_FOR_ENTRY to block all NEUTRAL entries too.")
        elif choppy_s.win_rate >= trend_s.win_rate:
            print("  [!] CHOPPY performs as well as TRENDING — data period may be range-bound.")
            print("      The strategy might have mean-reversion characteristics.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 6b — Tier analytics (shown only in --tiered mode)
    # ─────────────────────────────────────────────────────────────────
    if cfg.use_tiered and res.by_tier:
        _h("TASK 6b — TIER PERFORMANCE ANALYSIS")
        tier_order = ["STRONG", "MODERATE", "WEAK"]
        print(f"  {'Tier':<10} {'N':>4} {'WR':>8} {'Avg Net':>10} {'Avg PnL%':>9} {'Expectancy':>12}  Position")
        print(f"  {LN}")
        from core.tier_engine import TIER_RULES
        for t in tier_order:
            s = res.by_tier.get(t)
            if s and s.trades > 0:
                t_recs = [r for r in recs if getattr(r, "tier", "") == t]
                w_net  = [r.net_pnl for r in t_recs if r.is_winner]
                l_net  = [r.net_pnl for r in t_recs if not r.is_winner]
                exp_t  = round(s.win_rate/100 * (float(np.mean(w_net)) if w_net else 0)
                               - (1 - s.win_rate/100) * abs(float(np.mean(l_net)) if l_net else 0), 2)
                avg_pnl = round(float(np.mean(s.pct_pnls)), 1) if s.pct_pnls else 0.0
                rules  = TIER_RULES.get(t)
                pos_str = f"{int(rules.position_pct*100)}% lots" if rules else ""
                print(f"  {t:<10} {s.trades:>4} {s.win_rate:>7.1f}%  Rs{s.avg_net:>+8,.0f}  {avg_pnl:>+7.1f}%  Rs{exp_t:>+9,.0f}  {pos_str}")
        print()
        # Score-vs-outcome correlation
        if len(recs) >= 3:
            scores  = np.array([r.score for r in recs])
            outcomes = np.array([1 if r.is_winner else 0 for r in recs])
            if np.std(scores) > 0:
                corr = float(np.corrcoef(scores, outcomes)[0, 1])
                corr_str = f"+{corr:.3f}" if corr >= 0 else f"{corr:.3f}"
                quality = "positive edge" if corr > 0.1 else ("near-zero" if abs(corr) < 0.05 else "negative — investigate")
                print(f"  Score vs Win correlation: {corr_str}  ({quality})")
        # Soft-block impact
        soft_recs = [r for r in recs if getattr(r, "soft_blocks", [])]
        if soft_recs:
            hard_recs = [r for r in recs if not getattr(r, "soft_blocks", [])]
            soft_wr = sum(1 for r in soft_recs if r.is_winner) / len(soft_recs) * 100
            hard_wr = sum(1 for r in hard_recs if r.is_winner) / len(hard_recs) * 100 if hard_recs else 0
            print(f"  Soft-block trades: {len(soft_recs)} (WR {soft_wr:.1f}%)  vs clean: {len(hard_recs)} (WR {hard_wr:.1f}%)")
            if soft_wr < hard_wr - 10:
                print("  [+] Soft blocks correctly penalise weaker setups.")
            elif soft_wr >= hard_wr:
                print("  [?] Soft-block trades performing as well as clean — consider tightening penalties.")
        print()

    # ─────────────────────────────────────────────────────────────────
    # TASK 7 — Risk/reward validation
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 7 — RISK / REWARD VALIDATION")
    if recs:
        sl_hits  = sum(1 for r in recs if r.exit_reason == "stop_loss")
        tp_hits  = sum(1 for r in recs if r.exit_reason == "take_profit")
        trl_hits = sum(1 for r in recs if r.exit_reason == "trail_sl")
        time_out = sum(1 for r in recs if r.exit_reason == "time_exit")
        total    = len(recs)

        print(f"  Exit breakdown:")
        print(f"    SL hit       : {sl_hits:>3} ({sl_hits/total*100:.0f}%)  — pure loss")
        print(f"    TP hit       : {tp_hits:>3} ({tp_hits/total*100:.0f}%)  — full target achieved")
        print(f"    Trail SL hit : {trl_hits:>3} ({trl_hits/total*100:.0f}%)  — partial profit (trailing)")
        print(f"    Time exit    : {time_out:>3} ({time_out/total*100:.0f}%)  — held to max_bars limit")
        print()

        # Configured vs actual RR
        configured_rr = cfg.tp_atr_mult / cfg.sl_atr_mult
        print(f"  RR configured  : {cfg.sl_atr_mult:.2f}x SL / {cfg.tp_atr_mult:.3f}x TP = {configured_rr:.2f}:1 target")
        print(f"  RR actual      : {res.avg_rr_achieved:.3f}x  (avg across all trades)")
        print(f"  RR winners     : {float(np.mean([r.rr_achieved for r in recs if r.is_winner])):.3f}x" if [r for r in recs if r.is_winner] else "")
        print(f"  RR losers      : {float(np.mean([r.rr_achieved for r in recs if not r.is_winner])):.3f}x" if [r for r in recs if not r.is_winner] else "")
        print()

        # Trailing SL effectiveness
        if trl_hits > 0:
            trail_wins = sum(1 for r in recs if r.exit_reason == "trail_sl" and r.net_pnl > 0)
            print(f"  Trailing SL: {trl_hits} exits  ({trail_wins} profitable)")
            avg_trail_pnl = float(np.mean([r.net_pnl for r in recs if r.exit_reason == "trail_sl"]))
            print(f"  Avg trail exit PnL: Rs{avg_trail_pnl:>+,.2f}")
            if trail_wins / trl_hits > 0.5:
                print(f"  [+] Trailing SL is locking in profits effectively")
            else:
                print(f"  [-] Trail SL exits are mostly negative — activate level too tight")
                print(f"      Consider increasing trail_activate_pct from {cfg.trail_activate_pct*100:.0f}% to {cfg.trail_activate_pct*100+10:.0f}%")
        else:
            print(f"  Trailing SL: not triggered (trail_activate={cfg.trail_activate_pct*100:.0f}% premium gain needed)")
            print(f"  This is normal if no trade reached {cfg.trail_activate_pct*100:.0f}%+ premium gain intra-trade.")

        # Breakeven analysis
        needed_wr = abs(res.avg_loss_net) / (abs(res.avg_loss_net) + res.avg_win_net) * 100 if res.avg_win_net > 0 else 0
        print(f"\n  Breakeven WR needed : {needed_wr:.1f}%  (given current RR structure)")
        print(f"  Actual WR           : {res.win_rate:.1f}%")
        edge_pct = res.win_rate - needed_wr
        print(f"  WR edge             : {_sign(edge_pct, '%')}")
        if edge_pct > 5:
            print(f"  [+] Strategy has WR edge above breakeven — positive expectancy potential")
        elif edge_pct > 0:
            print(f"  [~] WR barely above breakeven — fees erode the edge; needs higher confidence entries")
        else:
            print(f"  [-] WR below breakeven — need to improve either WR or RR")

    # ─────────────────────────────────────────────────────────────────
    # TASK 8 — Failure analysis
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 8 — FAILURE ANALYSIS")

    # Feature edge table
    print("  Feature presence in WINNERS vs LOSERS:")
    print(f"  {'Feature':<20} {'Winners%':>9} {'Losers%':>9}  {'Edge':>7}  Signal")
    print(f"  {LN}")
    for feat, stats in res.feature_edge.items():
        if stats["with_n"] + stats["sans_n"] < 2:
            continue
        w_wr   = stats["with_wr"]
        s_wr   = stats["sans_wr"]
        edge   = round(w_wr - s_wr, 1)
        signal = ""
        if abs(edge) >= 15:
            signal = "<-- STRONG EDGE" if edge > 0 else "<-- HURTS"
        elif abs(edge) >= 8:
            signal = "<-- moderate" if edge > 0 else "<-- weak"
        print(f"  {feat:<20} {w_wr:>8.1f}%  {s_wr:>8.1f}%  {_sign(edge, '%'):>7}  {signal}")

    # Failure tag frequency
    all_tags: dict[str, int] = {}
    for r in recs:
        if not r.is_winner:
            for t in r.failure_tags:
                all_tags[t] = all_tags.get(t, 0) + 1
    if all_tags:
        print(f"\n  Failure condition frequency (losing trades only):")
        for tag, cnt in sorted(all_tags.items(), key=lambda x: -x[1]):
            pct_of_losses = cnt / res.losses * 100 if res.losses else 0
            print(f"    {tag:<22} {cnt:>3} ({pct_of_losses:.0f}% of losses)")
    else:
        print("\n  No losing trades to analyse.")

    # Worst 5 trades
    print(f"\n  Worst 5 trades:")
    print(f"  {'#':>3}  {'Time':>16}  {'Dir':>4}  {'Sc':>4}  {'Regime':<9}  "
          f"{'PnL':>9}  {'Bars':>5}  {'Exit':<12}  Failure tags")
    print(f"  {'-'*70}")
    for r in res.worst_trades:
        side = "CE" if r.direction == "CALL" else "PE"
        tags = ",".join(r.failure_tags) or "—"
        print(f"  {r.trade_id:>3}  {r.entry_time[:16]:>16}  {side:>4}  "
              f"{r.score:>4}  {r.regime:<9}  Rs{r.net_pnl:>+7,.0f}  "
              f"{r.bars_held:>5}  {r.exit_reason:<12}  {tags}")

    # Pattern summary
    print(f"\n  Common failure patterns:")
    top_tags = sorted(all_tags.items(), key=lambda x: -x[1])[:3]
    for tag, cnt in top_tags:
        explanations = {
            "no_breakout":     "Entries without momentum confirmation — add breakout gate",
            "rsi_extreme":     "RSI overbought/oversold at entry — RSI bonus is not firing",
            "low_adx":         "Weak trend at entry — increase ADX_TREND_THRESHOLD",
            "low_volume":      "Below-average volume — add vol_ratio >= 1.2 hard gate",
            "time_exit_loss":  "Trade didn't move within time limit — TP too far or choppy",
            "weak_signal":     "Score 65-74 trades underperform — raise score threshold",
        }
        print(f"    [{cnt}× ] {tag}: {explanations.get(tag, '')}")

    # ─────────────────────────────────────────────────────────────────
    # TASK 9 — Verdict + top-3 improvements
    # ─────────────────────────────────────────────────────────────────
    _h("TASK 9 — FINAL VERDICT")

    print(f"  {'─'*44}")
    print(f"  SUMMARY TABLE")
    print(f"  {'─'*44}")
    print(f"  Total trades    : {res.total_trades}")
    print(f"  Win rate        : {res.win_rate:.1f}%")
    print(f"  Profit factor   : {res.profit_factor:.3f}")
    print(f"  Net expectancy  : Rs{res.expectancy_net:>+,.2f} / trade")
    print(f"  Net return      : {_pct(res.net_return_pct)}")
    print(f"  Max drawdown    : {res.max_drawdown_pct:.2f}%")
    print(f"  Sharpe          : {res.sharpe:.3f}")
    print(f"  {'─'*44}")
    print()

    # Verdict logic
    has_edge   = res.profit_factor > 1.0 and res.expectancy_net > 0
    strong_edge= res.profit_factor > 1.5 and res.win_rate >= 55 and res.rr_ratio >= 1.3
    marginal   = res.profit_factor > 1.0 and res.expectancy_net > 0 and not strong_edge
    no_edge    = not has_edge

    if strong_edge:
        print("  VERDICT: PROFITABLE — Strong demonstrable edge")
        print("  Conditions: TRENDING or NEUTRAL regime, score >= 75, breakout confirmed")
    elif marginal:
        print("  VERDICT: MARGINALLY PROFITABLE — Edge exists but fragile")
        print("  Conditions: Only take CONFIRMED (75+) or STRONG (83+) signals")
        print("              Avoid CHOPPY regime; filter to breakout_ok=True")
    else:
        print("  VERDICT: NOT PROFITABLE in this configuration")
        print("  Root causes identified in Task 8 above")

    print()
    print("  TOP 3 IMPROVEMENTS:")
    improvements: list[str] = []

    # Auto-generate improvements from data
    weak_seg = res.by_segment.get("Weak (60-69)")
    if weak_seg and weak_seg.trades > 0 and weak_seg.win_rate < 45:
        improvements.append(
            f"1. Raise threshold to 70 (or score_gap=5) — Weak (60-69) "
            f"win rate is {weak_seg.win_rate:.0f}%, dragging overall performance"
        )
    elif res.win_rate < 50:
        improvements.append(
            f"1. Tighten entry filter — win rate {res.win_rate:.1f}% below 50%. "
            f"Use --threshold 70 --score-gap 5 to filter borderline signals"
        )

    if res.rr_ratio < 1.2:
        improvements.append(
            f"2. Improve RR structure — actual RR {res.rr_ratio:.2f} < 1.2. "
            f"Raise TP to {cfg.tp_atr_mult * 1.2:.2f}x ATR, or use partial exit at "
            f"TP1 (0.618x ATR) to bank early profits"
        )
    elif "no_breakout" in all_tags and all_tags.get("no_breakout", 0) / max(res.losses, 1) > 0.5:
        improvements.append(
            "2. Add hard breakout gate — >50% of losses had no breakout. "
            "Block entries where breakout_ok=False regardless of score"
        )

    choppy_s = res.by_regime.get("CHOPPY")
    if choppy_s and choppy_s.trades > 0 and choppy_s.avg_net < -100:
        improvements.append(
            f"3. Block CHOPPY regime entirely — {choppy_s.trades} trades, "
            f"avg loss Rs{abs(choppy_s.avg_net):,.0f}. "
            "Add regime==CHOPPY → skip entry logic in index_trader.py"
        )
    elif "time_exit_loss" in all_tags and all_tags.get("time_exit_loss", 0) > 2:
        improvements.append(
            f"3. Reduce max_bars_in_trade — {all_tags['time_exit_loss']} time-exit losses. "
            "Cut from 40 to 25 bars, or add intra-trade momentum check at bar 20"
        )
    elif len(improvements) < 3:
        improvements.append(
            "3. Add real NSE option chain data (PCR + OI) — synthetic OI caps scores "
            "at 75 max (no SmartMoney +10 or PCR +5). Real data unlocks full 83-95 range"
        )

    if len(improvements) < 3:
        improvements.append(
            f"{len(improvements)+1}. Test on bear-market window (eg. Oct–Nov 2024 NIFTY correction) "
            "to validate PUT signal performance and ensure balanced CALL/PUT edge"
        )

    for imp in improvements[:3]:
        print(f"  {imp}")

    print()
    print(f"  Next steps:")
    print(f"    python run_analysis.py --yf-quarter --threshold 70 --score-gap 5")
    print(f"    python run_analysis.py --yf-quarter --yf-symbol ^NSEBANK  (BankNifty)")
    print(f"    python run_backtest.py --yf-quarter                        (comparison mode)")
    print()
    print(SEP)
    print("  END OF ANALYSIS")
    print(SEP)
    print()


# ── JSON output ───────────────────────────────────────────────────────────
def _to_json(res: SimulationResult) -> dict:
    def _seg_to_dict(s: SegmentStats) -> dict:
        return {"trades": s.trades, "wins": s.wins, "win_rate": s.win_rate, "avg_net": s.avg_net}
    return {
        "summary": {
            "total_trades": res.total_trades, "wins": res.wins, "losses": res.losses,
            "win_rate": res.win_rate, "profit_factor": res.profit_factor,
            "expectancy_net": res.expectancy_net, "expectancy_gross": res.expectancy_gross,
            "avg_win_net": res.avg_win_net, "avg_loss_net": res.avg_loss_net,
            "avg_win_pct": res.avg_win_pct, "avg_loss_pct": res.avg_loss_pct,
            "rr_ratio": res.rr_ratio, "avg_rr_achieved": res.avg_rr_achieved,
            "net_return_pct": res.net_return_pct, "max_drawdown_pct": res.max_drawdown_pct,
            "sharpe": res.sharpe, "calmar": res.calmar,
            "ending_capital": res.ending_capital,
        },
        "by_segment":   {k: _seg_to_dict(v) for k, v in res.by_segment.items()},
        "by_regime":    {k: _seg_to_dict(v) for k, v in res.by_regime.items()},
        "by_direction": {k: _seg_to_dict(v) for k, v in res.by_direction.items()},
        "by_breakout":  {k: _seg_to_dict(v) for k, v in res.by_breakout.items()},
        "by_exit":      res.by_exit,
        "feature_edge": res.feature_edge,
        "daily_pnl":    res.daily_pnl,
        "failure_tags": {k: v for k, v in sorted(
            {t: sum(1 for r in res.records if not r.is_winner and t in r.failure_tags)
             for t in ["no_breakout","rsi_extreme","low_adx","low_volume","weak_signal","time_exit_loss"]}.items(),
            key=lambda x: -x[1])},
        "worst_trades": [
            {"trade_id": r.trade_id, "entry_time": r.entry_time, "direction": r.direction,
             "score": r.score, "net_pnl": r.net_pnl, "exit_reason": r.exit_reason,
             "regime": r.regime, "failure_tags": r.failure_tags}
            for r in res.worst_trades],
    }


# ── Main ──────────────────────────────────────────────────────────────────
def main() -> int:
    args = _build_parser().parse_args()

    # ── Live-trade performance report (short-circuit before simulation) ───
    if getattr(args, "live_report", False):
        from core.performance_metrics import print_report, export_jsonl, load_trades
        db = ROOT / "trades.db"
        print_report(str(db), mode=args.live_mode, days=args.live_days)
        if args.live_export:
            trades = load_trades(str(db), mode=args.live_mode, days=args.live_days)
            export_jsonl(trades, args.live_export)
            print(f"Exported {len(trades)} trades to {args.live_export}")
        return 0

    # Load data
    if args.yf_quarter:
        use_5m = getattr(args, "yf_5m", False)
        if use_5m:
            from core.yf_bar_fetch import fetch_5m_bars_chunked_yfinance
            eff = min(max(1, int(args.yf_days or 60)), 60)
            print(f"[analysis] Fetching {args.yf_symbol!r} {eff}d 5m bars (60-day window)...", file=sys.stderr)
            df = fetch_5m_bars_chunked_yfinance(str(args.yf_symbol), calendar_days=eff)
        else:
            from core.yf_bar_fetch import fetch_1m_bars_chunked_yfinance
            eff = min(max(1, int(args.yf_days or 30)), 30)
            print(f"[analysis] Fetching {args.yf_symbol!r} {eff}d 1m bars...", file=sys.stderr)
            df = fetch_1m_bars_chunked_yfinance(str(args.yf_symbol), calendar_days=eff)
        print(f"[analysis] Loaded {len(df)} bars  {df.index.min()} -> {df.index.max()}", file=sys.stderr)
    else:
        if not args.csv or not args.csv.is_file():
            _build_parser().error("Provide a CSV or --yf-quarter")
        from core.backtest_engine import CsvReplaySource, ReplayConfig
        src = CsvReplaySource(args.csv, ReplayConfig(warmup_bars=30))
        df  = src.load()

    # Config
    sig_cfg = _load_config(ROOT)
    thr = int(args.threshold) if args.threshold is not None else int(sig_cfg.get("AI_THRESHOLD", 65))
    gap = int(args.score_gap) if args.score_gap is not None else int(sig_cfg.get("SIGNAL_ENTRY_SCORE_GAP", 0))
    vix = float(args.vix) if args.vix else float(sig_cfg.get("BACKTEST_VIX", 14.0))
    skip_open = 0 if getattr(args, "no_session_skip", False) else 15

    symbol = args.symbol or (
        args.yf_symbol.upper().replace("^", "").replace("NSE:", "") if args.yf_quarter else "NIFTY"
    )
    if "NSEI" in symbol or symbol == "NIFTY50": symbol = "NIFTY"
    elif "NSEBANK" in symbol:                   symbol = "BANKNIFTY"

    regime = PureIndexRegimeParams(
        vix_block_threshold = float(sig_cfg.get("VIX_BLOCK_THRESHOLD",  35)),
        adx_trend_threshold = float(sig_cfg.get("ADX_TREND_THRESHOLD",  20)),
        adx_chop_threshold  = float(sig_cfg.get("ADX_CHOP_THRESHOLD",   14)),
    )

    # Tiered adaptive flags
    use_tiered           = getattr(args, "tiered", False)
    trade_weak           = getattr(args, "trade_weak", False)
    adaptive_thr_enabled = getattr(args, "adaptive_threshold", False)

    # For 5m data, scale bar counts: 1 5m bar ≈ 5 1m bars
    bar_scale = 5 if getattr(args, "yf_5m", False) else 1
    sim_cfg = SimConfig(
        score_threshold           = thr,
        score_gap                 = gap,
        vix                       = vix,
        dte                       = int(args.dte),
        sl_atr_mult               = float(sig_cfg.get("ATR_SL_MULTIPLIER",  1.2)),
        tp_atr_mult               = float(sig_cfg.get("FIB_TP2_RATIO",      1.618)),
        delta_scale               = float(sig_cfg.get("OPTION_DELTA_SCALE", 1.5)),
        use_option_model          = True,
        trail_activate_pct        = 0.30,
        trail_from_peak_pct       = 0.20,
        cooldown_bars             = max(6, 30 // bar_scale),
        max_bars_in_trade         = max(8, 40 // bar_scale),
        warmup_bars               = max(10, 35 // bar_scale),
        session_open_skip_minutes = skip_open,
        use_tiered                = use_tiered,
        trade_weak                = trade_weak,
        adaptive_threshold_enabled = adaptive_thr_enabled,
    )

    mode_str  = "5m-bar" if getattr(args, "yf_5m", False) else "1m-bar"
    tier_str  = "  [TIERED]" if use_tiered else ""
    skip_str  = f"  session_open_skip={skip_open}min"
    print(f"[analysis] Running simulation ({symbol}, {mode_str}, thr={thr}, gap={gap}){skip_str}{tier_str}...", file=sys.stderr)
    result = run_simulation(df, signal_cfg=sig_cfg, regime_params=regime,
                            sim_cfg=sim_cfg, symbol=symbol)
    print(f"[analysis] Done — {result.total_trades} trades", file=sys.stderr)

    if args.json:
        print(json.dumps(_to_json(result), indent=2, default=str))
    else:
        _print_analysis(result, symbol)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
