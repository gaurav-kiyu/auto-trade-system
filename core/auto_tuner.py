"""
Safe auto-tuning system for the OPB index options trading bot.

Philosophy:
  Suggestions over actions.  Stability over optimisation.  Simplicity over intelligence.

Only the parameters in _TUNABLE_PARAMS and _TUNABLE_REGIME_SIZE may ever be written.
Everything else is permanently blocked — see _blockedExceptions.

Confidence model:
  HIGH   >= 30 trades in the relevant sample AND clear statistical gap (WR off by > 15 pp)
  MEDIUM  15-29 trades OR borderline signal — produces suggestion text, never auto-applied
  LOW    < 15 trades — flag only, not acted on

Config flags (in config.json):
  AUTO_TUNE_ENABLED  (bool, default false) — gate for any file write
  AUTO_TUNE_DRY_RUN  (bool, default true)  — print recommendations, never write files
  AUTO_TUNE_MIN_TRADES (int, default 20)   — minimum trades required before ANY action

Usage:
  python -m core.auto_tuner                        # dry-run report
  python -m core.auto_tuner --apply                # apply HIGH-confidence (needs ENABLED=true)
  python -m core.auto_tuner --days 30              # limit analysis window
  python -m core.auto_tuner --config config.json   # explicit config path
  python -m core.auto_tuner --db trades.db --json  # machine-readable output
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from core.performance_metrics import (
    compute_drawdown,
    compute_metrics,
    load_trades,
    metrics_by_regime,
    metrics_by_score_bin,
)
from core.time_provider import time_provider

log = logging.getLogger("auto_tuner")

# ── Tuning constants ──────────────────────────────────────────────────────────

_MIN_TRADES_MEDIUM  = 15   # minimum trades for MEDIUM confidence
_MIN_TRADES_HIGH    = 30   # minimum trades for HIGH confidence
_MAX_CHANGES_PER_RUN = 2   # hard cap: never change more than 2 params per EOD run

_DEFAULT_CONFIG     = "config.json"
_DEFAULT_DB         = "trades.db"
_BACKUP_DIR         = Path("backups")
_AUDIT_LOG          = Path("reports/auto_tune_log.jsonl")
_MAX_BACKUP_FILES   = 5

# ── Whitelist: ONLY these keys may ever be written ────────────────────────────

_TUNABLE_PARAMS: dict[str, dict] = {
    "AI_THRESHOLD": {
        "type": "int",
        "abs_min": 60,
        "abs_max": 80,
        "max_delta": 5,
        "description": "Minimum signal score for entry",
    },
    "SIGNAL_ENTRY_SCORE_GAP": {
        "type": "int",
        "abs_min": 0,
        "abs_max": 10,
        "max_delta": 2,
        "description": "Score gap required between consecutive signals",
    },
}

_TUNABLE_REGIME_SIZE = {
    "abs_min": 0.2,
    "abs_max": 1.0,
    "max_delta": 0.2,
}

# ── Blocklist: these keys are permanently frozen ──────────────────────────────

_BLOCKED_KEYS: frozenset[str] = frozenset({
    # Credentials / broker
    "BOT_TOKEN", "CHAT_ID", "BROKER_CONFIG",
    "BROKER_API_ENABLED", "BROKER_DRIVER", "BROKER_NAME", "BROKER_CUSTOM_FACTORY",
    # Execution mode
    "EXECUTION_MODE", "MANUAL_SIGNALS_ONLY", "PAPER_MODE",
    # Risk circuit breakers
    "MAX_DAILY_LOSS", "MAX_DRAWDOWN", "BASE_CAPITAL",
    "RISK_PER_TRADE", "RISK_MODE", "RISK_FIXED_AMOUNT",
    # SL / TP / trail
    "SL_PCT", "TARGET_PCT", "TRAIL_PCT", "TRAIL_ACTIVATE",
    "ATR_SL_MULTIPLIER", "FIB_TP1_RATIO", "FIB_TP2_RATIO", "FIB_TP3_RATIO",
    # Orders / reconciliation
    "ORDER_PLACE_RETRIES", "ORDER_RETRY_WAIT_SEC", "ORDER_FILL_TIMEOUT_SEC",
    "EXIT_ORDER_RETRIES", "EXIT_RETRY_WAIT_SEC", "EXIT_FILL_TIMEOUT_SEC",
    "FORCE_PRE_TRADE_RECON", "RECONCILE_HALT_ON_QTY_MISMATCH",
    "RECONCILE_INTERVAL", "BROKER_STATUS_POLL_SEC",
    # Watchdog / circuit breaker
    "CIRCUIT_BREAKER_THRESHOLD", "WATCHDOG_TIMEOUT", "CONSEC_LOSS_LIMIT",
    # Index / lot config
    "INDEX_MAP", "INDEX_PRIORITY", "NIFTY_LOT_SIZE", "BANKNIFTY_LOT_SIZE", "FINNIFTY_LOT_SIZE",
})


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class Recommendation:
    type: str                    # "threshold" | "regime_size" | "regime_avoid" | "drawdown_warning"
    param: str                   # config key or "REGIME_SIZE_MAP.CHOPPY"
    current_value: Any
    suggested_value: Any         # None for informational-only warnings
    reason: str
    evidence: dict
    confidence: str              # "HIGH" | "MEDIUM" | "LOW"
    safe_to_apply: bool          # False for informational items and MEDIUM confidence


@dataclass
class AppliedChange:
    param: str
    old_value: Any
    new_value: Any
    ts: str
    dry_run: bool


@dataclass
class TuneResult:
    generated_at: str
    trade_sample: int
    overall_win_rate: float
    overall_expectancy: float
    overall_pf: Any
    recommendations: list[Recommendation]
    applied: list[AppliedChange]
    dry_run: bool
    enabled: bool
    backup_path: str = ""

    def to_dict(self) -> dict:
        return {
            "generated_at":      self.generated_at,
            "trade_sample":      self.trade_sample,
            "overall_win_rate":  self.overall_win_rate,
            "overall_expectancy": self.overall_expectancy,
            "overall_pf":        self.overall_pf,
            "dry_run":           self.dry_run,
            "enabled":           self.enabled,
            "backup_path":       self.backup_path,
            "recommendations": [asdict(r) for r in self.recommendations],
            "applied":          [asdict(c) for c in self.applied],
        }


# ── Core logic ────────────────────────────────────────────────────────────────

def generate_recommendations(
    trades: list[dict],
    config: dict,
) -> list[Recommendation]:
    """
    Pure function: analyse trades, return a list of Recommendation objects.
    No side effects — never reads or writes files.
    """
    if not trades:
        return []

    recs: list[Recommendation] = []

    recs.extend(_check_score_threshold(trades, config))
    recs.extend(_check_regime_sizes(trades, config))
    recs.extend(_check_drawdown(trades, config))
    recs.extend(_check_direction_skew(trades))

    # Sort: HIGH confidence first, then by type
    _order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recs.sort(key=lambda r: (_order.get(r.confidence, 3), r.type))

    return recs


def apply_recommendations(
    config_path: str,
    recommendations: list[Recommendation],
    dry_run: bool = True,
) -> list[AppliedChange]:
    """
    Apply HIGH-confidence, safe recommendations to config_path.

    Rules:
    - dry_run=True (default) -> log only, never write
    - Only Recommendation with safe_to_apply=True and confidence=="HIGH" are applied
    - Maximum _MAX_CHANGES_PER_RUN changes per call
    - backup_config() is called once before the first write
    - Writes are atomic: full JSON dump, not partial patching
    """
    applied: list[AppliedChange] = []
    actionable = [r for r in recommendations if r.safe_to_apply and r.confidence == "HIGH"]

    if not actionable:
        log.info("[AUTO-TUNE] No changes applied — no HIGH-confidence actionable recommendations")
        return applied

    cfg_path = Path(config_path)
    if not cfg_path.exists():
        log.error("[AUTO-TUNE] Config not found: %s", cfg_path)
        return applied

    config      = _load_config_file(cfg_path)
    backed_up   = False
    cooldown_days = int(config.get("AUTO_TUNE_COOLDOWN_DAYS", 7))

    for rec in actionable[:_MAX_CHANGES_PER_RUN]:
        # Cooldown gate: skip if this param was really changed within cooldown window.
        # Dry-run calls also respect the cooldown so the report is honest.
        if _in_cooldown(rec.param, cooldown_days):
            continue

        old, new = _compute_safe_change(rec, config)
        if old is None or old == new:
            continue

        if not dry_run and not backed_up:
            backup_config(cfg_path)
            backed_up = True

        change = AppliedChange(
            param=rec.param,
            old_value=old,
            new_value=new,
            ts=time_provider.format_ts(),
            dry_run=dry_run,
        )

        if not dry_run:
            _write_config_change(config, rec.param, new, cfg_path)

        applied.append(change)

        tag = "[DRY-RUN]" if dry_run else "[APPLIED]"
        log.info("[AUTO-TUNE] %s %s: %s -> %s  (restart required to take effect)", tag, rec.param, old, new)
        print(f"[AUTO-TUNE] {tag} {rec.param}: {old} -> {new}  (restart required)  ({rec.reason[:80]}…)")

    if not applied:
        log.info("[AUTO-TUNE] No changes applied — all actionable params in cooldown or already at target")

    return applied


def backup_config(config_path: str | Path) -> Path:
    """
    Copy config_path to backups/config.json.YYYYMMDD_HHMMSS.
    Prunes the oldest backups if > _MAX_BACKUP_FILES exist.
    Returns the backup path.
    """
    src = Path(config_path)
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    ts = time_provider.format_ts("%Y%m%d_%H%M%S")
    dst = _BACKUP_DIR / f"{src.name}.{ts}"
    shutil.copy2(src, dst)
    log.info("[AUTO-TUNE] Config backed up -> %s", dst)

    # Prune oldest backups
    pattern = f"{src.name}.*"
    backups = sorted(_BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime)
    while len(backups) > _MAX_BACKUP_FILES:
        old = backups.pop(0)
        old.unlink(missing_ok=True)
        log.debug("[AUTO-TUNE] Pruned old backup: %s", old)

    return dst


def run_auto_tune(
    db_path: str = _DEFAULT_DB,
    config_path: str = _DEFAULT_CONFIG,
    dry_run: bool = True,
    days: int | None = 50,
    apply: bool = False,
) -> TuneResult:
    """
    Main entry point.  Loads trades, generates recommendations, optionally applies them.

    Args:
        db_path     : path to trades.db
        config_path : path to config.json
        dry_run     : if True, never write files even if apply=True
        days        : analyse trades from the last N days (None = all time)
        apply       : if True AND dry_run=False, write approved changes to config

    Returns:
        TuneResult dataclass with all findings and applied changes.
    """
    cfg_path = Path(config_path)
    config   = _load_config_file(cfg_path) if cfg_path.exists() else {}

    # Config-level gates
    enabled   = bool(config.get("AUTO_TUNE_ENABLED", False))
    cfg_dry   = bool(config.get("AUTO_TUNE_DRY_RUN", True))
    min_trades = int(config.get("AUTO_TUNE_MIN_TRADES", 20))
    effective_dry_run = dry_run or cfg_dry or (not enabled and apply)

    trades = load_trades(db_path, days=days)
    n      = len(trades)

    ts_now = time_provider.format_ts()

    if n < min_trades:
        log.info(
            "[AUTO-TUNE] Only %d trades (need %d) — skipping analysis", n, min_trades
        )
        return TuneResult(
            generated_at=ts_now, trade_sample=n,
            overall_win_rate=0.0, overall_expectancy=0.0, overall_pf=0.0,
            recommendations=[], applied=[],
            dry_run=effective_dry_run, enabled=enabled,
        )

    m    = compute_metrics(trades)
    recs = generate_recommendations(trades, config)

    applied: list[AppliedChange] = []
    backup_path = ""

    if apply and not effective_dry_run:
        backup_path = str(backup_config(cfg_path))
        applied     = apply_recommendations(config_path, recs, dry_run=False)
    elif recs:
        # Even in dry-run: simulate what would have been applied
        applied = apply_recommendations(config_path, recs, dry_run=True)

    result = TuneResult(
        generated_at     = ts_now,
        trade_sample     = n,
        overall_win_rate = m.get("win_rate", 0.0),
        overall_expectancy = m.get("expectancy", 0.0),
        overall_pf       = m.get("profit_factor", 0.0),
        recommendations  = recs,
        applied          = applied,
        dry_run          = effective_dry_run,
        enabled          = enabled,
        backup_path      = backup_path,
    )

    _write_audit(result)
    return result


# ── Recommendation generators (private) ──────────────────────────────────────

def _check_score_threshold(
    trades: list[dict], config: dict
) -> list[Recommendation]:
    """
    If low-score bins have poor win rate and negative PnL, suggest raising AI_THRESHOLD.
    """
    by_score        = metrics_by_score_bin(trades)
    current_thr     = int(config.get("AI_THRESHOLD", 65))
    param_meta      = _TUNABLE_PARAMS["AI_THRESHOLD"]

    # Guard parameters (read once, used in the loop and after it)
    _n           = len(trades)
    overall_wr   = sum(1 for t in trades if float(t.get("net_pnl") or 0) >= 0) / _n * 100
    overall_wr   = float(overall_wr)
    min_n        = int(config.get("AUTO_TUNE_MIN_SAMPLES_PER_SEGMENT", 10))
    min_edge_pct = float(config.get("AUTO_TUNE_MIN_EDGE_DELTA", 0.05)) * 100

    # Find bins AT or JUST ABOVE the threshold that are bleeding.
    # These are the lowest-scoring trades being taken — prime candidates for exclusion.
    # A bin is "in scope" if its lower bound is within [current_thr, current_thr+10].
    losing_bins = []
    for label, bm in by_score.items():
        lo, hi = _parse_bin_range(label)
        if lo is None or hi is None:
            continue
        # Only consider bins that start AT the current threshold (currently being traded)
        if lo < current_thr:
            continue
        # Don't flag strong-score bins — only look at the weakest entries
        if lo > current_thr + 10:
            continue
        if bm["trades"] < _MIN_TRADES_MEDIUM:
            continue
        # Flag bin if win rate is below viable threshold AND total PnL is negative.
        # For options buying, WR < 50% with net losses on a score bin warrants review.
        if bm["win_rate"] < 50.0 and bm["total_pnl"] < -100:
            # Materiality guard: bin must be meaningfully worse than overall performance.
            # A 2% WR gap vs overall is noise, not signal.
            bin_wr = float(bm["win_rate"])
            overall_wr = float(overall_wr)
            if abs(bin_wr - overall_wr) < min_edge_pct:
                log.info(
                    "[AUTO-TUNE] Skipped (AI_THRESHOLD bin %s) due to low_materiality "
                    "(WR %.1f%% vs overall %.1f%%, delta %.1f%% < %.1f%%)",
                    label, bin_wr, overall_wr,
                    abs(bin_wr - overall_wr), min_edge_pct,
                )
                log.info(
                    "[AUTO-TUNE] Skipped (AI_THRESHOLD) — samples=%d, min_required=%d",
                    bm["trades"], min_n,
                )
                continue
            losing_bins.append((label, bm, lo, hi))

    if not losing_bins:
        return []

    # New threshold = upper edge of the highest losing bin + 1, capped by max_delta
    worst_upper = max(hi for _, _, _, hi in losing_bins)
    raw_new_thr = worst_upper + 1
    delta       = raw_new_thr - current_thr
    if delta <= 0:
        return []
    delta       = min(delta, param_meta["max_delta"])
    new_thr     = min(current_thr + delta, param_meta["abs_max"])

    total_bad   = sum(bm["trades"] for _, bm, _, _ in losing_bins)
    confidence  = "HIGH" if total_bad >= _MIN_TRADES_HIGH else "MEDIUM"

    # Consistency check: the signal must hold in RECENT trades, not just the full window.
    # A bad streak 45 days ago should not override a clean recent 2 weeks.
    # If the worst bin's recent WR is >= 50%, the problem may have self-corrected —
    # downgrade to MEDIUM so no automatic change fires.
    if confidence == "HIGH":
        worst_tmp   = min(losing_bins, key=lambda x: x[1]["win_rate"])
        w_lo, w_hi  = _parse_bin_range(worst_tmp[0])
        if w_lo is not None and w_hi is not None:
            recent_wr = _recent_bin_wr(trades, w_lo, w_hi)
            if recent_wr is not None and recent_wr >= 50.0:
                log.info(
                    "[AUTO-TUNE] Consistency: bin %s recent WR %.0f%% >= 50%% "
                    "(full-window %.0f%%) — downgrading HIGH -> MEDIUM",
                    worst_tmp[0], recent_wr, worst_tmp[1]["win_rate"],
                )
                confidence = "MEDIUM"

    # Minimum samples guard: total evidence across losing bins is too thin for HIGH confidence.
    if confidence == "HIGH" and total_bad < min_n:
        log.info(
            "[AUTO-TUNE] Downgraded (AI_THRESHOLD) due to low_samples (%d < %d)",
            total_bad, min_n,
        )
        log.info(
            "[AUTO-TUNE] Skipped (AI_THRESHOLD) — samples=%d, min_required=%d",
            total_bad, min_n,
        )
        confidence = "MEDIUM"

    safe_to_apply = (
        confidence == "HIGH"
        and delta <= param_meta["max_delta"]
        and param_meta["abs_min"] <= new_thr <= param_meta["abs_max"]
    )

    worst = min(losing_bins, key=lambda x: x[1]["win_rate"])
    reason = (
        f"Score bin {worst[0]}: {worst[1]['win_rate']:.0f}% WR "
        f"over {worst[1]['trades']} trades (total Rs{worst[1]['total_pnl']:+.0f}). "
        f"Raising threshold {current_thr} -> {new_thr} removes these low-quality entries."
    )

    return [Recommendation(
        type          = "threshold",
        param         = "AI_THRESHOLD",
        current_value = current_thr,
        suggested_value = new_thr,
        reason        = reason,
        evidence      = {b: bm for b, bm, _, _ in losing_bins},
        confidence    = confidence,
        safe_to_apply = safe_to_apply,
    )]


def _check_regime_sizes(
    trades: list[dict], config: dict
) -> list[Recommendation]:
    """
    If a regime has consistently poor win rate and negative PnL, suggest reducing
    the REGIME_SIZE_MAP multiplier.  Never suggests size > current value.
    """
    by_regime       = metrics_by_regime(trades)
    size_map        = dict(config.get("REGIME_SIZE_MAP", {}))
    lim             = _TUNABLE_REGIME_SIZE
    recs: list[Recommendation] = []

    # Guard parameters (computed once, applied per-regime)
    _n           = len(trades)
    overall_wr   = sum(1 for t in trades if float(t.get("net_pnl") or 0) >= 0) / _n * 100 if _n else 0.0
    overall_wr   = float(overall_wr)
    min_n        = int(config.get("AUTO_TUNE_MIN_SAMPLES_PER_SEGMENT", 10))
    min_edge_pct = float(config.get("AUTO_TUNE_MIN_EDGE_DELTA", 0.05)) * 100

    for regime, rm in by_regime.items():
        # Require at least 5 trades for MEDIUM; HIGH still needs _MIN_TRADES_HIGH
        if rm["trades"] < 5:
            continue
        current_size = float(size_map.get(regime, 0.75))

        # Determine severity (adjusted for options: 0% WR is catastrophic even in 5 trades)
        is_bad      = rm["win_rate"] < 40.0 and rm["total_pnl"] < -200
        is_very_bad = rm["win_rate"] < 20.0 and rm["total_pnl"] < -600

        if not is_bad:
            continue

        # Materiality guard: regime must be meaningfully worse than overall performance.
        regime_wr = float(rm["win_rate"])
        overall_wr = float(overall_wr)
        if abs(regime_wr - overall_wr) < min_edge_pct:
            log.info(
                "[AUTO-TUNE] Skipped (REGIME_SIZE_MAP.%s) due to low_materiality "
                "(WR %.1f%% vs overall %.1f%%, delta %.1f%% < %.1f%%)",
                regime, regime_wr, overall_wr,
                abs(regime_wr - overall_wr), min_edge_pct,
            )
            log.info(
                "[AUTO-TUNE] Skipped (REGIME_SIZE_MAP.%s) — samples=%d, min_required=%d",
                regime, rm["trades"], min_n,
            )
            continue

        if is_very_bad:
            # Floor at abs_min regardless of delta constraint
            suggested = lim["abs_min"]
            rec_type  = "regime_avoid"
            prefix    = f"Regime {regime} is strongly negative: {rm['win_rate']:.0f}% WR, " \
                        f"{rm['trades']} trades, Rs{rm['total_pnl']:+.0f}. " \
                        f"Reducing position to minimum floor ({suggested}x)."
        else:
            suggested = round(max(lim["abs_min"], current_size - lim["max_delta"]), 2)
            rec_type  = "regime_size"
            prefix    = f"Regime {regime}: {rm['win_rate']:.0f}% WR, " \
                        f"{rm['trades']} trades, Rs{rm['total_pnl']:+.0f}. " \
                        f"Reducing position size {current_size:.1f}x -> {suggested:.1f}x."

        if suggested >= current_size:
            continue

        confidence  = "HIGH" if rm["trades"] >= _MIN_TRADES_HIGH else "MEDIUM"

        # Consistency check: recent trades in this regime must confirm the signal.
        # If recent performance has recovered, don't fire a HIGH-confidence change.
        if confidence == "HIGH":
            recent_wr = _recent_regime_wr(trades, regime)
            if recent_wr is not None and recent_wr >= 45.0:
                log.info(
                    "[AUTO-TUNE] Consistency: regime %s recent WR %.0f%% >= 45%% "
                    "(full-window %.0f%%) — downgrading HIGH -> MEDIUM",
                    regime, recent_wr, rm["win_rate"],
                )
                confidence = "MEDIUM"

        # Minimum samples guard: regime evidence is too thin for HIGH confidence.
        if confidence == "HIGH" and rm["trades"] < min_n:
            log.info(
                "[AUTO-TUNE] Downgraded (REGIME_SIZE_MAP.%s) due to low_samples (%d < %d)",
                regime, rm["trades"], min_n,
            )
            log.info(
                "[AUTO-TUNE] Skipped (REGIME_SIZE_MAP.%s) — samples=%d, min_required=%d",
                regime, rm["trades"], min_n,
            )
            confidence = "MEDIUM"

        safe        = (
            confidence == "HIGH"
            and suggested >= lim["abs_min"]
            and suggested <= current_size
            and (current_size - suggested) <= lim["max_delta"] + 0.001
        )

        recs.append(Recommendation(
            type          = rec_type,
            param         = f"REGIME_SIZE_MAP.{regime}",
            current_value = current_size,
            suggested_value = suggested,
            reason        = prefix,
            evidence      = rm,
            confidence    = confidence,
            safe_to_apply = safe,
        ))

    return recs


def _check_drawdown(
    trades: list[dict], config: dict
) -> list[Recommendation]:
    """
    Informational warning when max drawdown exceeds 20% of BASE_CAPITAL.
    Never auto-applied — risk parameters are the user's responsibility.
    """
    dd           = compute_drawdown(trades)
    max_dd       = dd.get("max_drawdown", 0.0)
    base_capital = float(config.get("BASE_CAPITAL", 100_000))

    if max_dd <= 0 or base_capital <= 0:
        return []

    dd_pct = max_dd / base_capital * 100
    if dd_pct < 20:
        return []

    reason = (
        f"Max drawdown Rs{max_dd:,.0f} = {dd_pct:.1f}% of capital Rs{base_capital:,.0f}. "
        "Review MAX_DAILY_LOSS, CONSEC_LOSS_LIMIT, and daily target thresholds. "
        "This is an informational flag — no automatic change will be made."
    )
    return [Recommendation(
        type          = "drawdown_warning",
        param         = "CONSEC_LOSS_LIMIT",
        current_value = int(config.get("CONSEC_LOSS_LIMIT", 3)),
        suggested_value = None,
        reason        = reason,
        evidence      = dd,
        confidence    = "MEDIUM",
        safe_to_apply = False,   # risk params are NEVER auto-applied
    )]


def _check_direction_skew(trades: list[dict]) -> list[Recommendation]:
    """
    Informational flag when CALL/PUT win rates diverge by >= 20 pp with >= 15 samples each.
    """
    calls = [t for t in trades if str(t.get("direction", "")).upper() == "CALL"]
    puts  = [t for t in trades if str(t.get("direction", "")).upper() == "PUT"]

    if len(calls) < _MIN_TRADES_MEDIUM or len(puts) < _MIN_TRADES_MEDIUM:
        return []

    call_wr = sum(1 for t in calls if float(t.get("net_pnl") or 0) >= 0) / len(calls) * 100
    put_wr  = sum(1 for t in puts  if float(t.get("net_pnl") or 0) >= 0) / len(puts)  * 100
    diff    = abs(call_wr - put_wr)

    if diff < 20:
        return []

    worse = "CALL" if call_wr < put_wr else "PUT"
    better = "PUT" if worse == "CALL" else "CALL"
    worse_wr  = call_wr if worse == "CALL" else put_wr
    better_wr = put_wr  if worse == "CALL" else call_wr

    reason = (
        f"Direction skew detected: {worse} WR {worse_wr:.0f}% vs "
        f"{better} WR {better_wr:.0f}% (gap {diff:.0f} pp, n={len(calls)}/{len(puts)}). "
        f"Review {worse} entry criteria — RSI healthy zone, breakout confirmation, trend alignment."
    )
    return [Recommendation(
        type          = "direction_skew",
        param         = "AI_THRESHOLD",
        current_value = None,
        suggested_value = None,
        reason        = reason,
        evidence      = {"call_wr": round(call_wr, 1), "put_wr": round(put_wr, 1),
                         "call_n": len(calls), "put_n": len(puts)},
        confidence    = "MEDIUM",
        safe_to_apply = False,
    )]


# ── Stability helpers (private) ──────────────────────────────────────────────

def _last_change_date(param: str) -> datetime | None:
    """
    Scan the audit log for the most recent *real* (non-dry-run) change to param.
    Returns the datetime of that change, or None if the param was never changed.
    """
    if not _AUDIT_LOG.exists():
        return None
    last: datetime | None = None
    try:
        with _AUDIT_LOG.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for change in rec.get("applied", []):
                    if change.get("dry_run"):
                        continue
                    if change.get("param") == param:
                        try:
                            ts = datetime.fromisoformat(change["ts"])
                            if last is None or ts > last:
                                last = ts
                        except (KeyError, ValueError) as e:
                            log.debug("[AUTO_TUNER] non-critical error: %s", e)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        log.debug("[AUTO-TUNE] _last_change_date scan error: %s", exc)
    return last


def _in_cooldown(param: str, cooldown_days: int) -> bool:
    """
    Return True if param was really changed within the last cooldown_days.

    Prevents oscillation: a threshold raised today cannot be lowered for
    cooldown_days days, and vice versa.  Dry-run changes are ignored.
    """
    if cooldown_days <= 0:
        return False
    last = _last_change_date(param)
    if last is None:
        return False
    age_days = (time_provider.now() - last).days
    if age_days < cooldown_days:
        log.info(
            "[AUTO-TUNE] Cooldown: %s changed %dd ago (cooldown=%dd) — skipping",
            param, age_days, cooldown_days,
        )
        return True
    return False


def _recent_bin_wr(trades: list[dict], lo: int, hi: int, n: int = 15) -> float | None:
    """
    Win rate for the most recent n trades whose score falls in [lo, hi].
    Returns None when fewer than 5 recent trades exist in the bin (too thin to judge).
    """
    bin_trades = [t for t in trades if lo <= int(t.get("score") or 0) <= hi]
    recent = bin_trades[-n:]
    if len(recent) < 5:
        return None
    wins = sum(1 for t in recent if float(t.get("net_pnl") or 0) >= 0)
    return wins / len(recent) * 100


def _recent_regime_wr(trades: list[dict], regime: str, n: int = 15) -> float | None:
    """
    Win rate for the most recent n trades in the given regime.
    Returns None when fewer than 5 recent trades exist in the regime.
    """
    regime_trades = [
        t for t in trades
        if str(t.get("regime") or "").upper() == regime.upper()
    ]
    recent = regime_trades[-n:]
    if len(recent) < 5:
        return None
    wins = sum(1 for t in recent if float(t.get("net_pnl") or 0) >= 0)
    return wins / len(recent) * 100


# ── Apply helpers (private) ───────────────────────────────────────────────────

def _compute_safe_change(
    rec: Recommendation, config: dict
) -> tuple[Any, Any]:
    """
    Return (old_value, new_value) after re-validating bounds.
    Returns (None, None) if the change is invalid or already at target.
    """
    if rec.suggested_value is None:
        return None, None

    if rec.param in _BLOCKED_KEYS:
        log.warning("[AUTO-TUNE] Attempt to change blocked key %s — refused", rec.param)
        return None, None

    # Top-level scalar param
    if rec.param in _TUNABLE_PARAMS:
        meta    = _TUNABLE_PARAMS[rec.param]
        current = config.get(rec.param)
        if current is None:
            return None, None
        old = current
        new = rec.suggested_value
        # Re-validate bounds
        new = max(meta["abs_min"], min(meta["abs_max"], new))
        delta = abs(new - old)
        if delta > meta["max_delta"]:
            log.warning(
                "[AUTO-TUNE] Delta %d exceeds max_delta %d for %s — clamping",
                delta, meta["max_delta"], rec.param,
            )
            new = old + meta["max_delta"] if new > old else old - meta["max_delta"]
        if meta["type"] == "int":
            new = int(round(new))
        return old, new

    # REGIME_SIZE_MAP.REGIME_NAME
    if rec.param.startswith("REGIME_SIZE_MAP."):
        regime   = rec.param.split(".", 1)[1]
        size_map = config.get("REGIME_SIZE_MAP", {})
        if regime not in size_map:
            return None, None
        lim     = _TUNABLE_REGIME_SIZE
        old     = float(size_map[regime])
        new     = float(rec.suggested_value)
        new     = max(lim["abs_min"], min(lim["abs_max"], new))
        delta   = abs(new - old)
        if delta > lim["max_delta"] + 0.001:
            new = round(max(old - lim["max_delta"], lim["abs_min"]), 2)
        new = round(new, 2)
        return old, new

    log.warning("[AUTO-TUNE] Unknown param pattern: %s — skipped", rec.param)
    return None, None


def _write_config_change(
    config: dict, param: str, new_value: Any, cfg_path: Path
) -> None:
    """Write a single param change to config file (full atomic rewrite)."""
    if param.startswith("REGIME_SIZE_MAP."):
        regime = param.split(".", 1)[1]
        config.setdefault("REGIME_SIZE_MAP", {})[regime] = new_value
    elif param in config:
        config[param] = new_value
    else:
        log.error("[AUTO-TUNE] Param %s not found in loaded config — aborting write", param)
        return

    tmp = cfg_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=4, ensure_ascii=False), encoding="utf-8")
    tmp.replace(cfg_path)
    log.info("[AUTO-TUNE] Config written: %s", cfg_path)


# ── Audit trail ───────────────────────────────────────────────────────────────

def _write_audit(result: TuneResult) -> None:
    """Append a single JSON line to the auto-tune audit log."""
    try:
        _AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        record = result.to_dict()
        with _AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("[AUTO-TUNE] Audit log write failed: %s", exc)


# ── Report printer ────────────────────────────────────────────────────────────

def print_tune_report(result: TuneResult) -> None:
    """Human-readable auto-tune report printed to stdout."""
    W = 62
    print(f"\n{'=' * W}")
    print(f"  AUTO-TUNE REPORT  |  {result.generated_at}")
    mode_str = "DRY-RUN" if result.dry_run else ("LIVE" if result.enabled else "DISABLED")
    print(f"  Mode: {mode_str}  |  Trades analysed: {result.trade_sample}")
    print(f"{'=' * W}")

    if result.trade_sample == 0:
        print("  No trades available — nothing to tune.")
        print(f"{'=' * W}\n")
        return

    print(f"\n  Overall: WR {result.overall_win_rate:.1f}%  "
          f"Exp Rs{result.overall_expectancy:+.0f}  PF {result.overall_pf}")

    if not result.recommendations:
        print("\n  No recommendations — system is within expected parameters.")
        print(f"{'=' * W}\n")
        return

    print(f"\n  RECOMMENDATIONS ({len(result.recommendations)})")
    print(f"  {'-' * 58}")

    for i, rec in enumerate(result.recommendations, 1):
        icon = {"HIGH": "[H]", "MEDIUM": "[M]", "LOW": "[L]"}.get(rec.confidence, "[?]")
        apply_tag = "-> APPLY" if rec.safe_to_apply else "-> REVIEW"
        print(f"\n  {i}. {icon} {rec.confidence}  {rec.type.upper()}  {apply_tag}")
        print(f"     Param   : {rec.param}")
        if rec.current_value is not None:
            print(f"     Current : {rec.current_value}")
        if rec.suggested_value is not None:
            print(f"     Suggest : {rec.suggested_value}")
        # Word-wrap reason at 70 chars
        words = rec.reason.split()
        line: list[str] = []; lines: list[str] = []
        for w in words:
            if sum(len(x) + 1 for x in line) + len(w) > 68:
                lines.append(" ".join(line))
                line = [w]
            else:
                line.append(w)
        if line:
            lines.append(" ".join(line))
        for ln in lines:
            print(f"     {ln}")

    if result.applied:
        print(f"\n  {'CHANGES APPLIED' if not result.dry_run else 'WOULD APPLY (dry-run)'}:")
        print(f"  {'-' * 40}")
        for c in result.applied:
            tag = "[DRY-RUN]" if c.dry_run else "[APPLIED]"
            print(f"  {tag} {c.param}: {c.old_value} -> {c.new_value}")

    if result.backup_path:
        print(f"\n  Backup : {result.backup_path}")

    print(f"\n  Audit  : {_AUDIT_LOG}")
    print(f"{'=' * W}\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_bin_range(label: str) -> tuple[int | None, int | None]:
    """Parse score bin label ('65-69', '90+', 'below_60') -> (lo, hi inclusive)."""
    label = label.strip()
    if label.startswith("below_"):
        try:
            hi = int(label.split("_")[1]) - 1
            return 0, hi
        except (IndexError, ValueError):
            return None, None
    if label.endswith("+"):
        try:
            lo = int(label[:-1])
            return lo, 100
        except ValueError:
            return None, None
    if "-" in label:
        parts = label.split("-")
        try:
            return int(parts[0]), int(parts[1])
        except (IndexError, ValueError):
            return None, None
    return None, None


def _load_config_file(path: Path) -> dict:
    try:
        data: dict = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError) as exc:
        log.error("[AUTO-TUNE] Failed to load config %s: %s", path, exc)
        return {}


# ── EOD hook (called from index_trader.py send_eod_report) ───────────────────

def eod_auto_tune_hook(
    db_path: str = _DEFAULT_DB,
    config_path: str = _DEFAULT_CONFIG,
) -> str:
    """
    Lightweight wrapper for the EOD report hook.

    Reads AUTO_TUNE_ENABLED and AUTO_TUNE_DRY_RUN from config.
    Returns a short summary string suitable for appending to Telegram EOD report.
    Errors are swallowed — this must never crash the main EOD flow.
    """
    try:
        config = _load_config_file(Path(config_path))
        if not config.get("AUTO_TUNE_ENABLED", False):
            return ""

        dry_run = bool(config.get("AUTO_TUNE_DRY_RUN", True))
        result  = run_auto_tune(
            db_path=db_path,
            config_path=config_path,
            dry_run=dry_run,
            days=50,
            apply=(not dry_run),
        )

        if not result.recommendations:
            return ""

        lines = ["\nAuto-Tune:"]
        for rec in result.recommendations[:3]:          # max 3 in Telegram
            icon = "H" if rec.confidence == "HIGH" else "M"
            val  = f" -> {rec.suggested_value}" if rec.suggested_value is not None else ""
            lines.append(f"  [{icon}] {rec.param}{val}: {rec.reason[:60]}…")

        if result.applied and not dry_run:
            lines.append(f"  Applied {len(result.applied)} change(s). See {_AUDIT_LOG}")
        elif result.applied:
            lines.append(f"  (dry-run: {len(result.applied)} change(s) would apply)")

        return "\n".join(lines)

    except (OSError, ValueError, TypeError) as exc:
        log.warning("[AUTO-TUNE] EOD hook error: %s", exc)
        return ""


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cli() -> None:
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, AttributeError) as _ex:
            log.debug("[AUTO_TUNER] non-critical oserror; non-critical attributeerror")

    parser = argparse.ArgumentParser(
        description="OPB Auto-Tuner - safe parameter suggestion engine"
    )
    parser.add_argument("--db",     default=_DEFAULT_DB,     help="Path to trades.db")
    parser.add_argument("--config", default=_DEFAULT_CONFIG, help="Path to config.json")
    parser.add_argument("--days",   type=int, default=50,    help="Analysis window (days)")
    parser.add_argument("--apply",  action="store_true",
                        help="Apply HIGH-confidence changes (requires AUTO_TUNE_ENABLED=true in config)")
    parser.add_argument("--json",   action="store_true",
                        help="Print machine-readable JSON instead of formatted report")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    result = run_auto_tune(
        db_path     = args.db,
        config_path = args.config,
        dry_run     = not args.apply,
        days        = args.days,
        apply       = args.apply,
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print_tune_report(result)


if __name__ == "__main__":
    _cli()
