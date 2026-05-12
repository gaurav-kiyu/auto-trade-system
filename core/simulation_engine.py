"""
Deep simulation engine for strategy edge validation.

Extends the basic candle backtest with:
  • Trailing stop-loss (% trail from peak premium, activates after profit target)
  • Score component decomposition (which of the 7 scoring factors fired per trade)
  • Signal classification: EARLY (65-74) / CONFIRMED (75-82) / STRONG (83+)
  • Deterministic bid-ask spread on option premium (no random noise — reproducible)
  • Per-trade feature analysis: breakout, regime, RSI, MACD presence logged
  • Score segment analysis: weak/medium/strong bucket performance
  • Failure mode tagging: which condition was present in losing trades

Design principles:
  - Same signal pipeline as live system (evaluate_index_signal_partial)
  - No look-ahead bias (signal generated on bar N, entry on bar N+1 open)
  - Slippage applied at entry AND exit (round-trip cost model)
  - Trailing SL activates only after TRAIL_ACTIVATE_PCT gain on option premium
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from core.adaptive_signal import evaluate_adaptive_signal
from core.option_premium_model import (
    OptionTradeSpec,
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
from core.tier_engine import adaptive_threshold, classify_tier, get_tier_rules

# ── Signal type thresholds — must mirror tier_engine.py constants ──────────
# Single source of truth for tier boundaries: core/tier_engine.py
# These aliases keep simulation_engine self-contained for import safety.
SIGNAL_EARLY     = 60   # TIER_WEAK_MIN     — minimum to trade
SIGNAL_CONFIRMED = 70   # TIER_MODERATE_MIN — medium confidence
SIGNAL_STRONG    = 80   # TIER_STRONG_MIN   — full size / high confidence

def classify_signal_type(score: int) -> str:
    if score >= SIGNAL_STRONG:    return "STRONG"
    if score >= SIGNAL_CONFIRMED: return "MODERATE"
    return "WEAK"


# ── Bid-ask spread model (deterministic) ──────────────────────────────────
# Real NSE option bid-ask spread ≈ 1.5-3% of premium for liquid indices
# We apply half on entry (paying the ask) and half on exit (hitting the bid)
_BID_ASK_HALF = 0.015   # 1.5% of premium each side = 3% round-trip


# ── Score segment classification ──────────────────────────────────────────
def score_segment(score: int) -> str:
    if score >= SIGNAL_STRONG:    return "Strong (80+)"
    if score >= SIGNAL_CONFIRMED: return "Moderate (70-79)"
    return "Weak (60-69)"


# ── Frame building ────────────────────────────────────────────────────────
def _build_frames(base_df: pd.DataFrame, upto: int) -> dict[str, pd.DataFrame]:
    window = base_df.iloc[: upto + 1].copy()
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    frames: dict[str, pd.DataFrame] = {"1m": window.copy()}
    for rule, key in (("5min", "5m"), ("15min", "15m")):
        rs = window.resample(rule, label="right", closed="right").agg(agg).dropna(
            subset=["Open", "High", "Low", "Close"]
        )
        frames[key] = rs
    return frames


def _synthetic_oi(price: float) -> tuple[float, float, float, str]:
    if price <= 0:
        return 0.0, 0.0, 1.0, "NEUTRAL"
    return round(price * 0.99, 2), round(price * 1.01, 2), 1.0, "NEUTRAL"


# ── Configuration ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SimConfig:
    # Capital and position
    initial_capital: float = 100_000.0
    lots_per_trade: int    = 1

    # Entry/exit mechanics
    warmup_bars: int       = 35
    latency_bars: int      = 1       # realistic 1-bar execution lag
    max_bars_in_trade: int = 40      # 40-min max hold
    cooldown_bars: int     = 30      # min bars between trades

    # Score gate
    score_threshold: int   = 65
    score_gap: int         = 0       # additional margin above threshold

    # Risk parameters
    sl_atr_mult: float     = 1.2
    tp_atr_mult: float     = 1.618   # primary TP (regime-adaptive)
    use_regime_rr: bool    = True    # TRENDING→wider TP, CHOPPY→tighter

    # Trailing stop
    trail_activate_pct: float = 0.30  # activate trailing after 30% premium gain
    trail_from_peak_pct: float = 0.20  # trail at 20% below peak (option space)

    # Option model
    use_option_model: bool = True
    vix: float             = 14.0
    dte: int               = 3
    delta_scale: float     = 1.5

    # Session open filter
    # NSE opens 03:45 UTC (09:15 IST). Skip signal generation for the first N minutes
    # of each trading session to avoid gap-open noise (overbought RSI, no VWAP confirmation).
    session_open_skip_minutes: int = 15  # skip 03:45–03:59 UTC = 09:15–09:29 IST

    # Costs
    fee_per_lot: float     = 40.0    # round-trip brokerage + STT per lot
    # bid_ask cost is applied via _BID_ASK_HALF constant (1.5% each side)

    # ── Tiered adaptive mode ─────────────────────────────────────────────
    use_tiered: bool   = False   # enable tiered adaptive signal + position sizing
    trade_weak: bool   = False   # include WEAK-tier signals (score 60-64) when use_tiered=True
    adaptive_threshold_enabled: bool = False   # shift entry threshold by regime


# ── Trade record ──────────────────────────────────────────────────────────
@dataclass
class TradeRecord:
    # Identity
    trade_id: int
    entry_time: str
    exit_time: str
    symbol: str
    direction: str          # CALL / PUT

    # Score & signal quality
    score: int
    threshold: int
    signal_type: str        # EARLY / CONFIRMED / STRONG
    score_segment: str      # Weak / Medium / Strong
    score_components: dict[str, int]  # component breakdown
    features_triggered: list[str]    # human-readable list of fired features

    # Prices (index space)
    entry_index: float
    exit_index: float
    sl_index: float
    tp_index: float

    # Prices (option space)
    entry_premium: float    # 0 if option model off
    exit_premium: float
    sl_premium: float
    tp_premium: float
    peak_premium: float     # highest premium reached during trade

    # Execution
    delta: float
    lot_size_n: int
    exit_reason: str        # stop_loss / take_profit / trail_sl / time_exit
    bars_held: int
    slippage_cost: float    # total bid-ask + slippage cost for this trade

    # P&L
    gross_pnl: float
    net_pnl: float
    rr_achieved: float      # realised R multiple
    pct_pnl: float          # % gain/loss on option premium

    # Context
    regime: str
    adx: float
    rsi: float
    vwap: float
    vol_ratio: float
    breakout_ok: bool
    macd_histogram: float

    # Classification
    is_winner: bool
    failure_tags: list[str]  # what conditions were present in losers

    # Tiered adaptive fields (populated when cfg.use_tiered=True, else defaults)
    tier: str = "STRONG"          # STRONG / MODERATE / WEAK
    confidence: float = 1.0       # 0-1 signal confidence (lower with soft blocks)
    soft_blocks: list = field(default_factory=list)   # soft-rejection conditions applied
    position_lots: int = 1        # actual lots used (may differ from cfg.lots_per_trade)


# ── Segment + regime analytics ────────────────────────────────────────────
@dataclass
class SegmentStats:
    label: str
    trades: int       = 0
    wins: int         = 0
    total_gross: float = 0.0
    total_net: float   = 0.0
    pct_pnls: list     = field(default_factory=list)
    rr_vals: list      = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return round(self.wins / self.trades * 100, 2) if self.trades else 0.0

    @property
    def avg_net(self) -> float:
        return round(self.total_net / self.trades, 2) if self.trades else 0.0

    @property
    def win_trades(self) -> list:
        return []  # populated separately if needed

    def expectancy(self, win_trades_net: list[float], loss_trades_net: list[float]) -> float:
        if not (win_trades_net or loss_trades_net):
            return 0.0
        wr = len(win_trades_net) / (len(win_trades_net) + len(loss_trades_net))
        aw = float(np.mean(win_trades_net)) if win_trades_net else 0.0
        al = abs(float(np.mean(loss_trades_net))) if loss_trades_net else 0.0
        return round(wr * aw - (1 - wr) * al, 2)


@dataclass
class SimulationResult:
    records: list[TradeRecord]
    equity_curve: list[float]
    ending_capital: float
    initial_capital: float
    config: SimConfig

    # Signal pipeline diagnostics
    signal_attempts: int       = 0
    signal_rejections: dict    = field(default_factory=dict)  # reason → count
    score_distribution: dict   = field(default_factory=dict)  # "50-54" → count of scored-but-rejected bars

    # Pre-computed analytics (filled by _compute_analytics)
    total_trades: int          = 0
    wins: int                  = 0
    losses: int                = 0
    win_rate: float            = 0.0
    profit_factor: float       = 0.0
    expectancy_net: float      = 0.0
    expectancy_gross: float    = 0.0
    avg_win_net: float         = 0.0
    avg_loss_net: float        = 0.0
    avg_win_pct: float         = 0.0
    avg_loss_pct: float        = 0.0
    avg_rr_achieved: float     = 0.0
    rr_ratio: float            = 0.0
    max_drawdown_pct: float    = 0.0
    sharpe: float              = 0.0
    calmar: float              = 0.0
    net_return_pct: float      = 0.0
    # Breakdown dicts
    by_segment: dict[str, SegmentStats]    = field(default_factory=dict)
    by_regime:  dict[str, SegmentStats]    = field(default_factory=dict)
    by_direction: dict[str, SegmentStats]  = field(default_factory=dict)
    by_exit:    dict[str, int]             = field(default_factory=dict)
    by_breakout: dict[str, SegmentStats]   = field(default_factory=dict)
    by_tier:    dict[str, SegmentStats]    = field(default_factory=dict)   # tiered analytics
    # Per-day expectancy
    daily_pnl: dict[str, float]            = field(default_factory=dict)
    # Worst trades
    worst_trades: list[TradeRecord]        = field(default_factory=list)
    # Feature edge
    feature_edge: dict[str, dict]          = field(default_factory=dict)


# ── Simulation engine ─────────────────────────────────────────────────────
class SimulationEngine:
    """
    Bar-by-bar simulation with trailing SL, score breakdown, and signal classification.

    Entry flow:
      bar N  : signal generated (evaluate_index_signal_partial)
      bar N+1: entry at Open price (latency_bars=1)

    Exit flow (checked each bar while in trade, in priority order):
      1. Stop-loss hit (index SL)
      2. Take-profit hit (index TP)
      3. Trailing SL hit (option premium trail)
      4. Time exit (max_bars_in_trade)
    """

    def __init__(
        self,
        *,
        signal_cfg: Mapping[str, Any],
        regime_params: PureIndexRegimeParams,
        iv_spike_threshold: float = 45.0,
        vol_ratio_min: float = 1.2,
        name: str = "NIFTY",
    ) -> None:
        self._sc   = dict(signal_cfg)
        # Frame alignment check is for live async streams where 5m/15m data can lag.
        # In simulation we build all frames from the same 1m DataFrame, so they are
        # always temporally consistent. label="right" resampling puts the 5m bar label
        # up to 4 min ahead of the last 1m bar → the 120s default tolerance blocks ~80%
        # of signal attempts. Override to effectively disable the check here.
        self._sc["FRAME_ALIGN_1M_5M"]  = 99999
        self._sc["FRAME_ALIGN_1M_15M"] = 99999
        self._rp   = regime_params
        self._iv   = float(iv_spike_threshold)
        self._vrm  = float(vol_ratio_min)
        self._name = name

    # ── Public entry ──────────────────────────────────────────────────
    def run(self, base_1m: pd.DataFrame, cfg: SimConfig | None = None) -> SimulationResult:
        cfg = cfg or SimConfig()
        records: list[TradeRecord] = []
        equity: list[float] = []
        capital = float(cfg.initial_capital)
        peak    = capital
        max_dd  = 0.0
        position: dict[str, Any] | None = None
        pending: dict[str, Any] | None  = None
        cooldown_until = -1
        trade_id = 0
        n = len(base_1m)
        warmup = max(20, int(cfg.warmup_bars))
        _attempts = 0
        _rejects: dict[str, int] = {}
        _score_dist: dict[str, int] = {}  # score bucket → count for scored-but-rejected bars

        for idx in range(warmup, n):
            row = base_1m.iloc[idx]
            ts  = str(base_1m.index[idx])

            # ── Execute pending order ────────────────────────────────
            if pending is not None and pending["enter_on_idx"] == idx:
                position, capital = self._execute_entry(pending, row, idx, ts, cfg, capital)
                pending = None

            # ── Check exits (SL / TP / trail / time) ────────────────
            if position is not None:
                # Update trailing SL from this bar's high/low
                self._update_trail(position, row, cfg)
                exit_px, reason = self._check_exit(position, row, idx)
                if exit_px is not None:
                    trade_id += 1
                    rec, capital, peak, max_dd = self._close_trade(
                        trade_id, records, capital, peak, max_dd,
                        position, ts, float(exit_px), reason, idx, cfg,
                    )
                    records.append(rec)
                    position = None
                    cooldown_until = idx + int(cfg.cooldown_bars)
                    equity.append(capital)
                    continue

            equity.append(capital)
            if position is not None or idx < cooldown_until:
                continue

            # ── Session open filter ──────────────────────────────────
            # NSE opens 03:45 UTC. Skip the first N minutes to avoid gap-open entries
            # (extreme RSI, VWAP = price, no intraday confirmation yet).
            if cfg.session_open_skip_minutes > 0:
                try:
                    bt = base_1m.index[idx]
                    bar_min = bt.hour * 60 + bt.minute
                    session_open = 3 * 60 + 45  # 03:45 UTC
                    if session_open <= bar_min < session_open + cfg.session_open_skip_minutes:
                        continue
                except Exception:
                    pass

            # ── Generate signal ──────────────────────────────────────
            _attempts += 1
            frames = _build_frames(base_1m, idx)
            df1, df5, df15 = frames["1m"], frames["5m"], frames["15m"]
            price = float(df1["Close"].iloc[-1])
            sup, res, pcr, smart = _synthetic_oi(price)

            sig_params = PureIndexSignalParams(
                name=self._name,
                signal_cfg=self._sc,
                regime=self._rp,
                iv_spike_threshold=self._iv,
                vol_ratio_min=self._vrm,
                is_early_session=False,
            )

            # ── Tiered adaptive path ──────────────────────────────────
            if cfg.use_tiered:
                adaptive_sig, reason = evaluate_adaptive_signal(
                    params=sig_params,
                    df1=df1, df5=df5, df15=df15,
                    vix=float(cfg.vix), iv=0.0,
                    oi_sup=sup, oi_res=res,
                    pcr=pcr, smart=smart,
                    learning_score_bonus=0,
                    max_lots=int(cfg.lots_per_trade),
                    capital=capital,
                )
                if adaptive_sig is None:
                    _rejects[reason] = _rejects.get(reason, 0) + 1
                    continue

                # Apply adaptive threshold adjustment if enabled
                thr = int(cfg.score_threshold)
                if cfg.adaptive_threshold_enabled:
                    thr = adaptive_threshold(thr, adaptive_sig.regime)

                score = int(adaptive_sig.score)
                if adaptive_sig.tier == "IGNORE":
                    _rejects["score_too_low"] = _rejects.get("score_too_low", 0) + 1
                    lo = (score // 5) * 5
                    bk = f"{lo:02d}-{lo+4:02d}"
                    _score_dist[bk] = _score_dist.get(bk, 0) + 1
                    continue
                if not cfg.trade_weak and adaptive_sig.tier == "WEAK":
                    _rejects["score_too_low"] = _rejects.get("score_too_low", 0) + 1
                    lo = (score // 5) * 5
                    bk = f"{lo:02d}-{lo+4:02d}"
                    _score_dist[bk] = _score_dist.get(bk, 0) + 1
                    continue

                tier_rules = get_tier_rules(score)
                enter_on = idx + max(0, int(cfg.latency_bars))
                if enter_on >= n:
                    continue

                ref_row   = base_1m.iloc[enter_on]
                ref_price = float(ref_row["Open"])
                atr_val   = float(adaptive_sig.atr) or ref_price * 0.005
                regime    = adaptive_sig.regime

                sl_m = cfg.sl_atr_mult * tier_rules.sl_mult_adj
                tp_m = cfg.tp_atr_mult * tier_rules.tp_mult_adj
                if cfg.use_regime_rr:
                    base_sl, base_tp = regime_rr_targets(regime, cfg.sl_atr_mult, cfg.tp_atr_mult)
                    sl_m = float(base_sl) * tier_rules.sl_mult_adj
                    tp_m = float(base_tp) * tier_rules.tp_mult_adj

                max_bars = max(4, int(cfg.max_bars_in_trade * tier_rules.max_bars_mult))
                trail_act = tier_rules.trail_activate_pct if tier_rules.trail_enabled else 99.0
                trail_peak = tier_rules.trail_from_peak_pct if tier_rules.trail_enabled else 0.99

                pending = {
                    "enter_on_idx":  enter_on,
                    "direction":     adaptive_sig.direction,
                    "ref_price":     ref_price,
                    "atr":           atr_val,
                    "sl_mult":       float(sl_m),
                    "tp_mult":       float(tp_m),
                    "score":         score,
                    "threshold":     thr,
                    "regime":        regime,
                    "partial":       {
                        "score": score,
                        "direction": adaptive_sig.direction,
                        "mkt_regime": regime,
                        "adx": adaptive_sig.adx,
                        "rsi": adaptive_sig.rsi,
                        "vwap": adaptive_sig.vwap,
                        "atr": atr_val,
                        "vol_ratio": adaptive_sig.vol_ratio,
                        "breakout_ok": "breakout" in adaptive_sig.features,
                        "score_components": dict(adaptive_sig.score_components),
                        "macd": dict(adaptive_sig.macd),
                    },
                    "fin":           {"action": "BUY", "direction": adaptive_sig.direction},
                    # Tiered metadata
                    "tier":          adaptive_sig.tier,
                    "confidence":    adaptive_sig.confidence,
                    "soft_blocks":   list(adaptive_sig.soft_blocks),
                    "position_lots": int(adaptive_sig.position_spec.lots),
                    "max_bars_override": max_bars,
                    "trail_activate_override": trail_act,
                    "trail_peak_override": trail_peak,
                }
                continue  # pending will be picked up on the next iteration

            # ── Standard (non-tiered) path ────────────────────────────
            partial, reason = evaluate_index_signal_partial(
                params=sig_params,
                df1=df1, df5=df5, df15=df15,
                vix=float(cfg.vix), iv=0.0,
                oi_sup=sup, oi_res=res,
                pcr=pcr, smart=smart,
                learning_score_bonus=0,
            )
            if partial is None:
                _rejects[reason] = _rejects.get(reason, 0) + 1
                continue

            score = int(partial["score"])
            thr   = int(cfg.score_threshold)
            if score < thr + int(cfg.score_gap):
                _rejects["score_too_low"] = _rejects.get("score_too_low", 0) + 1
                lo = (score // 5) * 5
                bk = f"{lo:02d}-{lo+4:02d}"
                _score_dist[bk] = _score_dist.get(bk, 0) + 1
                continue

            fin = finalize_index_signal_with_threshold(
                partial, threshold=thr, regime="SIM",
                adaptive_delta=0, adaptive_reason="frozen",
                trace_id=f"sim-{idx}", signal_cfg=self._sc,
            )
            if fin.get("action") != "BUY":
                continue

            enter_on = idx + max(0, int(cfg.latency_bars))
            if enter_on >= n:
                continue

            ref_row   = base_1m.iloc[enter_on]
            ref_price = float(ref_row["Open"])
            atr_val   = float(fin.get("atr") or ref_price * 0.005)
            regime    = str(fin.get("mkt_regime") or "NEUTRAL")

            sl_m, tp_m = (regime_rr_targets(regime, cfg.sl_atr_mult, cfg.tp_atr_mult)
                          if cfg.use_regime_rr else (cfg.sl_atr_mult, cfg.tp_atr_mult))

            pending = {
                "enter_on_idx": enter_on,
                "direction":    fin["direction"],
                "ref_price":    ref_price,
                "atr":          atr_val,
                "sl_mult":      float(sl_m),
                "tp_mult":      float(tp_m),
                "score":        score,
                "threshold":    thr,
                "regime":       regime,
                "partial":      dict(partial),
                "fin":          dict(fin),
            }

        result = SimulationResult(
            records=records,
            equity_curve=equity,
            ending_capital=round(capital, 2),
            initial_capital=float(cfg.initial_capital),
            config=cfg,
            signal_attempts=_attempts,
            signal_rejections=_rejects,
            score_distribution=_score_dist,
        )
        _compute_analytics(result)
        return result

    # ── Entry execution ───────────────────────────────────────────────
    def _execute_entry(
        self, pending: dict, row: pd.Series, idx: int,
        ts: str, cfg: SimConfig, capital: float,
    ) -> tuple[dict[str, Any], float]:
        direction  = str(pending["direction"])
        raw_price  = float(pending["ref_price"])
        atr        = float(pending["atr"])
        sl_m       = float(pending["sl_mult"])
        tp_m       = float(pending["tp_mult"])
        regime     = str(pending["regime"])
        partial    = pending["partial"]
        score      = int(pending["score"])

        # Slippage on index (0.05% each side)
        slip = 0.0005
        if direction == "CALL":
            entry_idx = raw_price * (1 + slip)
            sl_idx    = entry_idx - atr * sl_m
            tp_idx    = entry_idx + atr * tp_m
        else:
            entry_idx = raw_price * (1 - slip)
            sl_idx    = entry_idx + atr * sl_m
            tp_idx    = entry_idx - atr * tp_m

        entry_prem = 0.0
        opt_spec: OptionTradeSpec | None = None
        if cfg.use_option_model:
            opt_spec   = build_option_trade(
                self._name, direction, entry_idx, atr,
                cfg.vix, sl_idx, tp_idx, cfg.dte, cfg.delta_scale,
            )
            # Apply half bid-ask on entry (paying the ask)
            entry_prem = round(opt_spec.entry_premium * (1 + _BID_ASK_HALF), 2)
            opt_spec   = OptionTradeSpec(
                **{**vars(opt_spec), "entry_premium": entry_prem}
            )

        # Components and feature list
        components = dict(partial.get("score_components") or {})
        features   = [k for k, v in components.items() if v > 0]

        # Tiered overrides (present only in use_tiered path)
        lots        = int(pending.get("position_lots") or cfg.lots_per_trade)
        max_bars    = int(pending.get("max_bars_override") or cfg.max_bars_in_trade)
        trail_act   = float(pending.get("trail_activate_override") or cfg.trail_activate_pct)
        trail_peak  = float(pending.get("trail_peak_override") or cfg.trail_from_peak_pct)
        tier_label  = str(pending.get("tier") or classify_tier(score))
        confidence  = float(pending.get("confidence") or 1.0)
        soft_blocks = list(pending.get("soft_blocks") or [])

        capital = round(capital - float(cfg.fee_per_lot) * lots, 2)

        position = {
            "entry_idx":         idx,
            "entry_time":        ts,
            "entry_price":       round(entry_idx, 4),
            "stop_loss":         round(sl_idx, 4),
            "tp":                round(tp_idx, 4),
            "direction":         direction,
            "lots":              lots,
            "entry_prem":        round(entry_prem, 2),
            "opt_spec":          opt_spec,
            "peak_prem":         float(entry_prem),
            "trail_sl_prem":     0.0,
            "trail_activate":    trail_act,
            "trail_from_peak":   trail_peak,
            "max_bars":          max_bars,
            "score":             score,
            "threshold":         int(pending["threshold"]),
            "regime":            regime,
            "signal_type":       classify_signal_type(score),
            "seg":               score_segment(score),
            "tier":              tier_label,
            "confidence":        confidence,
            "soft_blocks":       soft_blocks,
            "components":        components,
            "features":          features,
            "meta": {
                "rsi":        float(partial.get("rsi", 50.0)),
                "adx":        float(partial.get("adx", 0.0)),
                "vwap":       float(partial.get("vwap", 0.0)),
                "vol_ratio":  float(partial.get("vol_ratio", 0.0)),
                "breakout_ok": bool(partial.get("breakout_ok", False)),
                "macd_hist":  float((partial.get("macd") or {}).get("histogram", 0.0)),
            },
        }
        return position, capital

    # ── Trailing SL update (per bar) ──────────────────────────────────
    def _update_trail(self, position: dict, row: pd.Series, cfg: SimConfig) -> None:
        """Update option-space trailing stop from current bar's option premium."""
        if not cfg.use_option_model:
            return
        opt_spec = position.get("opt_spec")
        if opt_spec is None:
            return
        direction  = str(position["direction"])
        entry_prem = float(position["entry_prem"])
        hi, lo     = float(row["High"]), float(row["Low"])

        # Estimate current bar's best-case premium
        if direction == "CALL":
            bar_move = hi - float(opt_spec.entry_index)
        else:
            bar_move = float(opt_spec.entry_index) - lo
        curr_prem = max(1.0, entry_prem + bar_move * float(opt_spec.delta))

        # Update peak
        if curr_prem > position["peak_prem"]:
            position["peak_prem"] = curr_prem

        # Activate trailing stop once profit >= trail_activate_pct
        # Use tier-specific values if stored in position (tiered path), else cfg defaults
        trail_act_pct  = float(position.get("trail_activate",  cfg.trail_activate_pct))
        trail_peak_pct = float(position.get("trail_from_peak", cfg.trail_from_peak_pct))
        peak = float(position["peak_prem"])
        activate_level = entry_prem * (1.0 + trail_act_pct)
        if peak >= activate_level:
            new_trail = peak * (1.0 - trail_peak_pct)
            if new_trail > float(position["trail_sl_prem"]):
                position["trail_sl_prem"] = round(new_trail, 2)

    # ── Exit check ────────────────────────────────────────────────────
    def _check_exit(
        self, position: dict, row: pd.Series, idx: int,
    ) -> tuple[float | None, str]:
        direction = str(position["direction"])
        sl        = float(position["stop_loss"])
        tp        = float(position["tp"])
        held      = idx - int(position["entry_idx"])
        hi        = float(row["High"])
        lo        = float(row["Low"])
        close_px  = float(row["Close"])

        if direction == "CALL":
            if lo <= sl: return sl, "stop_loss"
            if hi >= tp: return tp, "take_profit"
        else:
            if hi >= sl: return sl, "stop_loss"
            if lo <= tp: return tp, "take_profit"

        # Trailing SL (option-space)
        trail_sl = float(position.get("trail_sl_prem", 0.0))
        if trail_sl > 0:
            opt_spec = position.get("opt_spec")
            if opt_spec is not None:
                if direction == "CALL":
                    curr_prem = float(opt_spec.entry_premium) + (close_px - float(opt_spec.entry_index)) * float(opt_spec.delta)
                else:
                    curr_prem = float(opt_spec.entry_premium) + (float(opt_spec.entry_index) - close_px) * float(opt_spec.delta)
                if curr_prem <= trail_sl:
                    return close_px, "trail_sl"

        if held >= int(position.get("max_bars", 40)):
            return close_px, "time_exit"
        return None, ""

    # ── Trade close ───────────────────────────────────────────────────
    def _close_trade(
        self, trade_id: int, records: list, capital: float,
        peak: float, max_dd: float,
        position: dict, ts: str, exit_index: float,
        reason: str, idx: int, cfg: SimConfig,
    ) -> tuple[TradeRecord, float, float, float]:
        entry_idx  = float(position["entry_price"])
        direction  = str(position["direction"])
        lots       = int(position["lots"])
        entry_prem = float(position["entry_prem"])
        opt_spec   = position.get("opt_spec")
        meta       = position.get("meta") or {}

        exit_prem   = 0.0
        rr          = 0.0
        pct_pnl     = 0.0
        gross       = 0.0
        slip_cost   = 0.0

        if cfg.use_option_model and opt_spec is not None:
            pnl_info = calc_option_pnl(opt_spec, exit_index, reason, fee_per_lot=0.0)
            raw_exit_prem = float(pnl_info["exit_premium"])
            # Apply half bid-ask on exit (hitting the bid)
            exit_prem = round(raw_exit_prem * (1 - _BID_ASK_HALF), 2)
            slip_cost = round(
                (entry_prem * _BID_ASK_HALF + raw_exit_prem * _BID_ASK_HALF) * opt_spec.lot_size_n * lots,
                2,
            )
            gross   = round((exit_prem - entry_prem) * opt_spec.lot_size_n * lots, 2)
            sl_risk = max(0.01, entry_prem - float(opt_spec.sl_premium))
            rr      = round((exit_prem - entry_prem) / sl_risk, 3)
            pct_pnl = round((exit_prem - entry_prem) / entry_prem * 100, 2)
        else:
            if direction == "CALL":
                gross = round((exit_index - entry_idx) * lots, 2)
            else:
                gross = round((entry_idx - exit_index) * lots, 2)
            pct_pnl = round((exit_index - entry_idx) / entry_idx * 100, 2)

        net    = round(gross - float(cfg.fee_per_lot) * lots, 2)
        capital = round(capital + net, 2)
        peak    = max(peak, capital)
        if peak > 0:
            max_dd = max(max_dd, (peak - capital) / peak * 100.0)

        # Failure tags (for losing trades)
        failure_tags: list[str] = []
        if net < 0:
            if not meta.get("breakout_ok"):
                failure_tags.append("no_breakout")
            rsi_v = float(meta.get("rsi", 50))
            if rsi_v > 72 or rsi_v < 28:
                failure_tags.append("rsi_extreme")
            if float(meta.get("adx", 25)) < 16:
                failure_tags.append("low_adx")
            if float(meta.get("vol_ratio", 1.5)) < 1.0:
                failure_tags.append("low_volume")
            if reason == "time_exit":
                failure_tags.append("time_exit_loss")
            if position.get("seg") == "Weak (60-69)":
                failure_tags.append("weak_signal")

        rec = TradeRecord(
            trade_id          = trade_id,
            entry_time        = str(position["entry_time"]),
            exit_time         = ts,
            symbol            = self._name,
            direction         = direction,
            score             = int(position["score"]),
            threshold         = int(position["threshold"]),
            signal_type       = str(position["signal_type"]),
            score_segment     = str(position["seg"]),
            score_components  = dict(position["components"]),
            features_triggered= list(position["features"]),
            entry_index       = round(entry_idx, 2),
            exit_index        = round(exit_index, 2),
            sl_index          = float(position["stop_loss"]),
            tp_index          = float(position["tp"]),
            entry_premium     = round(entry_prem, 2),
            exit_premium      = round(exit_prem, 2),
            sl_premium        = float(opt_spec.sl_premium) if opt_spec else 0.0,
            tp_premium        = float(opt_spec.tp_premium) if opt_spec else 0.0,
            peak_premium      = round(float(position["peak_prem"]), 2),
            delta             = float(opt_spec.delta) if opt_spec else 0.0,
            lot_size_n        = int(opt_spec.lot_size_n) if opt_spec else 1,
            exit_reason       = reason,
            bars_held         = idx - int(position["entry_idx"]),
            slippage_cost     = slip_cost,
            gross_pnl         = round(gross, 2),
            net_pnl           = round(net, 2),
            rr_achieved       = rr,
            pct_pnl           = pct_pnl,
            regime            = str(position["regime"]),
            adx               = float(meta.get("adx", 0.0)),
            rsi               = float(meta.get("rsi", 50.0)),
            vwap              = float(meta.get("vwap", 0.0)),
            vol_ratio         = float(meta.get("vol_ratio", 0.0)),
            breakout_ok       = bool(meta.get("breakout_ok", False)),
            macd_histogram    = float(meta.get("macd_hist", 0.0)),
            is_winner         = net >= 0,
            failure_tags      = failure_tags,
            tier              = str(position.get("tier") or classify_tier(int(position["score"]))),
            confidence        = float(position.get("confidence") or 1.0),
            soft_blocks       = list(position.get("soft_blocks") or []),
            position_lots     = int(position.get("lots") or 1),
        )
        return rec, capital, peak, max_dd


# ── Analytics computation ─────────────────────────────────────────────────
def _make_seg() -> SegmentStats:
    return SegmentStats(label="")

def _compute_analytics(result: SimulationResult) -> None:
    """Fill all aggregate analytics on the result in-place."""
    records = result.records
    if not records:
        return

    wins   = [r for r in records if r.is_winner]
    losses = [r for r in records if not r.is_winner]
    total  = len(records)

    result.total_trades   = total
    result.wins           = len(wins)
    result.losses         = len(losses)
    result.win_rate       = round(len(wins) / total * 100, 2)
    result.avg_win_net    = round(float(np.mean([r.net_pnl for r in wins])), 2) if wins else 0.0
    result.avg_loss_net   = round(float(np.mean([r.net_pnl for r in losses])), 2) if losses else 0.0
    result.avg_win_pct    = round(float(np.mean([r.pct_pnl for r in wins])), 2) if wins else 0.0
    result.avg_loss_pct   = round(float(np.mean([r.pct_pnl for r in losses])), 2) if losses else 0.0
    result.avg_rr_achieved = round(float(np.mean([r.rr_achieved for r in records])), 3)
    rr_denom = abs(result.avg_loss_net) if result.avg_loss_net < 0 else 1.0
    result.rr_ratio       = round(result.avg_win_net / rr_denom, 3) if rr_denom > 0 else 0.0

    gp = sum(r.net_pnl for r in wins)
    gl = abs(sum(r.net_pnl for r in losses))
    result.profit_factor  = round(gp / gl, 4) if gl > 0 else (9999.0 if gp > 0 else 0.0)

    # Expectancy
    wr = result.win_rate / 100
    lr = 1 - wr
    result.expectancy_net   = round(wr * result.avg_win_net   - lr * abs(result.avg_loss_net), 2)
    result.expectancy_gross = round(wr * float(np.mean([r.gross_pnl for r in wins]) if wins else 0)
                                    - lr * abs(float(np.mean([r.gross_pnl for r in losses]) if losses else 0)), 2)

    # Sharpe (trade-level)
    pnls = np.array([r.net_pnl for r in records])
    result.sharpe = round(float(np.mean(pnls) / np.std(pnls) * math.sqrt(252)), 3) if np.std(pnls) > 0 else 0.0

    # Calmar
    result.net_return_pct = round((result.ending_capital - result.initial_capital) / result.initial_capital * 100, 2)
    result.max_drawdown_pct = max((getattr(result, "max_drawdown_pct", 0) or 0),
                                  _calc_max_dd(result.equity_curve))
    result.calmar = round(result.net_return_pct / result.max_drawdown_pct, 3) if result.max_drawdown_pct > 0 else 0.0

    # By segment
    seg_keys = ["Weak (60-69)", "Moderate (70-79)", "Strong (80+)"]
    result.by_segment = {k: SegmentStats(k) for k in seg_keys}
    for r in records:
        s = result.by_segment.get(r.score_segment)
        if s is None:
            s = SegmentStats(r.score_segment)
            result.by_segment[r.score_segment] = s
        s.trades += 1
        s.wins   += int(r.is_winner)
        s.total_net += r.net_pnl
        s.pct_pnls.append(r.pct_pnl)
        s.rr_vals.append(r.rr_achieved)

    # By regime
    for r in records:
        reg = r.regime
        if reg not in result.by_regime:
            result.by_regime[reg] = SegmentStats(reg)
        s = result.by_regime[reg]
        s.trades += 1; s.wins += int(r.is_winner); s.total_net += r.net_pnl

    # By direction
    for r in records:
        d = r.direction
        if d not in result.by_direction:
            result.by_direction[d] = SegmentStats(d)
        s = result.by_direction[d]
        s.trades += 1; s.wins += int(r.is_winner); s.total_net += r.net_pnl
        s.pct_pnls.append(r.pct_pnl)

    # By breakout
    for r in records:
        key = "Breakout" if r.breakout_ok else "No-Breakout"
        if key not in result.by_breakout:
            result.by_breakout[key] = SegmentStats(key)
        s = result.by_breakout[key]
        s.trades += 1; s.wins += int(r.is_winner); s.total_net += r.net_pnl

    # By tier
    for r in records:
        t = getattr(r, "tier", "STRONG")
        if t not in result.by_tier:
            result.by_tier[t] = SegmentStats(t)
        s = result.by_tier[t]
        s.trades += 1; s.wins += int(r.is_winner)
        s.total_net += r.net_pnl
        s.pct_pnls.append(r.pct_pnl)
        s.rr_vals.append(r.rr_achieved)

    # By exit reason
    for r in records:
        result.by_exit[r.exit_reason] = result.by_exit.get(r.exit_reason, 0) + 1

    # Per-day expectancy
    for r in records:
        day = r.entry_time[:10]
        result.daily_pnl[day] = result.daily_pnl.get(day, 0.0) + r.net_pnl

    # Worst trades (bottom 5 by net_pnl)
    result.worst_trades = sorted(records, key=lambda r: r.net_pnl)[:5]

    # Feature edge: for each feature, win rate when present vs absent
    all_features = ["tf_aligned", "vwap", "d1_momentum", "d5_momentum",
                    "volume", "rsi_bonus", "breakout", "macd_bonus"]
    for feat in all_features:
        with_w = sum(1 for r in records if r.score_components.get(feat, 0) > 0 and r.is_winner)
        with_t = sum(1 for r in records if r.score_components.get(feat, 0) > 0)
        sans_w = sum(1 for r in records if r.score_components.get(feat, 0) <= 0 and r.is_winner)
        sans_t = sum(1 for r in records if r.score_components.get(feat, 0) <= 0)
        result.feature_edge[feat] = {
            "with_wr": round(with_w / with_t * 100, 1) if with_t else 0.0,
            "sans_wr": round(sans_w / sans_t * 100, 1) if sans_t else 0.0,
            "with_n":  with_t,
            "sans_n":  sans_t,
        }


def _calc_max_dd(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100.0)
    return round(max_dd, 4)


# ── Convenience function ──────────────────────────────────────────────────
def run_simulation(
    df_1m: pd.DataFrame,
    *,
    signal_cfg: Mapping[str, Any],
    regime_params: PureIndexRegimeParams,
    sim_cfg: SimConfig | None = None,
    symbol: str = "NIFTY",
) -> SimulationResult:
    engine = SimulationEngine(
        signal_cfg=signal_cfg,
        regime_params=regime_params,
        iv_spike_threshold=float(signal_cfg.get("IV_SPIKE_THRESHOLD", 45)),
        vol_ratio_min=float(signal_cfg.get("VOL_RATIO_MIN", 1.2)),
        name=symbol,
    )
    return engine.run(df_1m, sim_cfg or SimConfig())
