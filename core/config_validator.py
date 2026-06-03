"""
Config Validator -- startup schema validation and consistency checks.

Public API:
  append_tier_engine_errors(errors, warnings, cfg)  -- matches codebase append_* pattern,
      adds only the tier/execution-intelligence checks that no other validator covers.

  validate_config(cfg) -> (errors, warnings)  -- standalone full validation for scripts.
  log_resolved_config(cfg, logger)             -- emit resolved critical values to log.
  generate_config_checksum(cfg) -> str         -- 16-char SHA-256 of critical keys.
  validate_and_log(cfg, logger, abort_on_error) -- one-shot for scripts / run_analysis.
"""

import hashlib
import json
import logging
from collections.abc import MutableMapping
from typing import Any

log = logging.getLogger("config_validator")

# -- Required top-level keys -------------------------------------------------
_REQUIRED_KEYS: list[str] = [
    "EXECUTION_MODE",
    "BASE_CAPITAL",
    "MAX_DAILY_LOSS",
    "MAX_DRAWDOWN",
    "RISK_MODE",
    "SL_PCT",
    "TARGET_PCT",
    "AI_THRESHOLD",
    "TIER_STRONG_MIN",
    "TIER_MODERATE_MIN",
    "TIER_WEAK_MIN",
    "QUALITY_MIN_SCORE",
    "VIX_HALT_THRESHOLD",
    "VIX_BLOCK_THRESHOLD",
    "MAX_OPEN",
    "MAX_TRADES_DAY",
]

# -- Keys whose values must be in (0, 1] ------------------------------------
_FRACTION_KEYS: list[str] = [
    "MAX_DRAWDOWN", "RISK_PER_TRADE", "SLIPPAGE",
]

# -- Keys that must be positive ----------------------------------------------
_POSITIVE_KEYS: list[str] = [
    "BASE_CAPITAL", "SCAN_INTERVAL", "COOLDOWN",
    "TIER_STRONG_MIN", "TIER_MODERATE_MIN", "TIER_WEAK_MIN",
    "QUALITY_MIN_SCORE", "VIX_HALT_THRESHOLD", "VIX_BLOCK_THRESHOLD",
    "MIN_NET_RR",
]

_VALID_EXECUTION_MODES = {"MANUAL", "PAPER", "AUTO", "SIGNAL_ONLY"}
_VALID_RISK_MODES = {"FIXED", "PERCENT"}


def append_tier_engine_errors(
    errors: list[str],
    warnings: list[str],
    cfg: MutableMapping[str, Any],
) -> None:
    """
    Append tier-engine and execution-intelligence consistency issues to existing
    errors/warnings lists.  Follows the ``append_*(errors, cfg)`` pattern used
    throughout the codebase.

    Checks covered here (not duplicated by any other validator):
      - Tier boundary ordering: WEAK < MODERATE < STRONG
      - AI_THRESHOLD vs TIER_WEAK_MIN / TIER_MODERATE_MIN gap
      - TG_ALERT_MIN_SCORE vs AI_THRESHOLD alignment
      - QUALITY_MIN_SCORE within [TIER_WEAK_MIN, TIER_MODERATE_MIN]
      - EXECUTION_POLICY.quality_min_score vs top-level QUALITY_MIN_SCORE
      - EXECUTION_POLICY.trade_weak vs TIER_TRADE_WEAK
      - Legacy STRONG_THRESHOLD / MODERATE_THRESHOLD vs tier engine constants
    """
    t_strong   = int(cfg.get("TIER_STRONG_MIN",   80))
    t_moderate = int(cfg.get("TIER_MODERATE_MIN", 70))
    t_weak     = int(cfg.get("TIER_WEAK_MIN",     60))

    # -- Tier boundary ordering --------------------------------------------
    if not (t_weak < t_moderate < t_strong):
        errors.append(
            f"Tier boundaries out of order: "
            f"TIER_WEAK_MIN={t_weak}, TIER_MODERATE_MIN={t_moderate}, TIER_STRONG_MIN={t_strong} "
            f"-- required WEAK < MODERATE < STRONG"
        )
    if t_weak < 0 or t_strong > 100:
        errors.append(f"Tier boundaries must be in [0,100]; got {t_weak}-{t_strong}")

    # -- AI_THRESHOLD pipeline gap -- ERROR: causes dead zones in signal flow -
    ai_thr = int(cfg.get("AI_THRESHOLD", 60))
    if ai_thr > t_weak:
        # Any gap between TIER_WEAK_MIN and AI_THRESHOLD is a dead zone:
        # signals are scored by the engine but silently dropped before routing.
        errors.append(
            f"AI_THRESHOLD={ai_thr} > TIER_WEAK_MIN={t_weak}: "
            f"dead zone -- signals [{t_weak},{ai_thr - 1}] are scored but never routed. "
            f"Set AI_THRESHOLD={t_weak} (all WEAK) or AI_THRESHOLD={t_moderate} (MODERATE+ only)."
        )
    if ai_thr > t_moderate:
        # Separate, more severe case: entire MODERATE tier is unreachable.
        errors.append(
            f"AI_THRESHOLD={ai_thr} >= TIER_MODERATE_MIN={t_moderate}: "
            f"MODERATE tier is permanently unreachable -- only STRONG signals evaluated."
        )

    # -- TG_ALERT_MIN_SCORE -- ERROR: silent suppression of evaluated signals -
    tg_min = int(cfg.get("TG_ALERT_MIN_SCORE", ai_thr))
    if tg_min > ai_thr:
        # Signals are evaluated, pass all filters, then silently dropped in Telegram.
        errors.append(
            f"TG_ALERT_MIN_SCORE={tg_min} > AI_THRESHOLD={ai_thr}: "
            f"signals [{ai_thr},{tg_min - 1}] are processed but silently discarded before Telegram. "
            f"Set TG_ALERT_MIN_SCORE={ai_thr} to eliminate the silent dead zone."
        )
    elif tg_min < ai_thr:
        # Signals below pipeline entry are already blocked -- TG filter is redundant but harmless.
        warnings.append(
            f"TG_ALERT_MIN_SCORE={tg_min} < AI_THRESHOLD={ai_thr}: "
            f"TG filter is below pipeline gate -- effectively dead. "
            f"Set TG_ALERT_MIN_SCORE={ai_thr} to align with pipeline."
        )

    # -- QUALITY_MIN_SCORE range -------------------------------------------
    qms = int(cfg.get("QUALITY_MIN_SCORE", 68))
    if not (t_weak <= qms <= t_moderate):
        warnings.append(
            f"QUALITY_MIN_SCORE={qms} outside [TIER_WEAK_MIN={t_weak}, "
            f"TIER_MODERATE_MIN={t_moderate}]: quality filter spans tier boundaries."
        )

    ep = cfg.get("EXECUTION_POLICY", {}) or {}
    ep_qms = int(ep.get("quality_min_score", qms))
    if ep_qms != qms:
        warnings.append(
            f"QUALITY_MIN_SCORE={qms} != EXECUTION_POLICY.quality_min_score={ep_qms}: "
            f"top-level value takes precedence at runtime -- sync them."
        )

    # -- trade_weak coherence ----------------------------------------------
    ep_tw   = bool(ep.get("trade_weak", False))
    tier_tw = bool(cfg.get("TIER_TRADE_WEAK", False))
    if ep_tw != tier_tw:
        warnings.append(
            f"EXECUTION_POLICY.trade_weak={ep_tw} != TIER_TRADE_WEAK={tier_tw}: "
            f"EXECUTION_POLICY value is authoritative at runtime; "
            f"update TIER_TRADE_WEAK to match."
        )

    # -- Legacy GUI threshold alignment ------------------------------------
    legacy_strong   = int(cfg.get("STRONG_THRESHOLD",   t_strong))
    legacy_moderate = int(cfg.get("MODERATE_THRESHOLD", t_moderate))
    if legacy_strong != t_strong:
        warnings.append(
            f"STRONG_THRESHOLD={legacy_strong} != TIER_STRONG_MIN={t_strong}: "
            f"tier_engine uses TIER_STRONG_MIN; STRONG_THRESHOLD is GUI-only -- consider aligning."
        )
    if legacy_moderate != t_moderate:
        warnings.append(
            f"MODERATE_THRESHOLD={legacy_moderate} != TIER_MODERATE_MIN={t_moderate}: "
            f"tier_engine uses TIER_MODERATE_MIN; MODERATE_THRESHOLD is GUI-only -- consider aligning."
        )


def validate_config(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Validate config for type/range/consistency errors.

    Returns:
        (errors, warnings)
        errors   -- must-fix; startup should abort
        warnings -- degraded behaviour; startup can continue
    """
    errors: list[str] = []
    warnings: list[str] = []

    def err(msg: str):
        errors.append(msg)

    def warn(msg: str):
        warnings.append(msg)

    # -- 1. Required keys ---------------------------------------------------
    for k in _REQUIRED_KEYS:
        if k not in cfg:
            err(f"Missing required key: {k}")

    if errors:
        return errors, warnings   # can't do consistency checks without basics

    # -- 2. Execution mode -------------------------------------------------
    exec_mode = str(cfg.get("EXECUTION_MODE", "MANUAL")).upper()
    if exec_mode not in _VALID_EXECUTION_MODES:
        err(f"EXECUTION_MODE '{exec_mode}' not in {_VALID_EXECUTION_MODES}")

    if exec_mode == "AUTO" and not cfg.get("BROKER_API_ENABLED", False):
        err("EXECUTION_MODE=AUTO but BROKER_API_ENABLED=false -- orders cannot be placed")

    # BROKER_DRIVER must be a live-capable driver when auto-trading is requested
    _live_drivers = {"KITE", "ANGEL", "CUSTOM"}
    _driver = str(cfg.get("BROKER_DRIVER", cfg.get("BROKER_BACKEND", "GENERIC"))).upper()
    if exec_mode == "AUTO" and cfg.get("BROKER_API_ENABLED", False):
        if _driver not in _live_drivers:
            err(
                f"EXECUTION_MODE=AUTO + BROKER_API_ENABLED=true but BROKER_DRIVER={_driver!r} "
                f"is not a live-capable driver -- set BROKER_DRIVER to one of "
                f"{sorted(_live_drivers)}. System would silently fall back to paper-trading."
            )

    # MANUAL_SIGNALS_ONLY=true overrides AUTO -> orders are permanently blocked
    if exec_mode == "AUTO" and cfg.get("MANUAL_SIGNALS_ONLY", False):
        warn(
            "EXECUTION_MODE=AUTO but MANUAL_SIGNALS_ONLY=true -- auto-execution is "
            "permanently blocked at runtime. Set MANUAL_SIGNALS_ONLY=false to enable live orders."
        )

    # Duplicate credential keys: BROKER_CONFIG wins over legacy KITE_*/ANGEL_* silently
    _bc = cfg.get("BROKER_CONFIG") or {}
    if isinstance(_bc, dict) and _bc.get("api_key"):
        if _driver == "KITE":
            _legacy = [k for k in ("KITE_API_KEY", "KITE_ACCESS_TOKEN", "KITE_USER_ID") if cfg.get(k)]
            if _legacy:
                warn(
                    f"Both BROKER_CONFIG.api_key and legacy top-level keys {_legacy} are set. "
                    f"BROKER_CONFIG takes precedence -- the legacy keys are ignored. "
                    f"Remove the legacy KITE_* keys to avoid confusion."
                )
        elif _driver == "ANGEL":
            _legacy = [k for k in ("ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD") if cfg.get(k)]
            if _legacy:
                warn(
                    f"Both BROKER_CONFIG.api_key and legacy top-level keys {_legacy} are set. "
                    f"BROKER_CONFIG takes precedence -- the legacy keys are ignored. "
                    f"Remove the legacy ANGEL_* keys to avoid confusion."
                )

    # -- 3. Risk mode ------------------------------------------------------
    risk_mode = str(cfg.get("RISK_MODE", "")).upper()
    if risk_mode not in _VALID_RISK_MODES:
        err(f"RISK_MODE '{risk_mode}' not in {_VALID_RISK_MODES}")

    if risk_mode == "FIXED" and cfg.get("RISK_FIXED_AMOUNT", 0) <= 0:
        warn("RISK_MODE=FIXED but RISK_FIXED_AMOUNT <= 0; defaulting to zero risk per trade")

    # -- 4. Tier boundary ordering -----------------------------------------
    t_strong   = int(cfg.get("TIER_STRONG_MIN",   80))
    t_moderate = int(cfg.get("TIER_MODERATE_MIN", 70))
    t_weak     = int(cfg.get("TIER_WEAK_MIN",     60))

    if not (t_weak < t_moderate < t_strong):
        err(
            f"Tier boundaries out of order: "
            f"TIER_WEAK_MIN={t_weak}, TIER_MODERATE_MIN={t_moderate}, TIER_STRONG_MIN={t_strong} "
            f"-- required: WEAK < MODERATE < STRONG"
        )
    if t_weak < 0 or t_strong > 100:
        err(f"Tier boundaries must be in [0,100]; got {t_weak}-{t_strong}")

    # -- 5. AI_THRESHOLD -- error if it creates a dead zone ----------------
    ai_thr = int(cfg.get("AI_THRESHOLD", 60))
    if ai_thr > t_weak:
        err(
            f"AI_THRESHOLD={ai_thr} > TIER_WEAK_MIN={t_weak}: "
            f"dead zone -- signals [{t_weak},{ai_thr-1}] are scored but never routed. "
            f"Set AI_THRESHOLD={t_weak} (all WEAK) or AI_THRESHOLD={t_moderate} (MODERATE+ only)."
        )
    if ai_thr > t_moderate:
        err(
            f"AI_THRESHOLD={ai_thr} >= TIER_MODERATE_MIN={t_moderate}: "
            f"MODERATE tier permanently unreachable -- only STRONG signals evaluated."
        )

    # -- 6. TG_ALERT_MIN_SCORE -- error if it silently drops evaluated signals
    tg_min = int(cfg.get("TG_ALERT_MIN_SCORE", ai_thr))
    if tg_min > ai_thr:
        err(
            f"TG_ALERT_MIN_SCORE={tg_min} > AI_THRESHOLD={ai_thr}: "
            f"signals [{ai_thr},{tg_min-1}] are processed but silently discarded before Telegram. "
            f"Set TG_ALERT_MIN_SCORE={ai_thr}."
        )
    elif tg_min < ai_thr:
        warn(
            f"TG_ALERT_MIN_SCORE={tg_min} < AI_THRESHOLD={ai_thr}: "
            f"TG filter is below pipeline gate -- effectively redundant. Align to {ai_thr}."
        )

    # -- 7. QUALITY_MIN_SCORE range ----------------------------------------
    qms = int(cfg.get("QUALITY_MIN_SCORE", 68))
    if not (t_weak <= qms <= t_moderate):
        warn(
            f"QUALITY_MIN_SCORE={qms} is outside [TIER_WEAK_MIN={t_weak}, "
            f"TIER_MODERATE_MIN={t_moderate}]: quality filter spans tier boundaries."
        )

    # EXECUTION_POLICY.quality_min_score must match top-level
    ep = cfg.get("EXECUTION_POLICY", {})
    ep_qms = int(ep.get("quality_min_score", qms))
    if ep_qms != qms:
        warn(
            f"QUALITY_MIN_SCORE={qms} != EXECUTION_POLICY.quality_min_score={ep_qms}: "
            f"top-level value takes precedence; update EXECUTION_POLICY.quality_min_score to match."
        )

    # EXECUTION_POLICY.trade_weak vs TIER_TRADE_WEAK
    ep_tw = bool(ep.get("trade_weak", False))
    tier_tw = bool(cfg.get("TIER_TRADE_WEAK", False))
    if ep_tw != tier_tw:
        warn(
            f"EXECUTION_POLICY.trade_weak={ep_tw} != TIER_TRADE_WEAK={tier_tw}: "
            f"EXECUTION_POLICY value is used at runtime; sync TIER_TRADE_WEAK for clarity."
        )

    # -- 8. Legacy STRONG_THRESHOLD vs tier engine -------------------------
    legacy_strong = int(cfg.get("STRONG_THRESHOLD", t_strong))
    if legacy_strong != t_strong:
        warn(
            f"STRONG_THRESHOLD={legacy_strong} != TIER_STRONG_MIN={t_strong}: "
            f"tier_engine.py uses TIER_STRONG_MIN; STRONG_THRESHOLD is GUI-only -- "
            f"consider aligning them."
        )

    legacy_moderate = int(cfg.get("MODERATE_THRESHOLD", t_moderate))
    if legacy_moderate != t_moderate:
        warn(
            f"MODERATE_THRESHOLD={legacy_moderate} != TIER_MODERATE_MIN={t_moderate}: "
            f"tier_engine.py uses TIER_MODERATE_MIN; MODERATE_THRESHOLD is GUI-only -- "
            f"consider aligning them."
        )

    # -- 9. Capital / risk limits ------------------------------------------
    capital = float(cfg.get("BASE_CAPITAL", 0))
    if capital <= 0:
        err(f"BASE_CAPITAL={capital} must be > 0")

    max_loss = float(cfg.get("MAX_DAILY_LOSS", 0))
    if max_loss >= 0:
        err(f"MAX_DAILY_LOSS={max_loss} must be negative (e.g. -400)")

    max_dd = float(cfg.get("MAX_DRAWDOWN", 0))
    if not (0 < max_dd <= 1.0):
        err(f"MAX_DRAWDOWN={max_dd} must be in (0, 1]")

    daily_target = float(cfg.get("DAILY_TARGET", 0))
    if daily_target > 0 and abs(max_loss) > daily_target * 3:
        warn(
            f"MAX_DAILY_LOSS={max_loss} is > 3x DAILY_TARGET={daily_target}: "
            f"risk/reward ratio looks unusually wide."
        )

    # -- 10. SL/Target sanity ----------------------------------------------
    sl_pct = float(cfg.get("SL_PCT", 0))
    tp_pct = float(cfg.get("TARGET_PCT", 0))
    if sl_pct >= 1.0:
        err(f"SL_PCT={sl_pct} should be < 1.0 (e.g. 0.92 for 8% stop)")
    if tp_pct <= 1.0:
        err(f"TARGET_PCT={tp_pct} should be > 1.0 (e.g. 1.3 for 30% target)")
    if sl_pct > 0 and tp_pct > 0:
        rr = (tp_pct - 1.0) / (1.0 - sl_pct)
        min_rr = float(cfg.get("MIN_NET_RR", 1.5))
        if rr < min_rr:
            warn(
                f"Implied RR from SL_PCT/TARGET_PCT = {rr:.2f} < MIN_NET_RR={min_rr}: "
                f"configured targets don't satisfy minimum RR."
            )

    # -- 11. VIX thresholds ------------------------------------------------
    vix_halt  = float(cfg.get("VIX_HALT_THRESHOLD",  30))
    vix_block = float(cfg.get("VIX_BLOCK_THRESHOLD", 40))
    if vix_halt >= vix_block:
        err(
            f"VIX_HALT_THRESHOLD={vix_halt} >= VIX_BLOCK_THRESHOLD={vix_block}: "
            f"BLOCK must be strictly greater than HALT."
        )
    vix_high = float(cfg.get("VIX_SIZE_HIGH_THRESHOLD", 35))
    vix_med  = float(cfg.get("VIX_SIZE_MED_THRESHOLD",  25))
    if vix_med >= vix_high:
        warn(
            f"VIX_SIZE_MED_THRESHOLD={vix_med} >= VIX_SIZE_HIGH_THRESHOLD={vix_high}: "
            f"medium and high VIX size bands are inverted."
        )

    # -- 12. Fraction-range keys -------------------------------------------
    for k in _FRACTION_KEYS:
        v = cfg.get(k)
        if v is not None and not (0 < float(v) <= 1.0):
            warn(f"{k}={v} expected in (0, 1]; check units.")

    # -- 13. Positive-value keys -------------------------------------------
    for k in _POSITIVE_KEYS:
        v = cfg.get(k)
        if v is not None and float(v) <= 0:
            err(f"{k}={v} must be > 0")

    # -- 14. MAX_LOT_CAPITAL_PCT -------------------------------------------
    mlcp = float(cfg.get("MAX_LOT_CAPITAL_PCT", 0.6))
    if not (0 < mlcp <= 1.0):
        warn(f"MAX_LOT_CAPITAL_PCT={mlcp} should be in (0, 1]")

    # -- 15. Concurrent position limits -----------------------------------
    max_open = int(cfg.get("MAX_OPEN", 1))
    max_trades = int(cfg.get("MAX_TRADES_DAY", 2))
    if max_open > max_trades:
        warn(
            f"MAX_OPEN={max_open} > MAX_TRADES_DAY={max_trades}: "
            f"can never fill concurrent positions within daily limit."
        )

    return errors, warnings


def log_resolved_config(cfg: dict[str, Any], logger: logging.Logger = None) -> None:
    """Emit the final resolved values for the operationally critical keys."""
    L = logger or log
    t_strong   = cfg.get("TIER_STRONG_MIN",   80)
    t_moderate = cfg.get("TIER_MODERATE_MIN", 70)
    t_weak     = cfg.get("TIER_WEAK_MIN",     60)
    ep         = cfg.get("EXECUTION_POLICY", {})

    L.info("-- Resolved Config ----------------------------------------")
    L.info("  Execution    : mode=%-8s  capital=%s  max_open=%s  max_trades/day=%s",
           cfg.get("EXECUTION_MODE"), cfg.get("BASE_CAPITAL"),
           cfg.get("MAX_OPEN"), cfg.get("MAX_TRADES_DAY"))
    L.info("  Risk         : mode=%s  per_trade=%s  max_daily_loss=%s  max_drawdown=%s",
           cfg.get("RISK_MODE"), cfg.get("RISK_FIXED_AMOUNT") if cfg.get("RISK_MODE") == "FIXED"
           else cfg.get("RISK_PER_TRADE"),
           cfg.get("MAX_DAILY_LOSS"), cfg.get("MAX_DRAWDOWN"))
    L.info("  Tiers        : STRONG>=%d  MODERATE %d-%d  WEAK %d-%d  IGNORE<%d",
           t_strong, t_moderate, t_strong - 1, t_weak, t_moderate - 1, t_weak)
    L.info("  AI_THRESHOLD : %d  (pipeline entry gate)", cfg.get("AI_THRESHOLD"))
    L.info("  Quality      : min_score=%d  trade_weak=%s",
           cfg.get("QUALITY_MIN_SCORE"), ep.get("trade_weak", cfg.get("TIER_TRADE_WEAK", False)))
    L.info("  SL/TP        : SL_PCT=%s  TARGET_PCT=%s  TRAIL_PCT=%s  MIN_NET_RR=%s",
           cfg.get("SL_PCT"), cfg.get("TARGET_PCT"), cfg.get("TRAIL_PCT"), cfg.get("MIN_NET_RR"))
    L.info("  VIX gates    : halt=%s  block=%s", cfg.get("VIX_HALT_THRESHOLD"), cfg.get("VIX_BLOCK_THRESHOLD"))
    L.info("  Telegram     : quiet=%s  trade_only=%s  alert_min_score=%s",
           cfg.get("TG_QUIET_MODE"), cfg.get("TG_TRADE_ONLY"), cfg.get("TG_ALERT_MIN_SCORE"))
    checksum = generate_config_checksum(cfg)
    L.info("  Config CRC   : %s  (alert if this changes between restarts)", checksum)
    L.info("---------------------------------------------------------")


def generate_config_checksum(cfg: dict[str, Any]) -> str:
    """
    Return a 16-character SHA-256 fingerprint of execution-critical config values.

    Log this at every startup. If it changes between restarts, a config change
    occurred -- emit a warning so the change is auditable.
    """
    critical_keys = [
        "AI_THRESHOLD", "TIER_WEAK_MIN", "TIER_MODERATE_MIN", "TIER_STRONG_MIN",
        "QUALITY_MIN_SCORE", "TG_ALERT_MIN_SCORE",
        "EXECUTION_MODE", "BROKER_API_ENABLED",
        "BASE_CAPITAL", "MAX_DAILY_LOSS", "MAX_DRAWDOWN",
        "RISK_MODE", "RISK_PER_TRADE", "RISK_FIXED_AMOUNT",
        "SL_PCT", "TARGET_PCT", "TRAIL_PCT", "TRAIL_ACTIVATE", "MIN_NET_RR",
        "VIX_HALT_THRESHOLD", "VIX_BLOCK_THRESHOLD",
        "MAX_OPEN", "MAX_TRADES_DAY",
    ]
    snapshot = {k: cfg.get(k) for k in critical_keys}
    canonical = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


# -- v2.46 Sprint 0: Structured block validators ------------------------------

_REQUIRED_INSTRUMENT_KEYS = {
    "enabled", "yf_symbol", "lot_size", "strike_step",
    "expiry_weekday", "scan_priority", "max_lots", "min_premium",
}


def validate_structured_blocks(cfg: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Validate v2.46 structured config blocks (instruments, indicator, market, financial).
    Returns (errors, warnings). Non-blocking -- issues are warnings unless instruments block
    has a hard structural error.
    """
    errors: list[str] = []
    warnings: list[str] = []

    instruments = cfg.get("instruments")
    if instruments and isinstance(instruments, dict):
        for idx, params in instruments.items():
            if not isinstance(params, dict):
                errors.append(f"instruments.{idx} must be a dict")
                continue
            for key in _REQUIRED_INSTRUMENT_KEYS:
                if key not in params:
                    warnings.append(f"instruments.{idx} missing recommended key '{key}'")
            ls = params.get("lot_size")
            if ls is not None and (not isinstance(ls, int) or ls <= 0):
                errors.append(f"instruments.{idx}.lot_size must be a positive integer, got {ls!r}")
            ew = params.get("expiry_weekday")
            if ew is not None and ew not in range(7):
                errors.append(f"instruments.{idx}.expiry_weekday must be 0-6, got {ew!r}")

    fin = cfg.get("financial", {})
    for key in ("india_risk_free_rate", "stt_rate_sell", "exchange_charge_rate", "gst_rate"):
        val = fin.get(key)
        if val is not None and (not isinstance(val, (int, float)) or val < 0):
            warnings.append(f"financial.{key} must be non-negative, got {val!r}")

    import re
    market = cfg.get("market", {})
    _time_pattern = re.compile(r"^\d{2}:\d{2}$")
    for key in ("open_time", "close_time", "eod_exit_time", "expiry_cutoff_time"):
        val = market.get(key)
        if val and not _time_pattern.match(str(val)):
            warnings.append(f"market.{key} should be HH:MM format, got {val!r}")

    return errors, warnings


def get_instrument_param(cfg: dict[str, Any], index_name: str, key: str, fallback=None):
    """Safe accessor: instruments.{index}.{key} with flat-key fallback for backward compat."""
    instr = cfg.get("instruments", {}).get(str(index_name).upper(), {})
    if key in instr:
        return instr[key]
    flat_map = {
        "lot_size": f"LOT_SIZE_{index_name.upper()}",
        "strike_step": f"STRIKE_STEP_{index_name.upper()}",
        "expiry_weekday": f"EXPIRY_WEEKDAY_{index_name.upper()}",
        "yf_symbol": f"YF_SYMBOL_{index_name.upper()}",
        "max_lots": "BASE_LOTS",
        "min_premium": "MIN_OPTION_PREMIUM",
    }
    flat_key = flat_map.get(key)
    if flat_key and flat_key in cfg:
        return cfg[flat_key]
    return fallback


def get_indicator_param(cfg: dict[str, Any], key: str, fallback=None):
    """Safe accessor: indicator.{key} with top-level fallback."""
    return cfg.get("indicator", {}).get(key, cfg.get(key, fallback))


def get_market_param(cfg: dict[str, Any], key: str, fallback=None):
    """Safe accessor: market.{key} with top-level fallback."""
    return cfg.get("market", {}).get(key, cfg.get(key, fallback))


def get_financial_param(cfg: dict[str, Any], key: str, fallback=None):
    """Safe accessor: financial.{key}."""
    return cfg.get("financial", {}).get(key, fallback)


def get_url(cfg: dict[str, Any], key: str, fallback: str = "") -> str:
    """Safe accessor: data_source_urls.{key}."""
    return str(cfg.get("data_source_urls", {}).get(key, fallback))


def validate_and_log(
    cfg: dict[str, Any],
    logger: logging.Logger = None,
    abort_on_error: bool = True,
    run_parity_check: bool = False,
) -> bool:
    """
    One-shot: validate + log resolved config.

    Args:
        cfg:               Loaded config dict
        logger:            Optional logger (defaults to module logger)
        abort_on_error:    Raise SystemExit on errors (default True)
        run_parity_check:  Also run backtest/live parity assertion (default False --
                           set True in run_analysis.py)

    Returns True if no errors, False if errors found (and abort_on_error=False).
    Raises SystemExit if errors found and abort_on_error=True.
    """
    L = logger or log
    errors, warnings = validate_config(cfg)

    for w in warnings:
        L.warning("CONFIG WARN  : %s", w)

    if errors:
        for e in errors:
            L.error("CONFIG ERROR : %s", e)
        if abort_on_error:
            raise SystemExit(
                f"Config validation failed with {len(errors)} error(s). Fix config.json and restart."
            )
        return False

    log_resolved_config(cfg, L)

    if run_parity_check:
        try:
            from core.system_parity import assert_backtest_live_parity
            assert_backtest_live_parity()
            L.info("Backtest/live parity: OK")
        except ImportError:
            L.debug("system_parity module not available -- skipping parity check")
        except AssertionError as e:
            L.error("PARITY FAILURE: %s", e)
            if abort_on_error:
                raise SystemExit(str(e)) from e
            return False

    L.info("Config validation passed (%d warning(s))", len(warnings))
    return True
