"""OPB Phase D20: Signal Quality Remediation Gates & Governance Helper.

Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / Phase D20 Specification.

Implements:
- D20-A: Category-Aware Options Quality Gate
  For STOCK_OPTIONS and INDEX_OPTIONS, strictly requires:
      breakout > 0 AND volume > 0
  before persistence or dispatch. Fails closed on missing, invalid, or NaN evidence.
  Does NOT affect EQUITY_SWING_DELIVERY or other categories.
- D20-B: Index Call/Put Session Deduplication
  For INDEX_OPTIONS, enforces:
      Maximum 1 CALL + 1 PUT per canonical index underlying per trading session.
  CALL and PUT may coexist within the same session. Subsequent same-direction signals
  in the same session are rejected before persistence or dispatch.
- D20-C: Experimental Target Model Scaffolding
  Isolated experimental path comparing Baseline (+4% T1, +8% T2, -3% SL) versus
  Candidate (+1.2% T1) and ATR-scaled candidate, without altering production defaults.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from core.fno_universe import FNO_INDICES

_log = logging.getLogger("SIGNAL_QUALITY_GATE")

CANONICAL_INDEX_ORDER = (
    "MIDCPNIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "NIFTYNXT50",
    "BANKEX",
    "SENSEX",
    "NIFTY",
)


def get_canonical_index_underlying(symbol: str) -> str:
    """Resolve a raw or derivative symbol to its canonical index underlying name."""
    s = str(symbol).strip().upper().replace(".NS", "").replace("^", "")
    for idx in CANONICAL_INDEX_ORDER:
        if s == idx or s.startswith(idx):
            return idx
    return s


def validate_options_quality_gate(signal_data: Any, category: str | None = None) -> tuple[bool, str]:
    """Validate D20-A Category-Aware Options Quality Gate with strict fail-closed semantics.

    Rule:
    For STOCK_OPTIONS and INDEX_OPTIONS:
        require breakout > 0 AND volume > 0
    For all other categories (e.g. EQUITY_SWING_DELIVERY):
        gate does not apply (returns True).

    Returns:
        (passed: bool, reason: str)
    """
    # Extract category
    if category is None:
        if isinstance(signal_data, dict):
            category = str(signal_data.get("category") or "").upper()
        else:
            category = str(getattr(signal_data, "category", "") or "").upper()
    else:
        category = str(category).upper()

    # If category is not options, gate does not apply
    if category not in ("STOCK_OPTIONS", "INDEX_OPTIONS"):
        return True, "NOT_APPLICABLE_NON_OPTION"

    # Extract score_components
    comps = None
    if isinstance(signal_data, dict):
        comps = signal_data.get("score_components")
        if comps is None and "raw_data" in signal_data:
            raw = signal_data.get("raw_data")
            if isinstance(raw, dict):
                comps = raw.get("score_components")
            elif isinstance(raw, str):
                import json
                try:
                    comps = json.loads(raw).get("score_components")
                except Exception:
                    comps = None
    else:
        comps = getattr(signal_data, "score_components", None)

    # Fail closed: missing or invalid components container
    if comps is None or not isinstance(comps, dict):
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: score_components missing or unavailable", category)
        return False, "FAIL_CLOSED_MISSING_SCORE_COMPONENTS"

    # Fail closed: missing breakout key
    if "breakout" not in comps:
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: breakout component missing", category)
        return False, "FAIL_CLOSED_MISSING_BREAKOUT"

    # Fail closed: missing volume key
    if "volume" not in comps:
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: volume component missing", category)
        return False, "FAIL_CLOSED_MISSING_VOLUME"

    raw_bk = comps.get("breakout")
    raw_vol = comps.get("volume")

    # Fail closed: None or invalid types
    if raw_bk is None or raw_vol is None:
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: component value is None", category)
        return False, "FAIL_CLOSED_NONE_VALUE"

    try:
        bk_val = float(raw_bk)
        vol_val = float(raw_vol)
    except (ValueError, TypeError):
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: component value not numeric (bk=%s, vol=%s)", category, raw_bk, raw_vol)
        return False, "FAIL_CLOSED_NON_NUMERIC"

    # Fail closed: NaN or Inf values
    if math.isnan(bk_val) or math.isinf(bk_val):
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: breakout value is NaN or Inf", category)
        return False, "FAIL_CLOSED_NAN_BREAKOUT"

    if math.isnan(vol_val) or math.isinf(vol_val):
        _log.info("[OPTIONS_GATE_FAIL_CLOSED] %s rejected: volume value is NaN or Inf", category)
        return False, "FAIL_CLOSED_NAN_VOLUME"

    # Substantive gate: strictly require breakout > 0 AND volume > 0
    if bk_val <= 0:
        _log.info("[OPTIONS_GATE_REJECT] %s rejected: breakout %s <= 0", category, bk_val)
        return False, f"REJECTED_BREAKOUT_INSUFFICIENT (breakout={bk_val} <= 0)"

    if vol_val <= 0:
        _log.info("[OPTIONS_GATE_REJECT] %s rejected: volume %s <= 0", category, vol_val)
        return False, f"REJECTED_VOLUME_INSUFFICIENT (volume={vol_val} <= 0)"

    return True, "ELIGIBLE_OPTIONS_BREAKOUT_AND_VOLUME"


def check_index_session_dedup(
    conn_or_cursor: Any,
    symbol: str,
    category: str,
    direction: str,
    session_date: str,
) -> tuple[bool, str]:
    """Validate D20-B Index Session Deduplication.

    Rule:
    For INDEX_OPTIONS:
        Maximum 1 CALL + 1 PUT per canonical index underlying per trading session.
    A CALL and PUT can coexist in the same session.
    Second CALL or second PUT for the same index in the same session is rejected.

    Returns:
        (allowed: bool, reason: str)
    """
    cat_up = str(category or "").upper()
    if cat_up != "INDEX_OPTIONS":
        return True, "NOT_APPLICABLE_NON_INDEX"

    dir_up = str(direction or "").upper()
    if dir_up not in ("CALL", "PUT"):
        return True, "UNKNOWN_DIRECTION"

    canonical_idx = get_canonical_index_underlying(symbol)
    idx_pattern = f"{canonical_idx}%"

    try:
        # Check if cursor or connection
        cur = conn_or_cursor.cursor() if hasattr(conn_or_cursor, "cursor") else conn_or_cursor

        cur.execute(
            """SELECT signal_id, timestamp, direction FROM system_signals
               WHERE category = 'INDEX_OPTIONS'
                 AND direction = ?
                 AND created_date = ?
                 AND (symbol = ? OR symbol LIKE ? OR opportunity_key LIKE ?)
               ORDER BY timestamp ASC LIMIT 1""",
            (dir_up, session_date, canonical_idx, idx_pattern, idx_pattern),
        )
        existing = cur.fetchone()
        if existing:
            sig_id = existing["signal_id"] if hasattr(existing, "__getitem__") else existing[0]
            _log.info(
                "[INDEX_SESSION_DEDUP] Suppressed second %s for index %s in session %s (prior signal_id=%s)",
                dir_up, canonical_idx, session_date, sig_id,
            )
            return False, f"DEDUP_SUPPRESSED_INDEX_SESSION_LIMIT ({dir_up} already recorded for {canonical_idx} in session {session_date}, id={sig_id})"

        return True, f"ELIGIBLE_FIRST_INDEX_{dir_up}_IN_SESSION"
    except Exception as ex:
        _log.error("[INDEX_SESSION_DEDUP_ERROR] Database check failed: %s", ex)
        # Fail-closed for deduplication if query fails
        return False, f"FAIL_CLOSED_DB_ERROR: {ex}"


def calculate_experimental_target_levels(
    entry_price: float,
    direction: str,
    category: str,
    mode: str = "PRODUCTION",
    atr: float | None = None,
    stop_loss: float | None = None,
    target_1: float | None = None,
    target_2: float | None = None,
) -> tuple[float, float, float]:
    """Calculate target and stop-loss levels supporting isolated D20-C experimentation.

    Supported Modes:
    - "PRODUCTION": Current production defaults (+4.0% T1, +8.0% T2, -3.0% SL)
    - "CANDIDATE_1_2_PCT": Experimental +1.2% T1, +2.4% T2, -1.5% SL for options
    - "ATR_SCALED": Experimental 1.0 * ATR target & SL (clamped between 0.8% and 2.5%)

    IMPORTANT:
    Non-option categories always receive canonical production levels.
    Production defaults are returned whenever mode is "PRODUCTION" or unspecified.
    """
    is_call = str(direction).upper() in ("BUY", "CALL", "LONG")
    cat_up = str(category or "").upper()
    is_option = cat_up in ("STOCK_OPTIONS", "INDEX_OPTIONS")

    # If not in experimental mode or not an option, strictly use canonical defaults
    if mode == "PRODUCTION" or not is_option:
        from core.signal_utils import calculate_directional_levels
        return calculate_directional_levels(
            entry_price=entry_price,
            direction=direction,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
        )

    # D20-C Experimental Options Candidate: Target +1.2%, SL -1.5%
    if mode == "CANDIDATE_1_2_PCT":
        t1_pct = 0.012
        t2_pct = 0.024
        sl_pct = 0.015
    elif mode == "ATR_SCALED":
        if atr is not None and entry_price > 0 and atr > 0:
            atr_pct = (atr / entry_price)
            eff_t = max(0.008, min(0.025, atr_pct * 1.0))
            eff_sl = max(0.008, min(0.025, atr_pct * 1.0))
        else:
            eff_t = 0.012
            eff_sl = 0.015
        t1_pct = eff_t
        t2_pct = eff_t * 2.0
        sl_pct = eff_sl
    else:
        # Default fallback to production
        from core.signal_utils import calculate_directional_levels
        return calculate_directional_levels(
            entry_price=entry_price,
            direction=direction,
            stop_loss=stop_loss,
            target_1=target_1,
            target_2=target_2,
        )

    if is_call:
        calc_sl = round(entry_price * (1.0 - sl_pct), 2)
        calc_t1 = round(entry_price * (1.0 + t1_pct), 2)
        calc_t2 = round(entry_price * (1.0 + t2_pct), 2)
    else:
        calc_sl = round(entry_price * (1.0 + sl_pct), 2)
        calc_t1 = round(entry_price * (1.0 - t1_pct), 2)
        calc_t2 = round(entry_price * (1.0 - t2_pct), 2)

    return (calc_sl, calc_t1, calc_t2)
