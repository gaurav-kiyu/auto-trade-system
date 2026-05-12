"""Cross-bot config checks shared by index and stock entry scripts (append to errors/warnings)."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from .adapters.broker_adapters import broker_connection_secrets
from .hybrid_execution import normalize_execution_mode

# When BROKER_CUSTOM_FACTORY is unset, allowed BROKER_DRIVER values (per app defaults differ only in default_backend).
BROKER_ALLOWED_DRIVERS_INDEX = frozenset({"GENERIC", "KITE", "ANGEL", "CUSTOM"})
BROKER_ALLOWED_DRIVERS_STOCK = frozenset({"GENERIC", "KITE", "ANGEL", "CUSTOM", "PAPER", "SIM"})

_WEEKDAYS = frozenset({"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"})


def _cfg_int(
    cfg: MutableMapping[str, Any],
    key: str,
    default: int,
    lo: int,
    hi: int,
    errors: list[str],
) -> int | None:
    try:
        v = int(cfg.get(key, default))
    except (TypeError, ValueError):
        errors.append(f"{key} must be an integer")
        return None
    if not lo <= v <= hi:
        errors.append(f"{key} must be in [{lo},{hi}]")
        return None
    return v


def append_nse_session_clock_errors(errors: list[str], cfg: MutableMapping[str, Any]) -> None:
    """
    Validate NSE_* wall-clock keys used by :func:`core.datetime_ist.apply_nse_session_from_cfg`.

    Catches impossible operator edits (e.g. session end before start) before runtime surprises.
    """
    osh = _cfg_int(cfg, "NSE_CASH_SESSION_START_HOUR", 9, 0, 23, errors)
    osm = _cfg_int(cfg, "NSE_CASH_SESSION_START_MINUTE", 15, 0, 59, errors)
    ceh = _cfg_int(cfg, "NSE_CASH_SESSION_END_HOUR", 15, 0, 23, errors)
    cem = _cfg_int(cfg, "NSE_CASH_SESSION_END_MINUTE", 20, 0, 59, errors)
    if None in (osh, osm, ceh, cem):
        return
    t_open = osh * 60 + osm
    t_close = ceh * 60 + cem
    if t_open >= t_close:
        errors.append("NSE cash session: NSE_CASH_SESSION_START must be before NSE_CASH_SESSION_END (same day)")

    cth = _cfg_int(cfg, "NSE_CONTINUOUS_TRADE_START_HOUR", 9, 0, 23, errors)
    ctm = _cfg_int(cfg, "NSE_CONTINUOUS_TRADE_START_MINUTE", 20, 0, 59, errors)
    if cth is not None and ctm is not None and t_open < t_close:
        t_cont = cth * 60 + ctm
        if t_cont < t_open:
            errors.append("NSE_CONTINUOUS_TRADE_START must be on or after NSE_CASH_SESSION open")
        if t_cont > t_close:
            errors.append("NSE_CONTINUOUS_TRADE_START must be on or before NSE_CASH_SESSION end")

    sch = _cfg_int(cfg, "NSE_MARKET_STATUS_CLOSED_HOUR", 15, 0, 23, errors)
    scm = _cfg_int(cfg, "NSE_MARKET_STATUS_CLOSED_MINUTE", 30, 0, 59, errors)
    if sch is not None and scm is not None and t_open < t_close:
        t_sched = sch * 60 + scm
        if t_sched < t_close:
            errors.append("NSE_MARKET_STATUS_CLOSED must be at or after NSE_CASH_SESSION end")

    beh = _cfg_int(cfg, "NSE_BLOCK_NEW_ENTRIES_FROM_HOUR", 15, 0, 23, errors)
    bem = _cfg_int(cfg, "NSE_BLOCK_NEW_ENTRIES_FROM_MINUTE", 0, 0, 59, errors)
    if beh is not None and bem is not None and t_open < t_close:
        t_block = beh * 60 + bem
        if t_block < t_open:
            errors.append("NSE_BLOCK_NEW_ENTRIES_FROM must be on or after NSE_CASH_SESSION open")

    eeh = _cfg_int(cfg, "NSE_EARLY_SESSION_END_HOUR", 10, 0, 23, errors)
    eem = _cfg_int(cfg, "NSE_EARLY_SESSION_END_MINUTE", 15, 0, 59, errors)
    if eeh is not None and eem is not None and t_open < t_close:
        t_early = eeh * 60 + eem
        if t_early < t_open:
            errors.append("NSE_EARLY_SESSION_END must be on or after NSE_CASH_SESSION open")

    _cfg_int(cfg, "NSE_POST_OPEN_NO_TRADE_MINUTES", 10, 0, 240, errors)


def append_weekday_bias_errors(errors: list[str], cfg: MutableMapping[str, Any]) -> None:
    _wb = cfg.get("WEEKDAY_BIAS")
    if not isinstance(_wb, dict):
        errors.append("WEEKDAY_BIAS must be a dict (Monday..Friday → float)")
        return
    for k, v in _wb.items():
        if k not in _WEEKDAYS:
            errors.append(f"WEEKDAY_BIAS unknown day: {k}")
            continue
        try:
            fv = float(v)
            if not 0.3 <= fv <= 1.5:
                errors.append(f"WEEKDAY_BIAS[{k}] must be in [0.3,1.5]")
        except (TypeError, ValueError):
            errors.append(f"WEEKDAY_BIAS[{k}] must be float")


def append_vix_modifier_errors(errors: list[str], cfg: MutableMapping[str, Any]) -> None:
    try:
        _vrb = int(cfg.get("VIX_RISING_THRESHOLD_BONUS", 5))
        if not 0 <= _vrb <= 50:
            errors.append("VIX_RISING_THRESHOLD_BONUS in [0,50]")
    except (TypeError, ValueError):
        errors.append("VIX_RISING_THRESHOLD_BONUS must be int")
    try:
        _vfm = float(cfg.get("VIX_FALLING_COOLDOWN_MULT", 0.5))
        if not 0.05 <= _vfm <= 1.0:
            errors.append("VIX_FALLING_COOLDOWN_MULT in [0.05,1.0]")
    except (TypeError, ValueError):
        errors.append("VIX_FALLING_COOLDOWN_MULT must be float")


def append_portfolio_reconcile_errors(errors: list[str], cfg: MutableMapping[str, Any]) -> None:
    try:
        _pmsr = float(cfg.get("PORTFOLIO_MAX_SL_RISK_PCT", 0.75))
        if not 0.05 < _pmsr <= 1.0:
            errors.append("PORTFOLIO_MAX_SL_RISK_PCT in (0.05,1.0]")
    except (TypeError, ValueError):
        errors.append("PORTFOLIO_MAX_SL_RISK_PCT must be float")
    try:
        _ri = int(cfg.get("RECONCILE_INTERVAL", 90))
        if not 30 <= _ri <= 600:
            errors.append("RECONCILE_INTERVAL in [30,600] seconds")
    except (TypeError, ValueError):
        errors.append("RECONCILE_INTERVAL must be int")


def append_common_risk_and_target_errors(
    errors: list[str],
    *,
    risk_mode: str,
    risk_fixed_amount: float,
    brokerage_per_trade: float,
    min_net_rr: float,
    daily_target: float,
    sl_warn_pct: float,
    min_trade_duration_mins: int,
    sl_pct: float,
    target_pct: float,
) -> None:
    if risk_mode not in ("FIXED", "PERCENT"):
        errors.append("RISK_MODE: FIXED or PERCENT")
    if risk_mode == "FIXED" and risk_fixed_amount <= 0:
        errors.append("RISK_FIXED_AMOUNT>0")
    if brokerage_per_trade < 0:
        errors.append("BROKERAGE_PER_TRADE>=0")
    if min_net_rr < 1:
        errors.append("MIN_NET_RR>=1")
    if daily_target <= 0:
        errors.append("DAILY_TARGET>0")
    if not 0 < sl_warn_pct < 1:
        errors.append("SL_WARN_PCT 0<x<1")
    if min_trade_duration_mins <= 0:
        errors.append("MIN_TRADE_DURATION_MINS>0")
    if sl_pct >= 1 or sl_pct <= 0:
        errors.append("SL_PCT 0<x<1")
    if target_pct <= 1:
        errors.append("TARGET_PCT>1")
    if sl_pct > 0 and target_pct > 1 and target_pct <= sl_pct:
        errors.append(f"TARGET_PCT ({target_pct}) must be > SL_PCT ({sl_pct}); ambiguous exit if SL≥Target")
    if min_trade_duration_mins > 0 and min_net_rr >= 1:
        # MIN_TRADE_DURATION_MINS is checked against MAX_POSITION_AGE in append_scan_age_summary_errors
        pass  # cross-check lives in append_scan_age_summary_errors (needs max_position_age)


def append_vix_band_relation_errors(
    errors: list[str],
    *,
    vix_block_threshold: float,
    vix_halt_threshold: float,
    vix_size_med_threshold: float,
    vix_size_high_threshold: float,
) -> None:
    if vix_block_threshold <= vix_halt_threshold:
        errors.append(
            f"VIX_BLOCK_THRESHOLD ({vix_block_threshold}) must be > VIX_HALT ({vix_halt_threshold})"
        )
    if vix_size_med_threshold >= vix_size_high_threshold:
        errors.append(
            f"VIX_SIZE_MED ({vix_size_med_threshold}) must be < VIX_SIZE_HIGH ({vix_size_high_threshold})"
        )


def append_slot_and_trail_errors(
    errors: list[str],
    *,
    max_open: int,
    max_trades_day: int,
    max_drawdown: float,
    trail_activate: float,
    partial_exit_mult: float,
) -> None:
    if max_open < 1:
        errors.append("MAX_OPEN>=1")
    if max_trades_day < 1:
        errors.append("MAX_TRADES_DAY>=1")
    if not 0 < max_drawdown <= 1:
        errors.append("MAX_DRAWDOWN 0<x<=1")
    if trail_activate <= 1:
        errors.append("TRAIL_ACTIVATE>1")
    if partial_exit_mult <= 1:
        errors.append("PARTIAL_EXIT_MULT>1")


def append_scan_age_summary_errors(
    errors: list[str],
    *,
    scan_interval: int,
    cooldown: int,
    signal_max_age: int,
    max_position_age: int,
    summary_interval: int,
    min_trade_duration_mins: int = 0,
) -> None:
    if scan_interval < 5:
        errors.append("SCAN_INTERVAL>=5")
    if cooldown < 0:
        errors.append("COOLDOWN>=0")
    if signal_max_age <= 0:
        errors.append("SIGNAL_MAX_AGE>0")
    if max_position_age <= 0:
        errors.append("MAX_POSITION_AGE>0")
    if summary_interval < 60:
        errors.append("SUMMARY_INTERVAL>=60")
    if min_trade_duration_mins > 0 and max_position_age > 0:
        if min_trade_duration_mins >= max_position_age:
            errors.append(
                f"MIN_TRADE_DURATION_MINS ({min_trade_duration_mins}) must be < "
                f"MAX_POSITION_AGE ({max_position_age}min); zombie exit would fire before min-hold"
            )


def append_scan_cross_warnings(
    warnings: list[str],
    *,
    scan_interval: int,
    signal_max_age: int,
    max_position_age: int,
    summary_interval: int,
) -> None:
    if signal_max_age < scan_interval:
        warnings.append(
            f"SIGNAL_MAX_AGE ({signal_max_age}s) < SCAN_INTERVAL ({scan_interval}s): signals may expire before trade"
        )
    if summary_interval > max_position_age:
        warnings.append(
            f"SUMMARY_INTERVAL ({summary_interval}s) > MAX_POSITION_AGE ({max_position_age}s)"
        )


def append_normalized_execution_mode_errors(errors: list[str], raw_mode: Any) -> None:
    em = normalize_execution_mode(raw_mode)
    if em not in ("PAPER", "MANUAL", "AUTO", "SIGNALS"):
        errors.append("EXECUTION_MODE must be PAPER, MANUAL, AUTO, or SIGNALS")


def effective_broker_driver(cfg: MutableMapping[str, Any], *, default_backend: str = "GENERIC") -> str:
    """Resolve ``BROKER_DRIVER`` with ``BROKER_BACKEND`` fallback (index: GENERIC, stock: typically KITE)."""
    fb = default_backend or "GENERIC"
    return str(cfg.get("BROKER_DRIVER", cfg.get("BROKER_BACKEND", fb)) or fb).strip().upper()


def effective_broker_display_name(cfg: MutableMapping[str, Any], *, default_backend: str = "GENERIC") -> str:
    """Label for logs/UI: ``BROKER_NAME`` if set, else a short title from the resolved driver."""
    name = str(cfg.get("BROKER_NAME", "") or "").strip()
    if name:
        return name
    d = effective_broker_driver(cfg, default_backend=default_backend)
    return "Broker" if d == "GENERIC" else d.title()


def append_broker_api_config_errors(
    errors: list[str],
    cfg: MutableMapping[str, Any],
    *,
    broker_api_enabled: bool,
    default_backend: str,
    allowed_drivers_without_factory: frozenset[str],
) -> dict[str, Any]:
    """Validate broker driver / custom factory / merged api_key. Returns driver, factory flag, merged secrets."""
    drv = effective_broker_driver(cfg, default_backend=default_backend)
    bcf = str(cfg.get("BROKER_CUSTOM_FACTORY") or "").strip()
    live = broker_connection_secrets(cfg, drv)
    if not broker_api_enabled or bcf:
        return {"driver": drv, "custom_factory": bcf, "live_secrets": live}
    if drv == "CUSTOM":
        errors.append("BROKER_DRIVER=CUSTOM requires BROKER_CUSTOM_FACTORY (module:function)")
    if drv in ("KITE", "ANGEL") and not str(live.get("api_key") or "").strip():
        errors.append(
            "api_key empty for selected broker (set BROKER_CONFIG or KITE_API_KEY / ANGEL_API_KEY, or BROKER_CUSTOM_FACTORY)"
        )
    if drv not in allowed_drivers_without_factory:
        opts = ", ".join(sorted(allowed_drivers_without_factory))
        errors.append(f"BROKER_DRIVER must be one of: {opts} — or set BROKER_CUSTOM_FACTORY to module:function")
    return {"driver": drv, "custom_factory": bcf, "live_secrets": live}


def append_execution_hybrid_warnings(
    warnings: list[str],
    cfg: MutableMapping[str, Any],
    *,
    broker_api_enabled: bool,
) -> None:
    """Shared MANUAL_SIGNALS_ONLY + EXECUTION_MODE hints (index and stock)."""
    if bool(cfg.get("MANUAL_SIGNALS_ONLY", False)):
        warnings.append(
            "MANUAL_SIGNALS_ONLY: signals/alerts only — bot does not auto-place or track positions until you change mode."
        )
    if bool(cfg.get("MANUAL_SIGNALS_ONLY", False)) and broker_api_enabled:
        warnings.append(
            "MANUAL_SIGNALS_ONLY with BROKER_API enabled: live adapter is bypassed for auto-entries until you change mode."
        )
    em = normalize_execution_mode(cfg.get("EXECUTION_MODE", "MANUAL"))
    if em == "AUTO":
        warnings.append("EXECUTION_MODE=AUTO: broker orders may be placed automatically when all gates pass")
    elif em == "MANUAL":
        warnings.append("EXECUTION_MODE=MANUAL: live signals only — you place orders yourself")
    elif em == "SIGNALS":
        warnings.append("EXECUTION_MODE=SIGNALS: alert-oriented path — confirm behavior in SETUP_AND_TRADING_GUIDE.md.")
