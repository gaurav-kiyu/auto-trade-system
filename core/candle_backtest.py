"""
Candle-by-candle backtester using the same pure index signal path as live trading.

Key upgrades vs original:
  • Option premium model — P&L in option space (delta-scaled), not raw index pts.
    Eliminates the "avg_loss >> avg_win" artefact caused by measuring index moves.
  • Regime-adaptive TP/SL — TRENDING gets wider TP, CHOPPY gets tighter targets.
  • Expanded PerformanceMetrics — Sharpe, Calmar, RR ratio, score buckets,
    per-regime breakdown, directional breakdown (CALL vs PUT).
  • Signal quality log — per-trade features triggered; used for edge analysis.
  • Score-gap filter (score >= threshold + score_gap) kept from previous session.
  • Proper double fee (entry + exit) and realistic slippage on options.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core.option_premium_model import (
    build_option_trade,
    calc_option_pnl,
    regime_rr_targets,
)
from core.pure_index_signal import (
    PureIndexRegimeParams,
    PureIndexSignalParams,
    evaluate_index_signal_partial,
    finalize_index_signal_with_threshold,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _coerce_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _build_frames(base_df: pd.DataFrame, upto: int) -> dict[str, pd.DataFrame]:
    window = base_df.iloc[: upto + 1].copy()
    frames: dict[str, pd.DataFrame] = {"1m": window.copy()}
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    for rule, key in (("5min", "5m"), ("15min", "15m")):
        rs = window.resample(rule, label="right", closed="right").agg(agg).dropna(
            subset=["Open", "High", "Low", "Close"]
        )
        frames[key] = rs
    return frames


def _synthetic_oi(price: float) -> tuple[float, float, float, str]:
    if price <= 0:
        return 0.0, 0.0, 1.0, "NEUTRAL"
    sup = round(price * 0.99, 2)
    res = round(price * 1.01, 2)
    return sup, res, 1.0, "NEUTRAL"


def _historical_oi(
    index_name: str,
    price: float,
    target_ts: float,
    oi_db_path: str,
) -> tuple[float, float, float, str] | None:
    """
    Look up point-in-time PCR from oi_snapshots.db for a given bar timestamp.

    Returns a 4-tuple (sup, res, pcr, smart) matching _synthetic_oi's contract,
    or None when no historical data exists (caller falls back to _synthetic_oi).

    Never returns data AT or AFTER target_ts — no look-ahead.
    """
    try:
        from core.oi_snapshot_store import get_pcr_at as _get_pcr
        pcr = _get_pcr(index_name, target_ts, db_path=oi_db_path)
        if pcr is None:
            return None
        sup = round(price * 0.99, 2)
        res = round(price * 1.01, 2)
        # Infer smart-money bias from PCR (mirrors live get_oi_data logic)
        if pcr > 1.2:
            smart = "BULLISH"
        elif pcr < 0.8:
            smart = "BEARISH"
        else:
            smart = "NEUTRAL"
        return sup, res, pcr, smart
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CandleBacktestConfig:
    initial_capital: float  = 100_000.0
    qty: int                = 1           # lots traded per signal
    warmup_bars: int        = 35
    latency_bars: int       = 1           # 1-bar execution lag (realistic)
    slippage_pct: float     = 0.0005      # 5 bps on option premium
    spread_pct: float       = 0.0002      # 2 bps bid-ask on option
    fee_per_lot: float      = 40.0        # round-trip brokerage + STT per lot
    max_bars_in_trade: int  = 40          # 40 min max hold
    cooldown_bars: int      = 30          # min bars between trades
    vix: float              = 14.0
    iv: float               = 0.0
    base_ai_threshold: int  = 65
    score_gap: int          = 5           # score must exceed threshold by this margin
    tp_atr_mult: float      = 1.618       # default TP (overridden by regime logic)
    sl_atr_mult: float      = 1.2         # default SL
    use_option_model: bool  = True        # True → P&L in option space
    dte: int                = 3           # days-to-expiry for premium estimate
    delta_scale: float      = 1.5         # ATM premium calibration factor
    disable_learning: bool  = True
    disable_adaptive: bool  = True
    use_regime_rr: bool     = True        # True → adjust TP/SL per regime
    oi_snapshot_db: str     = ""          # path to oi_snapshots.db; "" = use synthetic OI
    strict_oi: bool         = False       # abort if OI coverage < 80%
    oi_fallback_warn_pct: float = 0.20    # warn in report header if > this fraction used synthetic


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TradeJournalRow:
    entry_time: str
    exit_time: str
    entry_price: float          # index price at entry
    exit_price: float           # index price at exit
    entry_premium: float        # option premium at entry (0 if model off)
    exit_premium: float         # option premium at exit
    direction: str              # "CALL" or "PUT"
    gross_pnl: float            # per lot
    net_pnl: float              # per lot after fees
    exit_reason: str
    bars_held: int
    score: int
    threshold: int
    confidence: float
    rr_achieved: float          # R:R actually realised
    pct_pnl: float              # % gain/loss on option premium
    regime: str
    signal_reason: str
    signal_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RegimeStats:
    regime: str
    trades: int = 0
    wins: int = 0
    gross_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.trades * 100.0, 2) if self.trades else 0.0

    @property
    def avg_pnl(self) -> float:
        return round(self.gross_pnl / self.trades, 2) if self.trades else 0.0


@dataclass
class ScoreBucket:
    label: str    # e.g. "65-70", "70-75", ...
    trades: int = 0
    wins: int = 0
    gross_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.trades * 100.0, 2) if self.trades else 0.0


@dataclass
class PerformanceMetrics:
    # Core
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    expectancy_per_trade: float
    total_trades: int
    wins: int
    losses: int
    # Risk / reward
    avg_win: float
    avg_loss: float
    rr_ratio: float             # avg_win / |avg_loss|
    avg_rr_achieved: float      # avg R:R actually realised
    avg_pct_win: float          # avg % gain on option premium (winners)
    avg_pct_loss: float         # avg % loss on option premium (losers)
    # Risk-adjusted
    sharpe_ratio: float         # daily Sharpe approximation
    calmar_ratio: float         # annualised return / max drawdown
    # Directional
    call_trades: int
    put_trades: int
    call_win_rate: float
    put_win_rate: float
    # Regime breakdown
    by_regime: dict[str, RegimeStats]
    # Score bucket distribution
    by_score: dict[str, ScoreBucket]


@dataclass
class CandleBacktestResult:
    journal: list[TradeJournalRow]
    equity_curve: list[float]
    metrics: PerformanceMetrics
    ending_capital: float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CandleBacktestEngine:
    """
    Bar-by-bar backtest using evaluate_index_signal_partial + finalize.

    P&L computation:
      use_option_model=True  → converts index moves to option-premium P&L via delta
      use_option_model=False → raw index-point P&L (original, for comparison)

    Regime-adaptive TP/SL:
      use_regime_rr=True → TRENDING gets wider TP (+20%), CHOPPY tighter both
    """

    def __init__(
        self,
        *,
        signal_cfg: Mapping[str, Any],
        regime_params: PureIndexRegimeParams,
        iv_spike_threshold: float,
        vol_ratio_min: float,
        is_early_session_fn: Callable[[], bool] | None = None,
        name: str = "NIFTY",
    ) -> None:
        self._signal_cfg = dict(signal_cfg)
        self._regime_params = regime_params
        self._iv_spike = float(iv_spike_threshold)
        self._vol_ratio_min = float(vol_ratio_min)
        self._is_early_session_fn = is_early_session_fn or (lambda: False)
        self._name = name

    # ------------------------------------------------------------------
    def run(
        self,
        base_1m: pd.DataFrame,
        cfg: CandleBacktestConfig | None = None,
    ) -> CandleBacktestResult:
        cfg = cfg or CandleBacktestConfig()
        journal: list[TradeJournalRow] = []
        equity: list[float] = []
        capital = float(cfg.initial_capital)
        peak = capital
        max_dd = 0.0
        position: dict[str, Any] | None = None
        pending: dict[str, Any] | None = None
        cooldown_until = -1

        warmup = max(20, int(cfg.warmup_bars))
        n = len(base_1m)
        _oi_db        = str(cfg.oi_snapshot_db or "")
        _use_hist_oi  = bool(_oi_db)
        _synthetic_bars = 0
        _total_signal_bars = 0

        for idx in range(warmup, n):
            row = base_1m.iloc[idx]
            ts  = str(base_1m.index[idx])

            # ── Pending order: execute one bar after signal ──────────────
            if pending is not None and int(pending["enter_on_idx"]) == idx:
                position, capital = self._execute_pending(pending, row, idx, ts, cfg, capital)
                pending = None

            # ── Check for exit ────────────────────────────────────────────
            if position is not None:
                exit_px, reason = self._maybe_exit_bar(position, row, idx)
                if exit_px is not None:
                    capital, peak, max_dd = self._close_trade(
                        journal, capital, peak, max_dd,
                        position, ts, float(exit_px), reason, idx, cfg,
                    )
                    position = None
                    cooldown_until = idx + int(cfg.cooldown_bars)
                    equity.append(capital)
                    continue

            equity.append(capital)

            if position is not None or idx < cooldown_until:
                continue

            # ── Generate signal ───────────────────────────────────────────
            frames = _build_frames(base_1m, idx)
            df1  = frames["1m"]
            df5  = frames["5m"]
            df15 = frames["15m"]
            price = float(df1["Close"].iloc[-1])
            _total_signal_bars += 1
            _hist = None
            if _use_hist_oi:
                try:
                    _bar_ts = base_1m.index[idx]
                    _bar_epoch = float(_bar_ts.timestamp()) if hasattr(_bar_ts, "timestamp") else float(_bar_ts)
                except Exception:
                    _bar_epoch = 0.0
                _hist = _historical_oi(self._name, price, _bar_epoch, _oi_db)
            if _hist is not None:
                sup, res, pcr, smart = _hist
            else:
                sup, res, pcr, smart = _synthetic_oi(price)
                _synthetic_bars += 1

            params = PureIndexSignalParams(
                name=self._name,
                signal_cfg=self._signal_cfg,
                regime=self._regime_params,
                iv_spike_threshold=self._iv_spike,
                vol_ratio_min=self._vol_ratio_min,
                is_early_session=bool(self._is_early_session_fn()),
            )
            partial, _tag = evaluate_index_signal_partial(
                params=params,
                df1=df1, df5=df5, df15=df15,
                vix=float(cfg.vix),
                iv=float(cfg.iv),
                oi_sup=sup, oi_res=res,
                pcr=pcr, smart=smart,
                learning_score_bonus=0,
            )
            if partial is None:
                continue

            thr = int(cfg.base_ai_threshold)
            # Score-gap filter: reject borderline signals
            if int(partial["score"]) < thr + int(cfg.score_gap):
                continue

            finalized = finalize_index_signal_with_threshold(
                partial,
                threshold=thr,
                regime="BACKTEST",
                adaptive_delta=0,
                adaptive_reason="frozen",
                trace_id=f"bt-{idx}",
                signal_cfg=self._signal_cfg,
            )
            if finalized.get("action") != "BUY":
                continue

            enter_on = idx + max(0, int(cfg.latency_bars))
            if enter_on >= n:
                continue

            ref_row   = base_1m.iloc[enter_on]
            ref_price = float(ref_row["Open"])
            atr_val   = float(finalized.get("atr") or ref_price * 0.005)
            regime    = str(finalized.get("mkt_regime") or "NEUTRAL")

            # Regime-adaptive TP/SL
            if cfg.use_regime_rr:
                sl_m, tp_m = regime_rr_targets(regime, cfg.sl_atr_mult, cfg.tp_atr_mult)
            else:
                sl_m, tp_m = cfg.sl_atr_mult, cfg.tp_atr_mult

            pending = {
                "enter_on_idx": enter_on,
                "direction":    finalized["direction"],
                "ref_price":    ref_price,
                "atr":          atr_val,
                "tp_mult":      float(tp_m),
                "sl_mult":      float(sl_m),
                "score":        int(finalized["score"]),
                "threshold":    int(finalized["threshold"]),
                "regime":       regime,
                "meta": {
                    "confidence":    finalized.get("confidence", 0.0),
                    "signal_reason": finalized.get("signal_reason", ""),
                    "mkt_regime":    regime,
                    "macd":          finalized.get("macd"),
                    "breakout_ok":   finalized.get("breakout_ok", False),
                    "adx":           finalized.get("adx", 0.0),
                    "rsi":           finalized.get("rsi", 50.0),
                    "trend_5m":      finalized.get("trend_5m"),
                    "trend_15m":     finalized.get("trend_15m"),
                },
            }

        # ── OI coverage check ─────────────────────────────────────────────
        _oi_fallback_frac = (
            _synthetic_bars / _total_signal_bars if _total_signal_bars > 0 else 1.0
        )
        if _use_hist_oi and _oi_fallback_frac > cfg.oi_fallback_warn_pct:
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "[BACKTEST] %.0f%% of signal bars used synthetic OI fallback "
                "(no historical snapshot). Consider running live first to build "
                "oi_snapshots.db, or disable oi_snapshot_db.",
                _oi_fallback_frac * 100,
            )
        if cfg.strict_oi and _oi_fallback_frac > 0.20:
            raise RuntimeError(
                f"--strict-backtest: OI coverage {100*(1-_oi_fallback_frac):.0f}% < 80% "
                f"({_synthetic_bars}/{_total_signal_bars} bars used synthetic fallback). "
                "Aborting. Run without --strict-backtest to proceed with fallback data."
            )

        metrics = self._compute_metrics(journal, cfg.initial_capital, capital, max_dd)
        return CandleBacktestResult(
            journal=journal,
            equity_curve=equity,
            metrics=metrics,
            ending_capital=round(capital, 2),
        )

    # ------------------------------------------------------------------
    def _execute_pending(
        self,
        pending: dict[str, Any],
        row: pd.Series,
        idx: int,
        ts: str,
        cfg: CandleBacktestConfig,
        capital: float,
    ) -> tuple[dict[str, Any], float]:
        direction = str(pending["direction"])
        raw_price = float(pending["ref_price"])
        slip = float(cfg.slippage_pct)
        spr  = float(cfg.spread_pct)

        # Index-level entry price (with slippage)
        if direction == "CALL":
            entry_idx = raw_price * (1.0 + slip + spr * 0.5)
        else:
            entry_idx = raw_price * (1.0 - slip - spr * 0.5)

        atr    = float(pending.get("atr", entry_idx * 0.005))
        sl_m   = float(pending.get("sl_mult", cfg.sl_atr_mult))
        tp_m   = float(pending.get("tp_mult", cfg.tp_atr_mult))
        regime = str(pending.get("regime", "NEUTRAL"))

        if direction == "CALL":
            sl_idx = entry_idx - atr * sl_m
            tp_idx = entry_idx + atr * tp_m
        else:
            sl_idx = entry_idx + atr * sl_m
            tp_idx = entry_idx - atr * tp_m

        entry_prem = 0.0
        opt_spec   = None
        if cfg.use_option_model:
            opt_spec = build_option_trade(
                symbol=self._name,
                direction=direction,
                entry_index=entry_idx,
                atr=atr,
                vix=float(cfg.vix),
                sl_index=sl_idx,
                tp_index=tp_idx,
                dte=int(cfg.dte),
                delta_scale=float(cfg.delta_scale),
            )
            entry_prem = opt_spec.entry_premium

        capital = round(capital - float(cfg.fee_per_lot) * int(cfg.qty), 2)

        position = {
            "entry_idx":     idx,
            "entry_time":    ts,
            "entry_price":   round(entry_idx, 4),
            "stop_loss":     round(sl_idx, 4),
            "tp":            round(tp_idx, 4),
            "direction":     direction,
            "qty":           int(cfg.qty),
            "entry_premium": round(entry_prem, 2),
            "opt_spec":      opt_spec,
            "meta":          dict(pending["meta"]),
            "score":         int(pending["score"]),
            "threshold":     int(pending["threshold"]),
            "regime":        regime,
            "max_bars":      int(cfg.max_bars_in_trade),
        }
        return position, capital

    # ------------------------------------------------------------------
    @staticmethod
    def _maybe_exit_bar(
        position: dict[str, Any],
        row: pd.Series,
        idx: int,
    ) -> tuple[float | None, str]:
        direction = str(position["direction"])
        sl        = float(position["stop_loss"])
        tp        = float(position["tp"])
        held      = idx - int(position["entry_idx"])
        hi        = float(row["High"])
        lo        = float(row["Low"])
        close_px  = float(row["Close"])
        max_bars  = int(position.get("max_bars", 40))

        if direction == "CALL":
            if lo <= sl: return sl, "stop_loss"
            if hi >= tp: return tp, "take_profit"
        else:
            if hi >= sl: return sl, "stop_loss"
            if lo <= tp: return tp, "take_profit"

        if held >= max_bars:
            return close_px, "time_exit"
        return None, ""

    # ------------------------------------------------------------------
    def _close_trade(
        self,
        journal: list[TradeJournalRow],
        capital: float,
        peak: float,
        max_dd: float,
        position: dict[str, Any],
        ts: str,
        exit_index: float,
        reason: str,
        idx: int,
        cfg: CandleBacktestConfig,
    ) -> tuple[float, float, float]:
        entry_idx  = float(position["entry_price"])
        qty        = int(position["qty"])
        direction  = str(position["direction"])
        entry_prem = float(position.get("entry_premium", 0.0))
        opt_spec   = position.get("opt_spec")
        regime     = str(position.get("regime", "NEUTRAL"))
        meta       = position.get("meta") or {}

        # Apply exit slippage — you always fill at a worse price when exiting.
        # For CALL holders selling: adverse fill = lower underlying index.
        # For PUT holders selling: adverse fill = higher underlying index.
        _exit_slip = float(cfg.slippage_pct) + float(cfg.spread_pct) * 0.5
        if direction == "CALL":
            exit_index = exit_index * (1.0 - _exit_slip)
        else:
            exit_index = exit_index * (1.0 + _exit_slip)

        exit_prem  = 0.0
        rr         = 0.0
        pct_pnl    = 0.0

        if cfg.use_option_model and opt_spec is not None:
            # Option-space P&L
            pnl_info  = calc_option_pnl(opt_spec, exit_index, reason, fee_per_lot=float(cfg.fee_per_lot))
            gross     = pnl_info["gross_pnl_per_lot"] * qty
            net       = pnl_info["net_pnl_per_lot"] * qty
            exit_prem = pnl_info["exit_premium"]
            rr        = pnl_info["rr_achieved"]
            pct_pnl   = pnl_info["pct_pnl"]
        else:
            # Raw index-point P&L (fallback / comparison mode)
            if direction == "CALL":
                gross = (exit_index - entry_idx) * qty
            else:
                gross = (entry_idx - exit_index) * qty
            net = gross - float(cfg.fee_per_lot) * qty
            if entry_idx > 0:
                pct_pnl = (exit_index - entry_idx) / entry_idx * 100.0

        capital = round(capital + net, 2)
        peak    = max(peak, capital)
        if peak > 0:
            max_dd = max(max_dd, (peak - capital) / peak * 100.0)

        journal.append(TradeJournalRow(
            entry_time     = str(position["entry_time"]),
            exit_time      = ts,
            entry_price    = round(entry_idx, 4),
            exit_price     = round(exit_index, 4),
            entry_premium  = round(entry_prem, 2),
            exit_premium   = round(exit_prem, 2),
            direction      = direction,
            gross_pnl      = round(gross, 2),
            net_pnl        = round(net, 2),
            exit_reason    = reason,
            bars_held      = idx - int(position["entry_idx"]),
            score          = int(position.get("score", 0)),
            threshold      = int(position.get("threshold", 0)),
            confidence     = float(meta.get("confidence", 0.0)),
            rr_achieved    = round(rr, 3),
            pct_pnl        = round(pct_pnl, 2),
            regime         = regime,
            signal_reason  = str(meta.get("signal_reason", "")),
            signal_metadata= dict(meta),
        ))
        return capital, peak, max_dd

    # ------------------------------------------------------------------
    @staticmethod
    def _compute_metrics(
        journal: list[TradeJournalRow],
        initial: float,
        ending: float,
        max_dd: float,
    ) -> PerformanceMetrics:
        if not journal:
            empty_regime = {r: RegimeStats(r) for r in ("TRENDING", "NEUTRAL", "CHOPPY", "EVENT")}
            return PerformanceMetrics(
                win_rate=0.0, profit_factor=0.0, max_drawdown_pct=round(max_dd, 4),
                expectancy_per_trade=0.0, total_trades=0, wins=0, losses=0,
                avg_win=0.0, avg_loss=0.0, rr_ratio=0.0, avg_rr_achieved=0.0,
                avg_pct_win=0.0, avg_pct_loss=0.0,
                sharpe_ratio=0.0, calmar_ratio=0.0,
                call_trades=0, put_trades=0, call_win_rate=0.0, put_win_rate=0.0,
                by_regime=empty_regime, by_score={},
            )

        wins   = [t for t in journal if t.net_pnl >= 0]
        losses = [t for t in journal if t.net_pnl <  0]
        total  = len(journal)

        win_rate       = round(len(wins) / total * 100.0, 2)
        gp             = sum(t.net_pnl for t in wins)
        gl             = abs(sum(t.net_pnl for t in losses))
        profit_factor  = round(gp / gl, 4) if gl > 0 else (9999.0 if gp > 0 else 0.0)
        expectancy     = float(np.mean([t.net_pnl for t in journal]))
        avg_win        = round(float(np.mean([t.net_pnl for t in wins])), 2) if wins else 0.0
        avg_loss_abs   = round(float(np.mean([abs(t.net_pnl) for t in losses])), 2) if losses else 0.0
        rr_ratio       = round(avg_win / avg_loss_abs, 3) if avg_loss_abs > 0 else 0.0

        avg_rr     = round(float(np.mean([t.rr_achieved for t in journal])), 3)
        avg_pct_w  = round(float(np.mean([t.pct_pnl for t in wins])), 2) if wins else 0.0
        avg_pct_l  = round(float(np.mean([t.pct_pnl for t in losses])), 2) if losses else 0.0

        # Approximate daily Sharpe from trade-level P&L
        pnls = np.array([t.net_pnl for t in journal])
        sharpe = round(float(np.mean(pnls) / np.std(pnls) * np.sqrt(252)), 3) if np.std(pnls) > 0 else 0.0

        # Calmar = annualised return / max drawdown
        total_ret_pct = (ending - initial) / initial * 100.0
        calmar = round(total_ret_pct / max_dd, 3) if max_dd > 0 else 0.0

        # Directional breakdown
        call_j   = [t for t in journal if t.direction == "CALL"]
        put_j    = [t for t in journal if t.direction == "PUT"]
        call_wr  = round(sum(1 for t in call_j if t.net_pnl >= 0) / len(call_j) * 100.0, 2) if call_j else 0.0
        put_wr   = round(sum(1 for t in put_j  if t.net_pnl >= 0) / len(put_j)  * 100.0, 2) if put_j  else 0.0

        # Per-regime breakdown
        regime_map: dict[str, RegimeStats] = {}
        for t in journal:
            r = t.regime or "UNKNOWN"
            if r not in regime_map:
                regime_map[r] = RegimeStats(r)
            s = regime_map[r]
            s.trades  += 1
            s.wins    += (1 if t.net_pnl >= 0 else 0)
            s.gross_pnl += t.net_pnl

        # Score-bucket distribution (5-point buckets)
        bucket_map: dict[str, ScoreBucket] = {}
        for t in journal:
            sc = int(t.score)
            lo_b = (sc // 5) * 5
            lbl  = f"{lo_b}-{lo_b + 4}"
            if lbl not in bucket_map:
                bucket_map[lbl] = ScoreBucket(lbl)
            b = bucket_map[lbl]
            b.trades  += 1
            b.wins    += (1 if t.net_pnl >= 0 else 0)
            b.gross_pnl += t.net_pnl

        return PerformanceMetrics(
            win_rate             = win_rate,
            profit_factor        = float(min(profit_factor, 1e9)),
            max_drawdown_pct     = round(max_dd, 4),
            expectancy_per_trade = round(expectancy, 4),
            total_trades         = total,
            wins                 = len(wins),
            losses               = len(losses),
            avg_win              = avg_win,
            avg_loss             = -avg_loss_abs,     # negative convention
            rr_ratio             = rr_ratio,
            avg_rr_achieved      = avg_rr,
            avg_pct_win          = avg_pct_w,
            avg_pct_loss         = avg_pct_l,
            sharpe_ratio         = sharpe,
            calmar_ratio         = calmar,
            call_trades          = len(call_j),
            put_trades           = len(put_j),
            call_win_rate        = call_wr,
            put_win_rate         = put_wr,
            by_regime            = regime_map,
            by_score             = dict(sorted(bucket_map.items())),
        )


# ---------------------------------------------------------------------------
# Convenience entry-point (mirrors old run_candle_backtest API)
# ---------------------------------------------------------------------------

def run_candle_backtest(
    df_1m: pd.DataFrame,
    *,
    signal_cfg: Mapping[str, Any],
    regime_params: PureIndexRegimeParams,
    iv_spike_threshold: float = 45.0,
    vol_ratio_min: float = 1.2,
    backtest_cfg: CandleBacktestConfig | None = None,
    symbol: str = "NIFTY",
) -> CandleBacktestResult:
    eng = CandleBacktestEngine(
        signal_cfg=signal_cfg,
        regime_params=regime_params,
        iv_spike_threshold=iv_spike_threshold,
        vol_ratio_min=vol_ratio_min,
        name=symbol,
    )
    return eng.run(df_1m, backtest_cfg or CandleBacktestConfig())
