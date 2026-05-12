"""
Greeks-Aware Strike Selector (Phase 4).

Selects the optimal option strike based on signal tier, VIX, DTE and
config-driven mode. Works offline — no broker greeks feed required.
Uses the same delta approximations as option_premium_model.py.

Modes
-----
  ATM   (default) : always return ATM — zero change vs current behaviour
  OTM             : tier-driven OTM step offset (STRONG=1 step, rest=0)
  DELTA           : select strike whose approximated delta is closest to
                    strike_target_delta (atm_delta + delta_per_step model)

Strike offset direction
-----------------------
  CALL : higher strike is OTM  →  selected = ATM + N × step
  PUT  : lower strike is OTM   →  selected = ATM - N × step

Config keys (all optional — safe defaults built in)
---------------------------------------------------
  strike_selection_mode      : str   "ATM"|"OTM"|"DELTA"  default "ATM"
  otm_step_offset            : int   default 0   (global fallback OTM steps)
  otm_step_offset_strong     : int   default 1   (1 step OTM for STRONG tier)
  otm_step_offset_moderate   : int   default 0
  otm_step_offset_weak       : int   default 0
  strike_target_delta        : float default 0.40  (DELTA mode target)
  delta_per_step             : float default 0.08  (delta change per OTM step)
  max_otm_steps              : int   default 3    (safety cap on OTM depth)
  min_dte_for_entry          : int   default 1    (block entry when DTE < this)
  theta_bleed_warn_dte       : int   default 2    (warn when DTE <= this)
  vega_cap_vix_threshold     : float default 30.0 (reduce OTM by 1 when VIX > this)
"""
from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

_DEF_MODE         = "ATM"
_DEF_OTM_GLOBAL   = 0
_DEF_OTM_STRONG   = 1
_DEF_OTM_MODERATE = 0
_DEF_OTM_WEAK     = 0
_DEF_TARGET_DELTA = 0.40
_DEF_DELTA_STEP   = 0.08
_DEF_MAX_OTM      = 3
_DEF_MIN_DTE      = 1
_DEF_WARN_DTE     = 2
_DEF_VEGA_VIX     = 30.0


# ── Internal helpers ──────────────────────────────────────────────────────────

def _cfg_int(cfg: dict[str, Any], key: str, default: int) -> int:
    try:
        return max(0, int(cfg.get(key, default)))
    except (TypeError, ValueError):
        return default


def _cfg_float(cfg: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def _otm_steps_for_tier(tier: str, cfg: dict[str, Any]) -> int:
    """Return OTM step count for the given signal tier (from config or defaults)."""
    t = str(tier).upper()
    if t == "STRONG":
        return _cfg_int(cfg, "otm_step_offset_strong",   _DEF_OTM_STRONG)
    if t == "MODERATE":
        return _cfg_int(cfg, "otm_step_offset_moderate", _DEF_OTM_MODERATE)
    if t == "WEAK":
        return _cfg_int(cfg, "otm_step_offset_weak",     _DEF_OTM_WEAK)
    return _cfg_int(cfg, "otm_step_offset", _DEF_OTM_GLOBAL)


def _otm_steps_for_delta(
    atm_d: float,
    target_delta: float,
    delta_per_step: float,
    max_steps: int,
) -> int:
    """
    Find the number of OTM steps to reach closest to target_delta.

    Model: delta(n) = atm_delta - n × delta_per_step (clamped to 0).
    Returns int in [0, max_steps].
    """
    if delta_per_step <= 0 or atm_d <= target_delta:
        return 0
    n = round((atm_d - target_delta) / delta_per_step)
    return max(0, min(int(n), max_steps))


def _apply_vega_cap(steps: int, vix: float, cfg: dict[str, Any]) -> int:
    """Reduce OTM depth by 1 when VIX exceeds vega_cap_vix_threshold (high vega environment)."""
    threshold = _cfg_float(cfg, "vega_cap_vix_threshold", _DEF_VEGA_VIX)
    if vix > threshold and steps > 0:
        return steps - 1
    return steps


def _apply_otm_direction(atm: int, steps: int, direction: str, step: int) -> int:
    """Convert a step count into an actual strike price."""
    if steps <= 0:
        return atm
    offset = steps * step
    if str(direction).upper() == "CALL":
        return atm + offset   # CALL OTM: higher strike
    return atm - offset       # PUT OTM: lower strike


# ── Public API ────────────────────────────────────────────────────────────────


def select_strike(
    atm: int,
    direction: str,
    step: int,
    tier: str,
    vix: float,
    dte: int,
    cfg: dict[str, Any] | None = None,
) -> tuple[int, str]:
    """
    Select the target strike price for a new options entry.

    Args:
        atm       : ATM strike (int(round(spot / step) * step)).
        direction : "CALL" or "PUT".
        step      : Strike grid spacing (e.g. 50 for NIFTY, 100 for BANKNIFTY).
        tier      : Signal tier — "STRONG", "MODERATE", "WEAK", "IGNORE".
        vix       : India VIX reading (used for delta model + vega cap).
        dte       : Calendar days to expiry (0 = expiry day).
        cfg       : Bot config dict.

    Returns:
        (strike, reason_tag)
            strike     : Selected strike price (may equal ATM if mode=ATM or no offset).
            reason_tag : Human-readable log string explaining the selection.
    """
    c = cfg or {}
    mode = str(c.get("strike_selection_mode", _DEF_MODE)).upper()
    max_steps = _cfg_int(c, "max_otm_steps", _DEF_MAX_OTM)

    if mode == "OTM":
        steps = _otm_steps_for_tier(tier, c)
        steps = _apply_vega_cap(steps, vix, c)
        steps = min(steps, max_steps)
        strike = _apply_otm_direction(atm, steps, direction, step)
        tag = f"OTM tier={tier} steps={steps} vix={vix:.1f}"

    elif mode == "DELTA":
        from core.option_premium_model import atm_delta as _atm_delta
        atm_d = _atm_delta(vix, dte)
        target_d = _cfg_float(c, "strike_target_delta", _DEF_TARGET_DELTA)
        d_per_step = _cfg_float(c, "delta_per_step", _DEF_DELTA_STEP)
        steps = _otm_steps_for_delta(atm_d, target_d, d_per_step, max_steps)
        steps = _apply_vega_cap(steps, vix, c)
        strike = _apply_otm_direction(atm, steps, direction, step)
        approx_delta = round(atm_d - steps * d_per_step, 3)
        tag = (
            f"DELTA target={target_d:.2f} atm_d={atm_d:.3f} "
            f"steps={steps} approx_d={approx_delta:.3f} dte={dte}"
        )

    else:  # ATM (default — backward compatible)
        strike = atm
        tag = "ATM (default)"

    if strike != atm:
        _log.debug("[STRIKE] %s %s: ATM=%d → selected=%d [%s]", direction, tier, atm, strike, tag)

    return int(strike), tag


def dte_entry_check(
    dte: int,
    cfg: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """
    Theta bleed / minimum-DTE gate.

    Returns (allowed, reason).  allowed=False hard-blocks the entry.
    A warning is logged (but entry is not blocked) when DTE <= theta_bleed_warn_dte.

    Args:
        dte : Calendar days to expiry.
        cfg : Bot config dict.

    Returns:
        (True, "") if entry is allowed.
        (False, reason) if DTE is below min_dte_for_entry.
    """
    c = cfg or {}
    min_dte  = _cfg_int(c, "min_dte_for_entry",    _DEF_MIN_DTE)
    warn_dte = _cfg_int(c, "theta_bleed_warn_dte", _DEF_WARN_DTE)

    if dte < min_dte:
        reason = f"DTE={dte} < min_dte_for_entry={min_dte} — theta too high"
        _log.info("[STRIKE] Entry blocked: %s", reason)
        return False, reason

    if dte <= warn_dte:
        _log.warning(
            "[STRIKE] DTE=%d <= theta_bleed_warn_dte=%d — near-expiry theta risk elevated",
            dte, warn_dte,
        )

    return True, ""


def strike_summary(
    atm: int,
    direction: str,
    step: int,
    tier: str,
    vix: float,
    dte: int,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a snapshot dict for logging and Telegram alerts."""
    strike, reason = select_strike(atm, direction, step, tier, vix, dte, cfg)
    dte_ok, dte_reason = dte_entry_check(dte, cfg)
    return {
        "mode":         str((cfg or {}).get("strike_selection_mode", _DEF_MODE)).upper(),
        "atm":          atm,
        "selected":     strike,
        "otm_steps":    (strike - atm) // step if direction.upper() == "CALL" else (atm - strike) // step,
        "direction":    direction,
        "tier":         tier,
        "vix":          vix,
        "dte":          dte,
        "dte_allowed":  dte_ok,
        "reason":       reason,
        "dte_reason":   dte_reason,
    }
