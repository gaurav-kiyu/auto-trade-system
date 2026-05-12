#!/usr/bin/env python3
"""
OPBuying Candle Backtest — Quant Research Edition
==================================================

Implements Tasks 1-9 from the quant redesign brief:

  Task 1: Option premium model (delta-scaled P&L, not raw index pts)
  Task 2: Regime-adaptive RR targets (TRENDING wider TP, CHOPPY tighter)
  Task 3: Score spread analysis (score distribution 60-95+)
  Task 4: Signal filtering report (score gap, breakout, ADX filters)
  Task 5: Regime performance breakdown (TRENDING/NEUTRAL/CHOPPY/EVENT)
  Task 6: Directional breakdown (CALL vs PUT win rates)
  Task 7: Full metrics — expectancy, PF, Sharpe, Calmar, RR ratio
  Task 8: Signal quality analysis — which features fire, what outcomes
  Task 9: Before/after comparison output

Usage
-----
  # Live download (30-day Yahoo 1m):
  python run_backtest.py --yf-quarter

  # Custom symbol / period:
  python run_backtest.py --yf-quarter --yf-symbol ^NSEI --yf-days 30

  # CSV replay (offline):
  python run_backtest.py tests/fixtures/replay_minute_bars.csv

  # Raw index mode (before/after comparison):
  python run_backtest.py --yf-quarter --raw-index

  # Tune threshold / score gap:
  python run_backtest.py --yf-quarter --threshold 65 --score-gap 5

  # Higher quality signals only:
  python run_backtest.py --yf-quarter --threshold 70 --score-gap 8
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# UTF-8 console (Windows safe)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.candle_backtest import (
    CandleBacktestConfig,
    CandleBacktestResult,
    PerformanceMetrics,
    run_candle_backtest,
)
from core.pure_index_signal import PureIndexRegimeParams

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="OPBuying candle backtest — quant research edition",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("csv", type=Path, nargs="?", default=None,
                   help="Path to 1m OHLCV CSV (omit when using --yf-quarter)")
    p.add_argument("--yf-quarter", action="store_true",
                   help="Download 1m bars via Yahoo Finance (max ~30 days for 1m)")
    p.add_argument("--yf-symbol", type=str, default="^NSEI",
                   help="Yahoo Finance symbol (default: ^NSEI = NIFTY 50)")
    p.add_argument("--yf-days", type=int, default=30,
                   help="Calendar days (Yahoo 1m capped at ~30; default 30)")
    p.add_argument("--threshold", type=int, default=None,
                   help="Score threshold (default: AI_THRESHOLD from config, else 65)")
    p.add_argument("--score-gap", type=int, default=None,
                   help="Extra margin above threshold (default: SIGNAL_ENTRY_SCORE_GAP, else 5)")
    p.add_argument("--raw-index", action="store_true",
                   help="Use raw index-point P&L (for before/after comparison; disables option model)")
    p.add_argument("--symbol", type=str, default=None,
                   help="Index symbol for lot-size lookup (default: from yf-symbol or NIFTY)")
    p.add_argument("--vix", type=float, default=None,
                   help="Override VIX for premium model (default: from config or 14.0)")
    p.add_argument("--dte", type=int, default=3,
                   help="Days to expiry for ATM premium estimate (default: 3 = weekly mid)")
    p.add_argument("--json", action="store_true",
                   help="Emit machine-readable JSON instead of rich report")
    return p


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

_SEP  = "=" * 70
_SEP2 = "-" * 70
_LINE = "-" * 40


def _sign(v: float) -> str:
    return f"+{v:.2f}" if v >= 0 else f"{v:.2f}"


def _pct(v: float) -> str:
    return f"+{v:.2f}%" if v >= 0 else f"{v:.2f}%"


def _bar(win_rate: float, width: int = 30) -> str:
    filled = int(round(win_rate / 100.0 * width))
    return "[" + "#" * filled + "." * (width - filled) + f"] {win_rate:.1f}%"


def _star_rating(win_rate: float, pf: float) -> str:
    score = 0
    if win_rate >= 55: score += 1
    if win_rate >= 60: score += 1
    if pf >= 1.2:      score += 1
    if pf >= 1.5:      score += 1
    if win_rate >= 65 and pf >= 1.8: score += 1
    return "★" * score + "☆" * (5 - score)


def _verdict(win_rate: float, rr: float, pf: float, sharpe: float) -> str:
    if win_rate >= 60 and rr >= 1.5 and pf >= 1.5:
        return "STRONG EDGE — consistent, high-conviction strategy"
    if win_rate >= 55 and pf >= 1.2:
        return "POSITIVE EDGE — profitable with room to optimise"
    if win_rate >= 50 and rr >= 1.2:
        return "MARGINAL EDGE — breakeven+, needs higher quality filter"
    if pf < 1.0:
        return "NO EDGE — strategy is losing; review signal calibration"
    return "NEUTRAL — strategy needs more data for clear verdict"


def _print_rich_report(
    res: CandleBacktestResult,
    cfg_used: CandleBacktestConfig,
    symbol: str,
    use_option_model: bool,
    args: argparse.Namespace,
) -> None:
    m = res.metrics
    j = res.journal
    print()
    print(_SEP)
    print(f"  OPBuying BACKTEST REPORT  |  {symbol}  |  {'Option Premium Model' if use_option_model else 'Raw Index Points'}")
    print(_SEP)

    # ── Config used ────────────────────────────────────────────────────
    print(f"\n  Threshold   : {cfg_used.base_ai_threshold}  |  Score gap: +{cfg_used.score_gap}")
    print(f"  SL mult     : {cfg_used.sl_atr_mult:.2f}x ATR  |  TP mult : {cfg_used.tp_atr_mult:.2f}x ATR (regime-adaptive: {cfg_used.use_regime_rr})")
    print(f"  Warmup bars : {cfg_used.warmup_bars}  |  Cooldown: {cfg_used.cooldown_bars} bars  |  Max hold: {cfg_used.max_bars_in_trade} bars")
    if use_option_model:
        print(f"  DTE         : {cfg_used.dte}d  |  Delta scale: {cfg_used.delta_scale}x  |  Fee/lot: Rs{cfg_used.fee_per_lot:.0f}")

    # ── Core performance ───────────────────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 7 — CORE PERFORMANCE METRICS")
    print(_SEP2)
    if m.total_trades == 0:
        print("  [!] No trades generated — try relaxing threshold or score-gap.")
        print(f"      Hint: --threshold {max(40, cfg_used.base_ai_threshold - 10)} --score-gap 0")
        print()
        return

    rating  = _star_rating(m.win_rate, m.profit_factor)
    verdict = _verdict(m.win_rate, m.rr_ratio, m.profit_factor, m.sharpe_ratio)

    print(f"  Total trades     : {m.total_trades}  ({m.wins}W / {m.losses}L)")
    print(f"  Win rate         : {_bar(m.win_rate)}  {rating}")
    print(f"  Profit factor    : {m.profit_factor:.3f}  (>1.5 = strong, >1.0 = profitable)")
    print(f"  Expectancy/trade : Rs{m.expectancy_per_trade:,.2f}  per lot")
    print(f"  Avg winner       : Rs{m.avg_win:,.2f}  |  Avg loser: Rs{m.avg_loss:,.2f}")
    if use_option_model:
        print(f"  Avg win  %       : {m.avg_pct_win:+.1f}%  |  Avg loss %: {m.avg_pct_loss:+.1f}%")
    print(f"  RR ratio         : {m.rr_ratio:.3f}  (avg_win / |avg_loss|; need >1.0)")
    print(f"  Avg RR achieved  : {m.avg_rr_achieved:.3f}x  (realised R multiple)")
    print(f"  Max drawdown     : {m.max_drawdown_pct:.2f}%")
    print(f"  Sharpe ratio     : {m.sharpe_ratio:.3f}  (trade-level approx; >0.5 acceptable)")
    print(f"  Calmar ratio     : {m.calmar_ratio:.3f}  (ret/drawdown; >0.5 good)")
    print(f"  Starting capital : Rs{cfg_used.initial_capital:,.0f}")
    print(f"  Ending capital   : Rs{res.ending_capital:,.0f}")
    net_ret = (res.ending_capital - cfg_used.initial_capital) / cfg_used.initial_capital * 100
    print(f"  Net return       : {_pct(net_ret)}")
    print(f"\n  Verdict: {verdict}")

    # ── Directional breakdown (Task 6) ─────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 6 — DIRECTIONAL BREAKDOWN (CALL vs PUT)")
    print(_SEP2)
    print(f"  CALL trades : {m.call_trades:>3}  |  Win rate: {_bar(m.call_win_rate, 20)}")
    print(f"  PUT  trades : {m.put_trades:>3}  |  Win rate: {_bar(m.put_win_rate, 20)}")
    call_pct = m.call_trades / m.total_trades * 100 if m.total_trades else 0
    put_pct  = m.put_trades  / m.total_trades * 100 if m.total_trades else 0
    print(f"  Split       : {call_pct:.0f}% CALL / {put_pct:.0f}% PUT")
    if call_pct > 80:
        print(f"  [!] Heavy CALL bias ({call_pct:.0f}%) — likely testing a bull-trend period.")
        print(f"      Run on a bear-market window to validate PUT signal quality.")
    elif put_pct > 80:
        print(f"  [!] Heavy PUT bias ({put_pct:.0f}%) — likely testing a bear-trend period.")

    # ── Regime breakdown (Task 5) ──────────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 5 — MARKET REGIME BREAKDOWN")
    print(_SEP2)
    print(f"  {'Regime':<12} {'Trades':>6} {'Wins':>5} {'Win%':>7} {'Avg PnL':>10}")
    print(f"  {_LINE}")
    for regime_name in ("TRENDING", "NEUTRAL", "CHOPPY", "EVENT"):
        rs = m.by_regime.get(regime_name)
        if rs and rs.trades > 0:
            print(f"  {rs.regime:<12} {rs.trades:>6} {rs.wins:>5} {rs.win_rate:>6.1f}%  Rs{rs.avg_pnl:>8,.2f}")
    for regime_name, rs in m.by_regime.items():
        if regime_name not in ("TRENDING", "NEUTRAL", "CHOPPY", "EVENT") and rs.trades > 0:
            print(f"  {rs.regime:<12} {rs.trades:>6} {rs.wins:>5} {rs.win_rate:>6.1f}%  Rs{rs.avg_pnl:>8,.2f}")
    print(f"\n  Key insight: TRENDING should be your best regime.")
    print(f"  If CHOPPY win rate > TRENDING → mean-reversion strategy is dominant.")
    print(f"  Consider disabling entries when regime=CHOPPY (ADX < chop_threshold).")

    # ── Score distribution (Task 3) ────────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 3 — SCORE DISTRIBUTION (5-pt buckets)")
    print(_SEP2)
    if m.by_score:
        print(f"  {'Score':>8} {'Trades':>6} {'Wins':>5} {'Win%':>7} {'Avg PnL':>10}  Bar")
        print(f"  {_LINE}")
        for lbl, bk in sorted(m.by_score.items()):
            if bk.trades > 0:
                bar_w = int(bk.trades / max(1, m.total_trades) * 40)
                bar   = "|" * bar_w
                print(f"  {lbl:>8} {bk.trades:>6} {bk.wins:>5} {bk.win_rate:>6.1f}%  Rs{bk.avg_pnl:>8,.2f}  {bar}")
        all_scores = [t.score for t in j]
        if all_scores:
            print(f"\n  Score range: {min(all_scores)} – {max(all_scores)}  "
                  f"Mean: {sum(all_scores)/len(all_scores):.1f}  "
                  f"StdDev: {(sum((x - sum(all_scores)/len(all_scores))**2 for x in all_scores)/len(all_scores))**0.5:.1f}")
        print(f"\n  Target: scores should spread 65-95.  If clustered at threshold,")
        print(f"  the OI/PCR data is synthetic (backtest limitation) — add real option chain.")
    else:
        print("  (No score data)")

    # ── Signal quality analysis (Task 8) ──────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 8 — SIGNAL QUALITY ANALYSIS")
    print(_SEP2)
    if j:
        # Feature frequency in winning vs losing trades
        win_trades  = [t for t in j if t.net_pnl >= 0]
        loss_trades = [t for t in j if t.net_pnl < 0]

        def _feature_rate(trades: list, key: str, truthy: Any = True) -> float:
            if not trades: return 0.0
            count = sum(1 for t in trades if t.signal_metadata.get(key) == truthy
                        or (truthy is True and bool(t.signal_metadata.get(key))))
            return round(count / len(trades) * 100.0, 1)

        print(f"  Feature presence in WINNERS vs LOSERS (% of trades):")
        print(f"  {'Feature':<22} {'Winners':>8} {'Losers':>8}  Edge")
        print(f"  {_LINE}")
        features = [
            ("breakout_ok",  True,     "Breakout confirmed"),
            ("mkt_regime",   "TRENDING", "Regime=TRENDING"),
            ("mkt_regime",   "CHOPPY",   "Regime=CHOPPY"),
        ]
        for key, val, label in features:
            wr = _feature_rate(win_trades, key, val)
            lr = _feature_rate(loss_trades, key, val)
            edge = wr - lr
            marker = " <-- edge" if abs(edge) >= 15 else ""
            print(f"  {label:<22} {wr:>7.1f}%  {lr:>7.1f}%  {_sign(edge)}%{marker}")

        # ADX distribution
        adx_vals_w = [t.signal_metadata.get("adx", 0) for t in win_trades  if "adx" in t.signal_metadata]
        adx_vals_l = [t.signal_metadata.get("adx", 0) for t in loss_trades if "adx" in t.signal_metadata]
        if adx_vals_w:
            avg_adx_w = sum(float(v) for v in adx_vals_w) / len(adx_vals_w)
            avg_adx_l = sum(float(v) for v in adx_vals_l) / len(adx_vals_l) if adx_vals_l else 0
            print(f"\n  Avg ADX at entry  —  Winners: {avg_adx_w:.1f}  |  Losers: {avg_adx_l:.1f}")
            if avg_adx_w > avg_adx_l + 3:
                print(f"  [+] Higher ADX in winners — trend quality matters; consider ADX_TREND_THRESHOLD up")
            elif avg_adx_l > avg_adx_w + 3:
                print(f"  [-] Higher ADX in losers  — breakout failures in strong trend; check overextension")

        # RSI distribution
        rsi_vals_w = [t.signal_metadata.get("rsi", 50) for t in win_trades  if "rsi" in t.signal_metadata]
        rsi_vals_l = [t.signal_metadata.get("rsi", 50) for t in loss_trades if "rsi" in t.signal_metadata]
        if rsi_vals_w:
            avg_rsi_w = sum(float(v) for v in rsi_vals_w) / len(rsi_vals_w)
            avg_rsi_l = sum(float(v) for v in rsi_vals_l) / len(rsi_vals_l) if rsi_vals_l else 50
            print(f"  Avg RSI at entry  —  Winners: {avg_rsi_w:.1f}  |  Losers: {avg_rsi_l:.1f}")
            if avg_rsi_l > 68:
                print(f"  [!] Losers show elevated RSI ({avg_rsi_l:.1f}) — overbought entries; RSI penalty active helps")

        # Exit reason breakdown
        exit_counts: dict[str, int] = {}
        for t in j:
            exit_counts[t.exit_reason] = exit_counts.get(t.exit_reason, 0) + 1
        print(f"\n  Exit reason distribution:")
        for reason, count in sorted(exit_counts.items(), key=lambda x: -x[1]):
            pct_e = count / m.total_trades * 100
            wins_r  = sum(1 for t in j if t.exit_reason == reason and t.net_pnl >= 0)
            wr_r    = wins_r / count * 100 if count else 0
            print(f"    {reason:<16} {count:>3} trades ({pct_e:.0f}%)  win rate: {wr_r:.0f}%")

        if exit_counts.get("stop_loss", 0) > exit_counts.get("take_profit", 0):
            print(f"\n  [!] More SL exits than TP exits — TP target may be too far; consider tighter TP")
            print(f"      or use partial-exit at TP1 (0.618x ATR) to bank quick profits.")

    # ── Sample journal (last 5 trades) ─────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 9 — TRADE JOURNAL SAMPLE (last 5)")
    print(_SEP2)
    sample = j[-5:] if len(j) >= 5 else j
    for t in sample:
        side  = "CE" if t.direction == "CALL" else "PE"
        prem_info = f" prem {t.entry_premium:.0f}→{t.exit_premium:.0f}" if use_option_model else ""
        print(f"  {t.entry_time[:16]}  {side} score={t.score}/{t.threshold}  "
              f"{t.exit_reason:<14} PnL=Rs{t.net_pnl:>8,.2f}{prem_info}  "
              f"RR={t.rr_achieved:>5.2f}  bars={t.bars_held}  regime={t.regime}")

    # ── Config suggestions (Task 9) ────────────────────────────────────
    print(f"\n{_SEP2}")
    print(f"  TASK 9 — CONFIG SUGGESTIONS")
    print(_SEP2)
    if m.total_trades > 0:
        if m.win_rate < 50 and m.rr_ratio < 1.2:
            print(f"  CRITICAL: Win rate {m.win_rate:.1f}% AND RR {m.rr_ratio:.2f} both poor.")
            print(f"    -> Raise threshold to {cfg_used.base_ai_threshold + 5} (filter weak signals)")
            print(f"    -> Raise score_gap to {cfg_used.score_gap + 3} (only high-conviction entries)")
            print(f"    -> Verify breakout_ok filter is active in live signal path")
        elif m.win_rate < 50:
            print(f"  Win rate low ({m.win_rate:.1f}%) but RR {m.rr_ratio:.2f} is OK.")
            print(f"    -> Consider raising threshold by +5 (more selective entries)")
            print(f"    -> Check if CHOPPY regime entries are dragging win rate down")
        elif m.rr_ratio < 1.0:
            print(f"  RR ratio < 1.0 ({m.rr_ratio:.2f}) — TP too tight or SL too wide.")
            print(f"    -> Increase tp_atr_mult from {cfg_used.tp_atr_mult} to {cfg_used.tp_atr_mult + 0.3:.2f}")
            print(f"    -> Decrease sl_atr_mult from {cfg_used.sl_atr_mult} to {cfg_used.sl_atr_mult - 0.1:.2f}")
        else:
            print(f"  Strategy is producing edge (WR={m.win_rate:.1f}%, RR={m.rr_ratio:.2f}, PF={m.profit_factor:.2f}).")
            print(f"  Suggested next steps:")
            print(f"    -> Walk-forward validate on different date windows")
            print(f"    -> Test with real NSE option chain data (PCR + OI → +15 pts score)")
            print(f"    -> Consider partial exit: sell 50% at TP1, trail remainder")

        print(f"\n  Recommended config.json values for this run:")
        print(f'    "AI_THRESHOLD"          : {cfg_used.base_ai_threshold},')
        print(f'    "SIGNAL_ENTRY_SCORE_GAP": {cfg_used.score_gap},')
        print(f'    "ATR_SL_MULTIPLIER"     : {cfg_used.sl_atr_mult},')
        print(f'    "FIB_TP2_RATIO"         : {cfg_used.tp_atr_mult},')
        print(f'    "ADX_CHOP_THRESHOLD"    : 14,')
        print(f'    "ADX_TREND_THRESHOLD"   : 20')

    print(f"\n{_SEP}")
    print(f"  END OF REPORT")
    print(_SEP)
    print()


# ---------------------------------------------------------------------------
# Before/after comparison (raw index vs option model)
# ---------------------------------------------------------------------------

def _run_and_summarise(
    df,
    signal_cfg: dict,
    regime: PureIndexRegimeParams,
    cfg: CandleBacktestConfig,
    symbol: str,
    label: str,
) -> CandleBacktestResult:
    print(f"  [backtest] Running '{label}' mode...", file=sys.stderr)
    res = run_candle_backtest(
        df, signal_cfg=signal_cfg, regime_params=regime,
        iv_spike_threshold=float(signal_cfg.get("IV_SPIKE_THRESHOLD", 45)),
        vol_ratio_min=float(signal_cfg.get("VOL_RATIO_MIN", 1.2)),
        backtest_cfg=cfg, symbol=symbol,
    )
    return res


def _print_comparison(res_raw: CandleBacktestResult, res_opt: CandleBacktestResult) -> None:
    r, o = res_raw.metrics, res_opt.metrics
    print(f"\n{_SEP}")
    print(f"  BEFORE / AFTER COMPARISON  (Raw Index pts vs Option Premium Model)")
    print(_SEP)
    print(f"  {'Metric':<26} {'Raw Index':>12} {'Option Model':>14}  Delta")
    print(f"  {_SEP2}")
    rows = [
        ("Total trades",         r.total_trades,         o.total_trades,         None),
        ("Win rate %",           r.win_rate,             o.win_rate,             "%"),
        ("Profit factor",        r.profit_factor,        o.profit_factor,        "x"),
        ("Expectancy/trade Rs",  r.expectancy_per_trade, o.expectancy_per_trade, "Rs"),
        ("Avg winner Rs",        r.avg_win,              o.avg_win,              "Rs"),
        ("Avg loser Rs",         r.avg_loss,             o.avg_loss,             "Rs"),
        ("RR ratio",             r.rr_ratio,             o.rr_ratio,             "x"),
        ("Sharpe ratio",         r.sharpe_ratio,         o.sharpe_ratio,         ""),
        ("Max drawdown %",       r.max_drawdown_pct,     o.max_drawdown_pct,     "%"),
    ]
    for label, rv, ov, unit in rows:
        if unit is None:
            print(f"  {label:<26} {int(rv):>12}  {int(ov):>13}")
        else:
            delta_str = _sign(ov - rv) if isinstance(rv, float) else ""
            print(f"  {label:<26} {rv:>12.2f}  {ov:>13.2f}  {delta_str}")
    print(f"\n  Key takeaway: option model typically shows higher RR and lower avg_loss")
    print(f"  because delta-scaling (×0.45) compresses the raw index move distance.")
    print(f"  The option model is the correct frame for evaluating this strategy.\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = _build_parser()
    args = p.parse_args()

    # Load data
    if args.yf_quarter:
        from core.yf_bar_fetch import fetch_1m_bars_chunked_yfinance
        eff = min(max(1, int(args.yf_days)), 30)
        if int(args.yf_days) > 30:
            print(f"[backtest] Yahoo 1m capped at 30d; using {eff}d.", file=sys.stderr)
        print(f"[backtest] Fetching {args.yf_symbol!r} {eff}d 1m bars...", file=sys.stderr)
        df = fetch_1m_bars_chunked_yfinance(str(args.yf_symbol), calendar_days=eff)
        print(f"[backtest] Loaded {len(df)} bars  {df.index.min()} → {df.index.max()}", file=sys.stderr)
    else:
        if not args.csv or not args.csv.is_file():
            p.error("Provide a CSV path or --yf-quarter.")
        from core.backtest_engine import CsvReplaySource, ReplayConfig
        src = CsvReplaySource(args.csv, ReplayConfig(warmup_bars=30))
        df = src.load()

    # Load config
    defaults_path = ROOT / "index_config.defaults.json"
    signal_cfg = json.loads(defaults_path.read_text(encoding="utf-8")) if defaults_path.exists() else {}

    # Override with main config.json keys where relevant
    main_cfg_path = ROOT / "config.json"
    if main_cfg_path.exists():
        try:
            main_cfg = json.loads(main_cfg_path.read_text(encoding="utf-8"))
            for k in (
                "AI_THRESHOLD", "SIGNAL_ENTRY_SCORE_GAP", "ATR_SL_MULTIPLIER",
                "FIB_TP2_RATIO", "FIB_TP3_RATIO", "ADX_CHOP_THRESHOLD",
                "ADX_TREND_THRESHOLD", "VIX_BLOCK_THRESHOLD", "IV_SPIKE_THRESHOLD",
                "VOL_RATIO_MIN", "BREAKOUT_BONUS", "ADX_PENALTY_THRESHOLD",
                "ADX_PENALTY_POINTS", "INDEX_RSI_BONUS", "INDEX_RSI_PENALTY",
                "INDEX_RSI_OVERBOUGHT", "INDEX_RSI_OVERSOLD",
                "OPTION_ATM_DELTA", "OPTION_DTE_DEFAULT", "OPTION_DELTA_SCALE",
            ):
                if k in main_cfg:
                    signal_cfg[k] = main_cfg[k]
        except Exception as e:
            print(f"[backtest] config.json load warning: {e}", file=sys.stderr)

    # Derive backtest parameters
    thr = (int(args.threshold) if args.threshold is not None
           else int(signal_cfg.get("AI_THRESHOLD", 65)))
    gap = (int(args.score_gap) if args.score_gap is not None
           else int(signal_cfg.get("SIGNAL_ENTRY_SCORE_GAP", 5)))
    vix = (float(args.vix) if args.vix is not None
           else float(signal_cfg.get("BACKTEST_VIX", 14.0)))

    # Infer symbol
    symbol = args.symbol or (
        args.yf_symbol.upper().replace("^", "").replace("NSE:", "") if args.yf_quarter else "NIFTY"
    )
    if "NSEI" in symbol or "NIFTY50" in symbol:
        symbol = "NIFTY"
    elif "NSEBANK" in symbol or "BANKNIFTY" in symbol:
        symbol = "BANKNIFTY"

    regime = PureIndexRegimeParams(
        vix_block_threshold  = float(signal_cfg.get("VIX_BLOCK_THRESHOLD",  35)),
        adx_trend_threshold  = float(signal_cfg.get("ADX_TREND_THRESHOLD",  20)),
        adx_chop_threshold   = float(signal_cfg.get("ADX_CHOP_THRESHOLD",   14)),
    )

    base_cfg = CandleBacktestConfig(
        warmup_bars       = 35,
        base_ai_threshold = thr,
        score_gap         = gap,
        latency_bars      = 1,
        slippage_pct      = 0.0005,
        spread_pct        = 0.0002,
        fee_per_lot       = 40.0,
        vix               = vix,
        tp_atr_mult       = float(signal_cfg.get("FIB_TP2_RATIO",    1.618)),
        sl_atr_mult       = float(signal_cfg.get("ATR_SL_MULTIPLIER", 1.2)),
        use_option_model  = not args.raw_index,
        dte               = int(args.dte),
        delta_scale       = float(signal_cfg.get("OPTION_DELTA_SCALE", 1.5)),
        use_regime_rr     = True,
    )

    if args.raw_index:
        # Single run in raw mode (for comparison baseline)
        res = _run_and_summarise(df, signal_cfg, regime, base_cfg, symbol, "raw-index")
        if args.json:
            m = res.metrics
            print(json.dumps({
                "mode": "raw_index",
                "ending_capital": res.ending_capital,
                "total_trades": m.total_trades,
                "win_rate": m.win_rate,
                "profit_factor": m.profit_factor,
                "max_drawdown_pct": m.max_drawdown_pct,
                "expectancy_per_trade": m.expectancy_per_trade,
                "rr_ratio": m.rr_ratio,
                "sharpe_ratio": m.sharpe_ratio,
                "calmar_ratio": m.calmar_ratio,
            }, indent=2))
        else:
            _print_rich_report(res, base_cfg, symbol, False, args)
    else:
        # Default: option model + before/after comparison
        cfg_opt = base_cfg
        cfg_raw = CandleBacktestConfig(
            **{k: v for k, v in vars(base_cfg).items() if k != "use_option_model"},
            use_option_model=False,
        )
        res_opt = _run_and_summarise(df, signal_cfg, regime, cfg_opt, symbol, "option-model")
        res_raw = _run_and_summarise(df, signal_cfg, regime, cfg_raw, symbol, "raw-index")

        if args.json:
            m = res_opt.metrics
            print(json.dumps({
                "mode": "option_model",
                "ending_capital":        res_opt.ending_capital,
                "total_trades":          m.total_trades,
                "win_rate":              m.win_rate,
                "profit_factor":         m.profit_factor,
                "max_drawdown_pct":      m.max_drawdown_pct,
                "expectancy_per_trade":  m.expectancy_per_trade,
                "rr_ratio":              m.rr_ratio,
                "sharpe_ratio":          m.sharpe_ratio,
                "calmar_ratio":          m.calmar_ratio,
                "call_trades":           m.call_trades,
                "put_trades":            m.put_trades,
                "call_win_rate":         m.call_win_rate,
                "put_win_rate":          m.put_win_rate,
                "by_regime":             {k: vars(v) for k, v in m.by_regime.items()},
                "by_score":              {k: vars(v) for k, v in m.by_score.items()},
                "journal_sample":        [vars(t) for t in res_opt.journal[-3:]],
            }, indent=2, default=str))
        else:
            _print_rich_report(res_opt, cfg_opt, symbol, True, args)
            _print_comparison(res_raw, res_opt)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
