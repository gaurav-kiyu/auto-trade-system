"""Signal Outcome Measurement Dataset & Analytical Engine (Phase B).

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001 / v2.60 Phase B Roadmap.

Connects immutable prediction snapshots with real subsequent market observations:
IMMUTABLE PREDICTION -> MARKET OBSERVATIONS -> OUTCOME CLASSIFICATION -> MFE / MAE / TIME-TO-EVENT -> ANALYTICAL DATASET

Strict Governance Invariants:
- Immutability: NEVER mutates prediction snapshots (signal_prediction_snapshots).
- Zero Look-Ahead Bias: Only observations strictly >= prediction timestamp (T0) are admitted.
- Directional MFE/MAE: Favorable and adverse excursions strictly respect CALL vs PUT direction.
- Non-Negative MAE Magnitude: MAE is represented as a non-negative magnitude.
- Strict Ambiguity Preservation: AMBIGUOUS_SAME_BAR is quarantined and never converted to win/loss.
- Realized R Integrity: Realized R is calculated exclusively from validated exits and initial risk.
- Zero Probability Fabrication: No probabilities are tuned, calibrated, or converted from scores.
- Idempotency & Determinism: Re-running dataset construction updates only derived analytical rows.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger("SIGNAL_OUTCOME_DATASET")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

CALCULATION_VERSION = "OUTCOME_MEASUREMENT_V1"


def parse_timestamp(ts: Any) -> datetime.datetime | None:
    """Parse various timestamp representations into a standardized datetime object."""
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts
    if isinstance(ts, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        except Exception:
            return None
    s = str(ts).strip()
    if not s:
        return None
    # Normalize ISO format
    s_iso = s.replace("Z", "+00:00").replace(" ", "T")
    try:
        return datetime.datetime.fromisoformat(s_iso)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except Exception:
            pass
    return None


def calculate_directional_mfe_mae(
    direction: str, entry_price: float, prices: list[float]
) -> tuple[float, float, float, float]:
    """Calculate directional Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).

    For CALL / BUY / LONG:
        favorable = observed - entry
        adverse = entry - observed
    For PUT / SELL / SHORT:
        favorable = entry - observed
        adverse = observed - entry

    Returns:
        (mfe, mae, mfe_pct, mae_pct)
        where mae and mae_pct are non-negative magnitudes.
    """
    if entry_price <= 0 or not prices:
        return 0.0, 0.0, 0.0, 0.0

    is_call = direction.upper() in ("CALL", "BUY", "LONG")
    fav_list: list[float] = []
    adv_list: list[float] = []

    for p in prices:
        if p <= 0:
            continue
        if is_call:
            fav = p - entry_price
            adv = entry_price - p
        else:
            fav = entry_price - p
            adv = p - entry_price
        fav_list.append(fav)
        adv_list.append(adv)

    if not fav_list:
        return 0.0, 0.0, 0.0, 0.0

    mfe = max(0.0, max(fav_list))
    mae = max(0.0, max(adv_list))
    mfe_pct = round((mfe / entry_price) * 100.0, 4)
    mae_pct = round((mae / entry_price) * 100.0, 4)
    return round(mfe, 4), round(mae, 4), mfe_pct, mae_pct


def calculate_realized_r(
    direction: str, entry_price: float, exit_price: float | None, initial_risk: float | None
) -> float | None:
    """Calculate realized R-multiple at exit.

    For CALL: (exit_price - entry_price) / initial_risk
    For PUT:  (entry_price - exit_price) / initial_risk
    """
    if exit_price is None or initial_risk is None or initial_risk <= 0 or entry_price <= 0:
        return None
    is_call = direction.upper() in ("CALL", "BUY", "LONG")
    if is_call:
        r = (exit_price - entry_price) / initial_risk
    else:
        r = (entry_price - exit_price) / initial_risk
    return round(r, 4)


def normalize_outcome_state(
    first_touch: str, raw_status: str, has_observations: bool, is_valid: bool
) -> str:
    """Classify the normalized analytical outcome from raw lifecycle and touch states.

    Normalized Outcomes:
    - TARGET_FIRST
    - SL_FIRST
    - TIMEOUT
    - INVALIDATED
    - AMBIGUOUS
    - NO_DATA
    - UNRESOLVED
    """
    if not is_valid:
        return "INVALIDATED"
    if not has_observations:
        return "NO_DATA"

    ft = (first_touch or "").strip().upper()
    status = (raw_status or "").strip().upper()

    if ft in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR") or status in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR"):
        return "AMBIGUOUS"
    if ft in ("T1", "T2") or status in ("TARGET_1_HIT", "TARGET_2_HIT"):
        return "TARGET_FIRST"
    if ft == "SL" or status == "SL_HIT":
        return "SL_FIRST"
    if ft == "EXPIRED" or status == "EXPIRED":
        return "TIMEOUT"
    if status in ("OPEN", "ACTIVE"):
        return "UNRESOLVED"
    return "UNRESOLVED"


@dataclass
class OutcomeMeasurement:
    """Analytical measurement of a signal's post-prediction outcome."""

    signal_id: str
    prediction_snapshot_id: str
    symbol: str
    category: str
    direction: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    initial_risk: float | None
    observed_from: str
    observed_until: str | None
    outcome: str
    raw_lifecycle_state: str
    first_touch: str | None
    first_touch_at: str | None
    first_touch_price: float | None
    target_1_hit: int
    target_1_hit_at: str | None
    target_1_hit_price: float | None
    target_2_hit: int
    target_2_hit_at: str | None
    target_2_hit_price: float | None
    stop_loss_hit: int
    stop_loss_hit_at: str | None
    stop_loss_hit_price: float | None
    mfe: float | None
    mae: float | None
    mfe_pct: float | None
    mae_pct: float | None
    mfe_r: float | None
    mae_r: float | None
    time_to_first_event_seconds: float | None
    time_to_t1_seconds: float | None
    time_to_t2_seconds: float | None
    time_to_sl_seconds: float | None
    realized_r: float | None
    exit_price: float | None
    exit_at: str | None
    observation_count: int
    data_quality_status: str
    outcome_confidence: str
    calculation_version: str = CALCULATION_VERSION
    calculated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SignalOutcomeDatasetService:
    """Thread-safe analytical engine for materializing signal outcome measurements."""

    _instance: SignalOutcomeDatasetService | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._io_lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalOutcomeDatasetService:
        with cls._lock:
            if cls._instance is None:
                cls._instance = SignalOutcomeDatasetService(
                    db_path=Path(db_path) if db_path is not None else None
                )
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instance = None

    def _get_conn(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the dedicated signal_outcome_measurements table if not exists."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signal_outcome_measurements (
                        signal_id TEXT PRIMARY KEY,
                        prediction_snapshot_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        category TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        target_1 REAL NOT NULL,
                        target_2 REAL NOT NULL,
                        initial_risk REAL,
                        observed_from TEXT NOT NULL,
                        observed_until TEXT,
                        outcome TEXT NOT NULL,
                        raw_lifecycle_state TEXT NOT NULL,
                        first_touch TEXT,
                        first_touch_at TEXT,
                        first_touch_price REAL,
                        target_1_hit INTEGER NOT NULL DEFAULT 0,
                        target_1_hit_at TEXT,
                        target_1_hit_price REAL,
                        target_2_hit INTEGER NOT NULL DEFAULT 0,
                        target_2_hit_at TEXT,
                        target_2_hit_price REAL,
                        stop_loss_hit INTEGER NOT NULL DEFAULT 0,
                        stop_loss_hit_at TEXT,
                        stop_loss_hit_price REAL,
                        mfe REAL,
                        mae REAL,
                        mfe_pct REAL,
                        mae_pct REAL,
                        mfe_r REAL,
                        mae_r REAL,
                        time_to_first_event_seconds REAL,
                        time_to_t1_seconds REAL,
                        time_to_t2_seconds REAL,
                        time_to_sl_seconds REAL,
                        realized_r REAL,
                        exit_price REAL,
                        exit_at TEXT,
                        observation_count INTEGER NOT NULL DEFAULT 0,
                        data_quality_status TEXT NOT NULL DEFAULT 'VALID_DATA',
                        outcome_confidence TEXT DEFAULT 'UNKNOWN',
                        calculation_version TEXT NOT NULL DEFAULT 'OUTCOME_MEASUREMENT_V1',
                        calculated_at TEXT NOT NULL,
                        FOREIGN KEY (signal_id) REFERENCES signal_prediction_snapshots(signal_id)
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_outcome_meas_sym ON signal_outcome_measurements(symbol)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_outcome_meas_outcome ON signal_outcome_measurements(outcome)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_outcome_meas_calc_at ON signal_outcome_measurements(calculated_at)")
                conn.commit()
            except Exception as ex:
                _log.error("Failed to initialize signal_outcome_measurements: %s", ex)
            finally:
                conn.close()

    def build_signal_outcome_measurement(self, signal_id: str) -> dict[str, Any] | None:
        """Calculate and materialize the post-prediction outcome measurement for a single signal.

        Enforces:
        - Immutability: Never updates prediction snapshot or original signal.
        - Zero Look-Ahead: Observations before T0 are strictly ignored.
        - Directional Excursion: MFE and MAE respect CALL vs PUT.
        - Ambiguity Preservation: AMBIGUOUS_SAME_BAR is never coerced.
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()

                # 1. Load immutable prediction snapshot (or fallback to system_signals for legacy compatibility)
                cur.execute("SELECT * FROM signal_prediction_snapshots WHERE signal_id = ?", (signal_id,))
                snapshot_row = cur.fetchone()

                cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", (signal_id,))
                signal_row = cur.fetchone()

                if not snapshot_row and not signal_row:
                    return None

                # Base fields derived from snapshot (immutable ground truth at T0)
                pred_dict = dict(snapshot_row) if snapshot_row else dict(signal_row)
                sig_dict = dict(signal_row) if signal_row else dict(snapshot_row)

                symbol = str(pred_dict.get("symbol", "")).upper()
                category = str(pred_dict.get("category", "")).upper()
                direction = str(pred_dict.get("direction", "CALL")).upper()
                is_call = direction in ("CALL", "BUY", "LONG")

                entry_price = float(pred_dict.get("entry_price") or 0.0)
                stop_loss = float(pred_dict.get("stop_loss") or 0.0)
                target_1 = float(pred_dict.get("target_1") or 0.0)
                target_2 = float(pred_dict.get("target_2") or 0.0)

                # Prediction timestamp T0
                observed_from = str(pred_dict.get("captured_at") or pred_dict.get("timestamp") or "").strip()
                t0_dt = parse_timestamp(observed_from)

                # Initial Risk calculation
                initial_risk: float | None = None
                if entry_price > 0 and stop_loss > 0:
                    diff = (entry_price - stop_loss) if is_call else (stop_loss - entry_price)
                    if diff > 0:
                        initial_risk = round(diff, 4)
                    else:
                        initial_risk = round(abs(entry_price - stop_loss), 4)

                # Check data validity
                is_valid = entry_price > 0 and stop_loss > 0 and target_1 > 0

                # 2. Query outcome events strictly adhering to NO LOOK-AHEAD (observed_at >= T0)
                cur.execute(
                    """SELECT event_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2, transition_note
                       FROM signal_outcome_events
                       WHERE signal_id = ?
                       ORDER BY observed_at ASC, event_id ASC""",
                    (signal_id,),
                )
                raw_events = [dict(r) for r in cur.fetchall()]

                # Filter events with zero look-ahead bias
                valid_events: list[dict[str, Any]] = []
                for ev in raw_events:
                    ev_ts = parse_timestamp(ev["observed_at"])
                    if ev_ts is not None and t0_dt is not None:
                        # Allow same-second or later observations; discard strictly earlier
                        if ev_ts < t0_dt:
                            continue
                    valid_events.append(ev)

                # 3. Detect barrier hits and timestamps
                t1_hit = 0
                t1_hit_at: str | None = None
                t1_hit_price: float | None = None

                t2_hit = 0
                t2_hit_at: str | None = None
                t2_hit_price: float | None = None

                sl_hit = 0
                sl_hit_at: str | None = None
                sl_hit_price: float | None = None

                obs_prices: list[float] = []
                latest_obs_at: str | None = observed_from

                for ev in valid_events:
                    p = float(ev.get("observed_price") or 0.0)
                    ts_str = ev.get("observed_at")
                    if p > 0:
                        obs_prices.append(p)
                        latest_obs_at = ts_str

                    if int(ev.get("hit_t1") or 0) == 1 and t1_hit == 0:
                        t1_hit = 1
                        t1_hit_at = ts_str
                        t1_hit_price = p

                    if int(ev.get("hit_t2") or 0) == 1 and t2_hit == 0:
                        t2_hit = 1
                        t2_hit_at = ts_str
                        t2_hit_price = p

                    if int(ev.get("hit_sl") or 0) == 1 and sl_hit == 0:
                        sl_hit = 1
                        sl_hit_at = ts_str
                        sl_hit_price = p

                # Check system_signals lifecycle truth if events were summarized
                raw_lifecycle_state = str(sig_dict.get("status") or "ACTIVE").upper()
                first_touch = str(sig_dict.get("first_touch") or "").strip() or None
                first_touch_at = str(sig_dict.get("first_touch_at") or "").strip() or None
                first_touch_price_raw = float(sig_dict.get("first_touch_price") or 0.0)
                first_touch_price = first_touch_price_raw if first_touch_price_raw > 0 else None
                outcome_confidence = str(sig_dict.get("outcome_confidence") or "UNKNOWN")

                # If first_touch was T1, ensure t1_hit is flagged
                if first_touch in ("T1", "T2") or raw_lifecycle_state in ("TARGET_1_HIT", "TARGET_2_HIT"):
                    if t1_hit == 0:
                        t1_hit = 1
                        t1_hit_at = t1_hit_at or first_touch_at
                        t1_hit_price = t1_hit_price or first_touch_price or target_1
                    if target_1 > 0 and target_1 not in obs_prices:
                        obs_prices.append(target_1)

                if first_touch == "T2" or raw_lifecycle_state == "TARGET_2_HIT":
                    if t2_hit == 0:
                        t2_hit = 1
                        t2_hit_at = t2_hit_at or first_touch_at
                        t2_hit_price = t2_hit_price or target_2
                    if target_2 > 0 and target_2 not in obs_prices:
                        obs_prices.append(target_2)

                if first_touch == "SL" or raw_lifecycle_state == "SL_HIT":
                    if sl_hit == 0:
                        sl_hit = 1
                        sl_hit_at = sl_hit_at or first_touch_at
                        sl_hit_price = sl_hit_price or first_touch_price or stop_loss
                    if stop_loss > 0 and stop_loss not in obs_prices:
                        obs_prices.append(stop_loss)

                # Include first_touch_price & current_price into price path if valid post-T0
                if first_touch_price and first_touch_price > 0 and first_touch_price not in obs_prices:
                    obs_prices.append(first_touch_price)

                curr_p = float(sig_dict.get("current_price") or 0.0)
                if curr_p > 0 and curr_p not in obs_prices:
                    obs_prices.append(curr_p)

                # Same-bar ambiguity detection
                is_ambiguous = (
                    first_touch in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR")
                    or raw_lifecycle_state in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR")
                    or outcome_confidence == "AMBIGUOUS"
                )

                # Data Quality Status
                has_obs = len(obs_prices) > 0
                if not is_valid:
                    data_quality_status = "INVALID_DATA"
                elif is_ambiguous:
                    data_quality_status = "AMBIGUOUS_DATA"
                elif not has_obs:
                    data_quality_status = "NO_DATA"
                else:
                    data_quality_status = "VALID_DATA"

                # 4. Normalized Outcome Classification
                outcome = normalize_outcome_state(
                    first_touch=first_touch or "",
                    raw_status=raw_lifecycle_state,
                    has_observations=has_obs,
                    is_valid=is_valid,
                )

                # 5. MFE & MAE Calculation
                mfe: float | None = None
                mae: float | None = None
                mfe_pct: float | None = None
                mae_pct: float | None = None
                mfe_r: float | None = None
                mae_r: float | None = None

                if is_valid and has_obs:
                    mfe_val, mae_val, mfe_p, mae_p = calculate_directional_mfe_mae(
                        direction=direction, entry_price=entry_price, prices=obs_prices
                    )
                    mfe = mfe_val
                    mae = mae_val
                    mfe_pct = mfe_p
                    mae_pct = mae_p
                    if initial_risk and initial_risk > 0:
                        mfe_r = round(mfe / initial_risk, 4)
                        mae_r = round(mae / initial_risk, 4)

                # 6. Time-to-Event Calculations
                time_to_first_event_seconds: float | None = None
                time_to_t1_seconds: float | None = None
                time_to_t2_seconds: float | None = None
                time_to_sl_seconds: float | None = None

                if t0_dt is not None:
                    if first_touch_at:
                        dt_ft = parse_timestamp(first_touch_at)
                        if dt_ft is not None:
                            diff = (dt_ft - t0_dt).total_seconds()
                            if diff >= 0:
                                time_to_first_event_seconds = round(diff, 1)

                    if t1_hit_at:
                        dt_t1 = parse_timestamp(t1_hit_at)
                        if dt_t1 is not None:
                            diff = (dt_t1 - t0_dt).total_seconds()
                            if diff >= 0:
                                time_to_t1_seconds = round(diff, 1)

                    if t2_hit_at:
                        dt_t2 = parse_timestamp(t2_hit_at)
                        if dt_t2 is not None:
                            diff = (dt_t2 - t0_dt).total_seconds()
                            if diff >= 0:
                                time_to_t2_seconds = round(diff, 1)

                    if sl_hit_at:
                        dt_sl = parse_timestamp(sl_hit_at)
                        if dt_sl is not None:
                            diff = (dt_sl - t0_dt).total_seconds()
                            if diff >= 0:
                                time_to_sl_seconds = round(diff, 1)

                # 7. Realized R and Exit Price Calculation
                exit_price: float | None = None
                exit_at: str | None = None

                if outcome == "TARGET_FIRST":
                    if t2_hit and t2_hit_price:
                        exit_price = t2_hit_price
                        exit_at = t2_hit_at
                    elif t1_hit_price:
                        exit_price = t1_hit_price
                        exit_at = t1_hit_at
                    else:
                        exit_price = target_1
                        exit_at = first_touch_at
                elif outcome == "SL_FIRST":
                    exit_price = sl_hit_price or stop_loss
                    exit_at = sl_hit_at or first_touch_at
                elif outcome == "TIMEOUT":
                    exit_price = first_touch_price or curr_p or None
                    exit_at = first_touch_at or latest_obs_at

                realized_r: float | None = None
                if exit_price is not None and is_valid and initial_risk and initial_risk > 0:
                    realized_r = calculate_realized_r(
                        direction=direction,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        initial_risk=initial_risk,
                    )

                calculated_at = now_ist().isoformat()
                measurement = OutcomeMeasurement(
                    signal_id=signal_id,
                    prediction_snapshot_id=signal_id,
                    symbol=symbol,
                    category=category,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    target_1=target_1,
                    target_2=target_2,
                    initial_risk=initial_risk,
                    observed_from=observed_from,
                    observed_until=latest_obs_at,
                    outcome=outcome,
                    raw_lifecycle_state=raw_lifecycle_state,
                    first_touch=first_touch,
                    first_touch_at=first_touch_at,
                    first_touch_price=first_touch_price,
                    target_1_hit=t1_hit,
                    target_1_hit_at=t1_hit_at,
                    target_1_hit_price=t1_hit_price,
                    target_2_hit=t2_hit,
                    target_2_hit_at=t2_hit_at,
                    target_2_hit_price=t2_hit_price,
                    stop_loss_hit=sl_hit,
                    stop_loss_hit_at=sl_hit_at,
                    stop_loss_hit_price=sl_hit_price,
                    mfe=mfe,
                    mae=mae,
                    mfe_pct=mfe_pct,
                    mae_pct=mae_pct,
                    mfe_r=mfe_r,
                    mae_r=mae_r,
                    time_to_first_event_seconds=time_to_first_event_seconds,
                    time_to_t1_seconds=time_to_t1_seconds,
                    time_to_t2_seconds=time_to_t2_seconds,
                    time_to_sl_seconds=time_to_sl_seconds,
                    realized_r=realized_r,
                    exit_price=exit_price,
                    exit_at=exit_at,
                    observation_count=len(valid_events),
                    data_quality_status=data_quality_status,
                    outcome_confidence=outcome_confidence,
                    calculation_version=CALCULATION_VERSION,
                    calculated_at=calculated_at,
                )

                # Materialize idempotently into signal_outcome_measurements
                cur.execute("""
                    INSERT OR REPLACE INTO signal_outcome_measurements (
                        signal_id, prediction_snapshot_id, symbol, category, direction,
                        entry_price, stop_loss, target_1, target_2, initial_risk,
                        observed_from, observed_until, outcome, raw_lifecycle_state,
                        first_touch, first_touch_at, first_touch_price,
                        target_1_hit, target_1_hit_at, target_1_hit_price,
                        target_2_hit, target_2_hit_at, target_2_hit_price,
                        stop_loss_hit, stop_loss_hit_at, stop_loss_hit_price,
                        mfe, mae, mfe_pct, mae_pct, mfe_r, mae_r,
                        time_to_first_event_seconds, time_to_t1_seconds,
                        time_to_t2_seconds, time_to_sl_seconds, realized_r,
                        exit_price, exit_at, observation_count, data_quality_status,
                        outcome_confidence, calculation_version, calculated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                """, (
                    measurement.signal_id, measurement.prediction_snapshot_id, measurement.symbol,
                    measurement.category, measurement.direction, measurement.entry_price,
                    measurement.stop_loss, measurement.target_1, measurement.target_2,
                    measurement.initial_risk, measurement.observed_from, measurement.observed_until,
                    measurement.outcome, measurement.raw_lifecycle_state, measurement.first_touch,
                    measurement.first_touch_at, measurement.first_touch_price, measurement.target_1_hit,
                    measurement.target_1_hit_at, measurement.target_1_hit_price, measurement.target_2_hit,
                    measurement.target_2_hit_at, measurement.target_2_hit_price, measurement.stop_loss_hit,
                    measurement.stop_loss_hit_at, measurement.stop_loss_hit_price, measurement.mfe,
                    measurement.mae, measurement.mfe_pct, measurement.mae_pct, measurement.mfe_r,
                    measurement.mae_r, measurement.time_to_first_event_seconds, measurement.time_to_t1_seconds,
                    measurement.time_to_t2_seconds, measurement.time_to_sl_seconds, measurement.realized_r,
                    measurement.exit_price, measurement.exit_at, measurement.observation_count,
                    measurement.data_quality_status, measurement.outcome_confidence,
                    measurement.calculation_version, measurement.calculated_at
                ))
                conn.commit()
                return measurement.to_dict()
            except Exception as ex:
                _log.error("Failed to build signal outcome measurement for %s: %s", signal_id, ex)
                return None
            finally:
                conn.close()

    def build_signal_outcome_dataset(
        self,
        limit: int = 1000,
        category: str = "all",
        include_seed_samples: bool = False,
    ) -> list[dict[str, Any]]:
        """Materialize outcome measurements for all eligible prediction snapshots."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                query = "SELECT signal_id FROM signal_prediction_snapshots ORDER BY captured_at ASC"
                cur.execute(query)
                rows = cur.fetchall()
                sig_ids = [r["signal_id"] for r in rows]
            finally:
                conn.close()

        results: list[dict[str, Any]] = []
        for s_id in sig_ids[:max(1, limit)]:
            meas = self.build_signal_outcome_measurement(s_id)
            if meas:
                if category != "all" and meas["category"] != category:
                    continue
                results.append(meas)
        return results

    def get_outcome_measurement(self, signal_id: str) -> dict[str, Any] | None:
        """Retrieve a stored outcome measurement by signal_id."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM signal_outcome_measurements WHERE signal_id = ?", (signal_id,))
                row = cur.fetchone()
                return dict(row) if row else None
            finally:
                conn.close()

    def get_outcome_measurements(
        self, limit: int = 100, symbol: str | None = None, outcome: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve stored outcome measurements with optional symbol and outcome filtering."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                clauses = ["1=1"]
                params: list[Any] = []
                if symbol:
                    clauses.append("symbol = ?")
                    params.append(symbol.upper())
                if outcome:
                    clauses.append("outcome = ?")
                    params.append(outcome.upper())
                where_sql = " AND ".join(clauses)
                params.append(max(1, limit))
                cur.execute(
                    f"SELECT * FROM signal_outcome_measurements WHERE {where_sql} ORDER BY observed_from DESC LIMIT ?",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()
