"""
Slippage Auto-Calibration Model (v2.45 Item 14).

Fits a linear regression of observed slippage against order features
(lot size, bid-ask spread pct) using historical trade journal data.
Uses numpy for regression to avoid a hard scipy dependency.

Public API
----------
    calibrate_model(db_path, cfg)               → SlippageModel | None
    predict_slippage(lot_size, spread_pct, model) → float
    format_slippage_summary(model)              → str

Config keys
-----------
    slippage_model_enabled          : bool  default true
    slippage_calibration_min_samples: int   default 20
    slippage_model_lookback_days    : int   default 60
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

_log = logging.getLogger(__name__)


@dataclass
class SlippageModel:
    intercept:       float   # baseline slippage in ticks / pct
    lot_coeff:       float   # marginal slippage per additional lot
    spread_coeff:    float   # marginal slippage per 1% spread widening
    r_squared:       float   # fit quality  0–1
    n_samples:       int
    calibrated_at:   str     # ISO timestamp


def _load_journal(db_path: str, days: int) -> list[tuple[float, float, float]]:
    """
    Load (lot_size, spread_pct, slippage) rows from trade_journal.

    Returns list of (lot_size, spread_pct, slippage_pct) tuples.
    """
    try:
        con = sqlite3.connect(db_path)
        cur = con.execute(
            """
            SELECT lot_size, spread_pct, slippage_pct
            FROM trade_journal
            WHERE lot_size IS NOT NULL
              AND spread_pct IS NOT NULL
              AND slippage_pct IS NOT NULL
              AND DATE(entry_ts) >= DATE('now', ? || ' days')
            """,
            (f"-{days}",),
        )
        rows = [(float(r[0]), float(r[1]), float(r[2])) for r in cur.fetchall()]
        con.close()
        return rows
    except Exception as e:
        _log.debug("[SLIP] journal load failed: %s", e)
        return []


def _ols(X: list[list[float]], y: list[float]) -> tuple[list[float], float]:
    """
    Ordinary least squares via numpy.  Returns (coefficients, r_squared).
    coefficients = [intercept, coeff_1, coeff_2, ...]
    """
    try:
        import numpy as np
        A = np.column_stack([[1.0] * len(y)] + [[row[i] for row in X] for i in range(len(X[0]))])
        b = np.array(y)
        coefs, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        y_hat = A @ coefs
        ss_res = float(np.sum((b - y_hat) ** 2))
        ss_tot = float(np.sum((b - np.mean(b)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
        return list(coefs), round(r2, 4)
    except Exception as e:
        _log.debug("[SLIP] OLS failed: %s", e)
        return [0.0, 0.0, 0.0], 0.0


def calibrate_model(
    db_path: str = "trade_journal.db",
    cfg: dict[str, Any] | None = None,
) -> SlippageModel | None:
    """
    Fit a slippage linear model from historical trade journal data.

    Model: slippage_pct = intercept + lot_coeff × lot_size + spread_coeff × spread_pct

    Args:
        db_path: path to trade_journal SQLite database.
        cfg:     config dict.

    Returns:
        SlippageModel or None if insufficient data or disabled.
    """
    c = cfg or {}
    if not c.get("slippage_model_enabled", True):
        return None

    min_samples = int(c.get("slippage_calibration_min_samples", 20))
    days        = int(c.get("slippage_model_lookback_days",      60))

    rows = _load_journal(db_path, days)
    if len(rows) < min_samples:
        _log.debug("[SLIP] only %d samples, need %d", len(rows), min_samples)
        return None

    X  = [[r[0], r[1]] for r in rows]   # [lot_size, spread_pct]
    y  = [r[2] for r in rows]           # slippage_pct
    coefs, r2 = _ols(X, y)

    try:
        from core.datetime_ist import now_ist
        ts = now_ist().isoformat(timespec="seconds")
    except Exception:
        import datetime
        ts = datetime.datetime.now().isoformat(timespec="seconds")

    return SlippageModel(
        intercept=round(coefs[0], 6),
        lot_coeff=round(coefs[1], 6),
        spread_coeff=round(coefs[2], 6),
        r_squared=r2,
        n_samples=len(rows),
        calibrated_at=ts,
    )


def predict_slippage(
    lot_size:   float,
    spread_pct: float,
    model:      SlippageModel | None = None,
) -> float:
    """
    Predict slippage percentage for a given order.

    Args:
        lot_size:   number of lots.
        spread_pct: current bid-ask spread as a percentage of mid.
        model:      calibrated SlippageModel (returns 0.0 if None).

    Returns:
        Predicted slippage percentage (≥ 0).
    """
    if model is None:
        return 0.0
    raw = model.intercept + model.lot_coeff * lot_size + model.spread_coeff * spread_pct
    return round(max(0.0, raw), 4)


def format_slippage_summary(model: SlippageModel | None) -> str:
    """Return a one-line summary of the calibrated model."""
    if model is None:
        return "[slippage_model] not calibrated"
    return (
        f"[slippage_model] n={model.n_samples} R²={model.r_squared:.3f} "
        f"intercept={model.intercept:.4f} lot={model.lot_coeff:.4f} "
        f"spread={model.spread_coeff:.4f} @ {model.calibrated_at}"
    )
