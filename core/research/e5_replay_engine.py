"""OPB v2.60 — E5 Offline Historical Candle Replay & Barrier Evaluation Engine.

Governing Standard: OPB-FINAL-PHASE-GOVERNANCE-001
Governing Specification: OPB-V260-E4.1-SHADOW-TELEMETRY-FORMAL-SPEC-20261003-001
Authorization: OPB v2.60 — E5 Offline Historical Candle Replay & Barrier Evaluation Authorization

This module implements the isolated research replay engine designed to evaluate
Point-A setup-qualified candidate observations across the pre-authorized 6 barrier
models (M1–M6) and 6 discrete horizons using genuine historical completed candles.

Strict Safety Invariants:
1. Production DB Immutability: Writes exclusively to db/e5_research_results.db.
   Attempting to connect to db/signals_history.db raises an immediate fatal ValueError.
2. Zero Look-Ahead Leakage: All barriers and candidate features derive strictly from
   candidate-time Point-A values. Forward candles start strictly after candidate timestamp.
3. First-Touch Immutability & Same-Candle Ambiguity: First touched barrier defines terminal
   state. If both Target and SL are breached in the same bar, quarantined as AMBIGUOUS.
4. No Synthetic Market Data: Zero interpolation, zero forward-filling. Incomplete forward
   windows are classified as INSUFFICIENT_FORWARD_DATA.
5. Non-Optimization: Purely factual descriptive measurement across the fixed E1 grid.
   No model is selected as optimal or winner.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.datetime_ist import now_ist
from core.exchange_calendar_engine import ExchangeCalendarEngine
# OPB v2.60 E4.2.2 / E5 Specification: Explicit E5 Telemetry Population Definition
E5_TELEMETRY_POPULATION = "POST-EVALUATOR / SETUP-QUALIFIED CANDIDATES ENTERING scan_universe() AT POINT-A"


def canonical_json_dumps(obj: Any) -> str:
    """Deterministic, sorted-key JSON serialization for cryptographic hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def generate_candidate_obs_id(
    market_date: str,
    cycle_id: str,
    symbol: str,
    direction: str,
    candidate_timestamp: str | None = None,
    entry_price: float | None = None,
) -> str:
    """Generate deterministic, reproducible observation ID for a candidate observed at Point-A.

    Uses a deterministic SHA-256 canonical payload of Point-A candidate fields.
    Contains zero randomness, zero UUID tokens, and no future or outcome fields.
    """
    clean_date = market_date.replace("-", "")
    sym_clean = symbol.strip().upper()
    dir_clean = direction.strip().upper()

    price_str = ""
    if entry_price is not None:
        try:
            price_str = f"{float(entry_price):.4f}"
        except (ValueError, TypeError):
            price_str = str(entry_price)

    ts_str = str(candidate_timestamp).strip() if candidate_timestamp else ""

    identity_payload = {
        "market_date": clean_date,
        "cycle_id": cycle_id,
        "symbol": sym_clean,
        "direction": dir_clean,
        "candidate_timestamp": ts_str,
        "entry_price": price_str,
    }
    canonical_str = canonical_json_dumps(identity_payload)
    hash_suffix = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()[:8]

    return f"CAND-OBS-{clean_date}-{cycle_id}-{sym_clean}-{dir_clean}-{hash_suffix}"


_log = logging.getLogger("OPB_E5_REPLAY_ENGINE")
_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_E5_DB_PATH = _ROOT / "db" / "e5_research_results.db"
PROD_DB_NAME = "signals_history.db"

# ==============================================================================
# 1. DATABASE PATH VALIDATION (SAFETY ASSERTION)
# ==============================================================================

def validate_e5_db_path(path: Path | str) -> Path:
    """Validate that the E5 research database path does NOT target the production database.

    Enforces strict physical separation from signals_history.db.
    """
    resolved = Path(path).resolve()
    target_name = resolved.name.lower()
    full_str = str(resolved).lower()

    if target_name == PROD_DB_NAME or "signals_history" in full_str:
        raise ValueError(
            f"CRITICAL SAFETY VIOLATION: E5 replay database path '{resolved}' targets "
            "production database! Replay writes must go exclusively to e5_research_results.db."
        )
    return resolved


# ==============================================================================
# 2. PRE-AUTHORIZED BARRIER MODELS & HORIZONS SPECIFICATION
# ==============================================================================

@dataclass(frozen=True)
class BarrierModel:
    model_id: str
    t1_multiplier: float
    sl_multiplier: float
    t2_multiplier: float
    description: str


PRE_AUTHORIZED_MODELS: dict[str, BarrierModel] = {
    "M1": BarrierModel("M1", 1.0, 1.0, 2.0, "T1=1.0x, SL=1.0x, T2=2.0x ATR"),
    "M2": BarrierModel("M2", 1.5, 1.0, 3.0, "T1=1.5x, SL=1.0x, T2=3.0x ATR"),
    "M3": BarrierModel("M3", 2.0, 1.0, 3.0, "T1=2.0x, SL=1.0x, T2=3.0x ATR"),
    "M4": BarrierModel("M4", 2.0, 1.5, 4.0, "T1=2.0x, SL=1.5x, T2=4.0x ATR"),
    "M5": BarrierModel("M5", 3.0, 1.5, 4.0, "T1=3.0x, SL=1.5x, T2=4.0x ATR"),
    "M6": BarrierModel("M6", 3.0, 2.0, 5.0, "T1=3.0x, SL=2.0x, T2=5.0x ATR"),
}


@dataclass(frozen=True)
class HorizonSpec:
    horizon_id: str
    duration_seconds: int
    name: str


PRE_AUTHORIZED_HORIZONS: dict[str, HorizonSpec] = {
    "15m": HorizonSpec("15m", 900, "15 Minutes"),
    "30m": HorizonSpec("30m", 1800, "30 Minutes"),
    "60m": HorizonSpec("60m", 3600, "60 Minutes"),
    "EOD": HorizonSpec("EOD", 21600, "End of Day (Same Session Close 15:30 IST)"),
    "Next Day": HorizonSpec("Next Day", 108000, "Next Trading Day Close"),
    "5 Days": HorizonSpec("5 Days", 432000, "Full 5 Trading Days"),
}

# Category-specific authorized evaluation horizons (E5.1 governance requirement)
CATEGORY_AUTHORIZED_HORIZONS: dict[str, list[str]] = {
    "EQUITY_SWING": ["EOD", "Next Day", "5 Days"],
    "EQUITY_SWING_DELIVERY": ["EOD", "Next Day", "5 Days"],
    "LARGE_CAP_EQUITY": ["EOD", "Next Day", "5 Days"],
    "MID_SMALL_CAP": ["EOD", "Next Day", "5 Days"],
    "STOCK_OPTIONS": ["15m", "30m", "60m", "EOD"],
    "INDEX_OPTIONS": ["60m"],
    "FUTURES": ["15m", "30m", "60m", "EOD"],
}


def is_horizon_authorized_for_category(category: str, horizon_id: str) -> bool:
    """Return whether the specified horizon is authorized for the given asset category."""
    cat_norm = str(category or "").strip().upper()
    auth_list = CATEGORY_AUTHORIZED_HORIZONS.get(cat_norm, ["15m", "30m", "60m", "EOD"])
    return horizon_id in auth_list


def compute_horizon_cutoff(
    candidate_dt: datetime.datetime,
    horizon_id: str,
    calendar_engine: ExchangeCalendarEngine | None = None,
) -> datetime.datetime:
    """Compute exact trading-session horizon cutoff timestamp.

    Enforces authentic trading-session semantics rather than raw elapsed seconds:
    - 15m, 30m, 60m: candidate_dt + timedelta(minutes=N), capped at same-day 15:30:00 IST.
    - EOD: Same trading day session close at 15:30:00 IST.
    - Next Day: Close of the next valid exchange trading day (skipping weekends & statutory holidays) at 15:30:00 IST.
    - 5 Days: Close of the 5th valid exchange trading day (skipping weekends & statutory holidays) at 15:30:00 IST.
    """
    engine = calendar_engine or ExchangeCalendarEngine()
    session_date = candidate_dt.date()
    same_day_close = datetime.datetime.combine(session_date, datetime.time(15, 30))
    if candidate_dt.tzinfo is not None:
        same_day_close = same_day_close.replace(tzinfo=candidate_dt.tzinfo)

    if horizon_id == "15m":
        cutoff = candidate_dt + datetime.timedelta(minutes=15)
        return min(cutoff, same_day_close)
    elif horizon_id == "30m":
        cutoff = candidate_dt + datetime.timedelta(minutes=30)
        return min(cutoff, same_day_close)
    elif horizon_id == "60m":
        cutoff = candidate_dt + datetime.timedelta(minutes=60)
        return min(cutoff, same_day_close)
    elif horizon_id == "EOD":
        return same_day_close
    elif horizon_id == "Next Day":
        curr = session_date + datetime.timedelta(days=1)
        while not engine.is_market_day(curr):
            curr += datetime.timedelta(days=1)
        cutoff = datetime.datetime.combine(curr, datetime.time(15, 30))
        if candidate_dt.tzinfo is not None:
            cutoff = cutoff.replace(tzinfo=candidate_dt.tzinfo)
        return cutoff
    elif horizon_id == "5 Days":
        curr = session_date
        added = 0
        while added < 5:
            curr += datetime.timedelta(days=1)
            if engine.is_market_day(curr):
                added += 1
        cutoff = datetime.datetime.combine(curr, datetime.time(15, 30))
        if candidate_dt.tzinfo is not None:
            cutoff = cutoff.replace(tzinfo=candidate_dt.tzinfo)
        return cutoff
    else:
        # Fallback for arbitrary horizons
        return candidate_dt + datetime.timedelta(hours=1)


def normalize_excursion_r(excursion_points: float | None, stop_distance: float) -> float | None:
    """Normalize excursion price points into R-multiples: R = Points / Stop_Distance."""
    if excursion_points is None or stop_distance <= 0:
        return None
    return round(excursion_points / stop_distance, 4)


def normalize_excursion_pct(excursion_points: float | None, entry_price: float) -> float | None:
    """Normalize excursion price points into percentage: Pct = Points / Entry_Price * 100."""
    if excursion_points is None or entry_price <= 0:
        return None
    return round((excursion_points / entry_price) * 100, 4)


VALID_SCORE_BUCKETS = ["95-100", "90-94", "85-89", "80-84", "75-79", "70-74"]


def classify_score_bucket(score: int) -> str:
    """Classify numerical score into authorized OPB score buckets."""
    if score >= 95:
        return "95-100"
    if score >= 90:
        return "90-94"
    if score >= 85:
        return "85-89"
    if score >= 80:
        return "80-84"
    if score >= 75:
        return "75-79"
    if score >= 70:
        return "70-74"
    return "BELOW_70"


# ==============================================================================
# 3. REPLAY CANDLE DATA STRUCTURE
# ==============================================================================

@dataclass(frozen=True)
class ReplayCandle:
    """Historical completed OHLCV candle for forward evaluation."""
    timestamp: str  # ISO-8601 string
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def parse_datetime(self) -> datetime.datetime:
        dt_str = self.timestamp.replace("Z", "+00:00")
        try:
            return datetime.datetime.fromisoformat(dt_str)
        except Exception:
            return datetime.datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S")


# ==============================================================================
# 4. CANDIDATE REPLAY EVALUATION RESULT DATA STRUCTURE
# ==============================================================================

@dataclass
class ReplayEvaluationResult:
    candidate_obs_id: str
    market_date: str
    cycle_id: str
    symbol: str
    direction: str
    category: str
    score: int
    entry_price: float
    atr: float | None
    model_id: str
    horizon: str
    target1_distance: float
    target2_distance: float
    stop_distance: float
    target1_price: float
    target2_price: float
    stop_price: float
    forward_data_complete: int  # 1 or 0
    terminal_status: str  # T1_ONLY, T2, SL, TIMEOUT, AMBIGUOUS, INSUFFICIENT_FORWARD_DATA
    first_touch_timestamp: str | None
    evaluation_end_timestamp: str | None
    mfe: float | None
    mae: float | None
    bars_evaluated: int
    ambiguous: int  # 1 or 0
    insufficient_forward_data: int  # 1 or 0

    def to_tuple(self) -> tuple[Any, ...]:
        return (
            self.candidate_obs_id,
            self.market_date,
            self.cycle_id,
            self.symbol,
            self.direction,
            self.category,
            self.score,
            self.entry_price,
            self.atr,
            self.model_id,
            self.horizon,
            self.target1_distance,
            self.target2_distance,
            self.stop_distance,
            self.target1_price,
            self.target2_price,
            self.stop_price,
            self.forward_data_complete,
            self.terminal_status,
            self.first_touch_timestamp,
            self.evaluation_end_timestamp,
            self.mfe,
            self.mae,
            self.bars_evaluated,
            self.ambiguous,
            self.insufficient_forward_data,
        )

    @property
    def mfe_r(self) -> float | None:
        """Maximum Favorable Excursion normalized by Stop Loss distance (R-multiples)."""
        if self.mfe is None or self.stop_distance <= 0:
            return None
        return round(self.mfe / self.stop_distance, 4)

    @property
    def mae_r(self) -> float | None:
        """Maximum Adverse Excursion normalized by Stop Loss distance (R-multiples)."""
        if self.mae is None or self.stop_distance <= 0:
            return None
        return round(self.mae / self.stop_distance, 4)

    @property
    def mfe_pct(self) -> float | None:
        """Maximum Favorable Excursion normalized by Entry Price (percentage)."""
        if self.mfe is None or self.entry_price <= 0:
            return None
        return round((self.mfe / self.entry_price) * 100, 4)

    @property
    def mae_pct(self) -> float | None:
        """Maximum Adverse Excursion normalized by Entry Price (percentage)."""
        if self.mae is None or self.entry_price <= 0:
            return None
        return round((self.mae / self.entry_price) * 100, 4)


# ==============================================================================
# 5. E5 REPLAY DATABASE MANAGER
# ==============================================================================

class E5DatabaseManager:
    """Thread-safe SQLite manager dedicated exclusively to db/e5_research_results.db."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        raw_path = Path(db_path) if db_path else DEFAULT_E5_DB_PATH
        self._db_path = validate_e5_db_path(raw_path)
        self._lock = threading.Lock()
        self._initialized = False
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            if self._initialized:
                return
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS e5_barrier_evaluation_results (
                        candidate_obs_id TEXT NOT NULL,
                        market_date TEXT NOT NULL,
                        cycle_id TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        category TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        entry_price REAL NOT NULL,
                        atr REAL,
                        model_id TEXT NOT NULL,
                        horizon TEXT NOT NULL,
                        target1_distance REAL NOT NULL,
                        target2_distance REAL NOT NULL,
                        stop_distance REAL NOT NULL,
                        target1_price REAL NOT NULL,
                        target2_price REAL NOT NULL,
                        stop_price REAL NOT NULL,
                        forward_data_complete INTEGER NOT NULL,
                        terminal_status TEXT NOT NULL,
                        first_touch_timestamp TEXT,
                        evaluation_end_timestamp TEXT,
                        mfe REAL,
                        mae REAL,
                        bars_evaluated INTEGER NOT NULL,
                        ambiguous INTEGER NOT NULL,
                        insufficient_forward_data INTEGER NOT NULL,
                        PRIMARY KEY (candidate_obs_id, model_id, horizon)
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_e5_model_hor ON e5_barrier_evaluation_results(model_id, horizon)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_e5_category ON e5_barrier_evaluation_results(category)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_e5_score ON e5_barrier_evaluation_results(score)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_e5_status ON e5_barrier_evaluation_results(terminal_status)")
                conn.commit()
                self._initialized = True
            finally:
                conn.close()

    def insert_results(self, results: list[ReplayEvaluationResult]) -> int:
        """Batch insert evaluation results with conflict replacement."""
        if not results:
            return 0
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.executemany("""
                    INSERT OR REPLACE INTO e5_barrier_evaluation_results (
                        candidate_obs_id, market_date, cycle_id, symbol, direction, category,
                        score, entry_price, atr, model_id, horizon, target1_distance,
                        target2_distance, stop_distance, target1_price, target2_price,
                        stop_price, forward_data_complete, terminal_status, first_touch_timestamp,
                        evaluation_end_timestamp, mfe, mae, bars_evaluated, ambiguous,
                        insufficient_forward_data
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [r.to_tuple() for r in results])
                conn.commit()
                return len(results)
            finally:
                conn.close()

    def get_row_count(self) -> int:
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM e5_barrier_evaluation_results")
            return cur.fetchone()[0]
        finally:
            conn.close()

    def clear_results(self) -> None:
        """Clear all rows from e5_barrier_evaluation_results table."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.cursor()
                cur.execute("DELETE FROM e5_barrier_evaluation_results")
                conn.commit()
            finally:
                conn.close()


# ==============================================================================
# 6. E5 HISTORICAL REPLAY ENGINE
# ==============================================================================

class E5ReplayEngine:
    """Core offline counterfactual historical candle replay engine."""

    def __init__(self, db_manager: E5DatabaseManager | None = None) -> None:
        self._db_manager = db_manager or E5DatabaseManager()

    @property
    def db_manager(self) -> E5DatabaseManager:
        return self._db_manager

    @staticmethod
    def calculate_directional_barriers(
        entry_price: float,
        atr: float,
        direction: str,
        model: BarrierModel,
    ) -> tuple[float, float, float, float, float, float]:
        """Compute directional barrier prices and absolute distances strictly from Point-A values.

        Returns:
            (target1_price, target2_price, stop_price, target1_distance, target2_distance, stop_distance)
        """
        is_long = direction.strip().upper() in ("BUY", "CALL", "LONG")

        t1_dist = round(model.t1_multiplier * atr, 4)
        t2_dist = round(model.t2_multiplier * atr, 4)
        sl_dist = round(model.sl_multiplier * atr, 4)

        if is_long:
            t1_price = round(entry_price + t1_dist, 2)
            t2_price = round(entry_price + t2_dist, 2)
            sl_price = round(entry_price - sl_dist, 2)
        else:
            t1_price = round(entry_price - t1_dist, 2)
            t2_price = round(entry_price - t2_dist, 2)
            sl_price = round(entry_price + sl_dist, 2)

        return t1_price, t2_price, sl_price, t1_dist, t2_dist, sl_dist

    @staticmethod
    def evaluate_candidate_forward_window(
        candidate_obs_id: str,
        market_date: str,
        cycle_id: str,
        symbol: str,
        direction: str,
        category: str,
        score: int,
        entry_price: float,
        atr: float | None,
        candidate_timestamp: str,
        candles: list[ReplayCandle],
        model: BarrierModel,
        horizon_spec: HorizonSpec,
        calendar_engine: ExchangeCalendarEngine | None = None,
    ) -> ReplayEvaluationResult:
        """Chronologically evaluate a single candidate observation under a specific model and horizon.

        Enforces:
        - Candidate-time barrier computation: strictly from candidate ATR and entry price.
        - Forward-window integrity: only candles with timestamp > candidate_timestamp are evaluated.
        - Same-candle ambiguity: breaches of both target and SL in the same bar are quarantined as AMBIGUOUS.
        - First-touch precedence: earliest barrier touch determines the terminal state.
        - MFE/MAE: computed exclusively from forward candles.
        - Missing/incomplete forward window: classified as INSUFFICIENT_FORWARD_DATA.
        """
        is_long = direction.strip().upper() in ("BUY", "CALL", "LONG")

        # ATR validation: if ATR is missing or non-positive, data is insufficient
        if atr is None or atr <= 0.0 or entry_price <= 0.0:
            return ReplayEvaluationResult(
                candidate_obs_id=candidate_obs_id,
                market_date=market_date,
                cycle_id=cycle_id,
                symbol=symbol,
                direction=direction,
                category=category,
                score=score,
                entry_price=entry_price,
                atr=atr,
                model_id=model.model_id,
                horizon=horizon_spec.horizon_id,
                target1_distance=0.0,
                target2_distance=0.0,
                stop_distance=0.0,
                target1_price=0.0,
                target2_price=0.0,
                stop_price=0.0,
                forward_data_complete=0,
                terminal_status="INSUFFICIENT_FORWARD_DATA",
                first_touch_timestamp=None,
                evaluation_end_timestamp=None,
                mfe=None,
                mae=None,
                bars_evaluated=0,
                ambiguous=0,
                insufficient_forward_data=1,
            )

        t1_price, t2_price, sl_price, t1_dist, t2_dist, sl_dist = (
            E5ReplayEngine.calculate_directional_barriers(entry_price, atr, direction, model)
        )

        cand_dt = None
        try:
            cand_dt = datetime.datetime.fromisoformat(candidate_timestamp.replace("Z", "+00:00"))
        except Exception:
            try:
                cand_dt = datetime.datetime.strptime(candidate_timestamp[:19], "%Y-%m-%dT%H:%M:%S")
            except Exception:
                pass

        if cand_dt is None:
            # Cannot establish chronological timeline
            return ReplayEvaluationResult(
                candidate_obs_id=candidate_obs_id,
                market_date=market_date,
                cycle_id=cycle_id,
                symbol=symbol,
                direction=direction,
                category=category,
                score=score,
                entry_price=entry_price,
                atr=atr,
                model_id=model.model_id,
                horizon=horizon_spec.horizon_id,
                target1_distance=t1_dist,
                target2_distance=t2_dist,
                stop_distance=sl_dist,
                target1_price=t1_price,
                target2_price=t2_price,
                stop_price=sl_price,
                forward_data_complete=0,
                terminal_status="INSUFFICIENT_FORWARD_DATA",
                first_touch_timestamp=None,
                evaluation_end_timestamp=None,
                mfe=None,
                mae=None,
                bars_evaluated=0,
                ambiguous=0,
                insufficient_forward_data=1,
            )

        # Horizon cutoff time computed via authentic exchange trading session calendar
        horizon_end_dt = compute_horizon_cutoff(cand_dt, horizon_spec.horizon_id, calendar_engine)

        # Filter candles strictly forward of candidate observation
        valid_forward_candles: list[tuple[datetime.datetime, ReplayCandle]] = []
        for c in candles:
            try:
                b_dt = c.parse_datetime()
                # Ensure timezone alignment
                if b_dt.tzinfo is None and cand_dt.tzinfo is not None:
                    b_dt = b_dt.replace(tzinfo=cand_dt.tzinfo)
                elif b_dt.tzinfo is not None and cand_dt.tzinfo is None:
                    b_dt = b_dt.replace(tzinfo=None)

                # Strict no-lookahead: bar must be strictly after candidate timestamp
                if b_dt > cand_dt:
                    valid_forward_candles.append((b_dt, c))
            except Exception:
                continue

        # Sort chronologically
        valid_forward_candles.sort(key=lambda x: x[0])

        if not valid_forward_candles:
            # Zero forward candles available
            return ReplayEvaluationResult(
                candidate_obs_id=candidate_obs_id,
                market_date=market_date,
                cycle_id=cycle_id,
                symbol=symbol,
                direction=direction,
                category=category,
                score=score,
                entry_price=entry_price,
                atr=atr,
                model_id=model.model_id,
                horizon=horizon_spec.horizon_id,
                target1_distance=t1_dist,
                target2_distance=t2_dist,
                stop_distance=sl_dist,
                target1_price=t1_price,
                target2_price=t2_price,
                stop_price=sl_price,
                forward_data_complete=0,
                terminal_status="INSUFFICIENT_FORWARD_DATA",
                first_touch_timestamp=None,
                evaluation_end_timestamp=None,
                mfe=None,
                mae=None,
                bars_evaluated=0,
                ambiguous=0,
                insufficient_forward_data=1,
            )

        # Check forward window coverage:
        # A window is complete if candles reach or exceed the horizon cutoff, OR if terminal barrier was reached
        last_available_bar_dt = valid_forward_candles[-1][0]
        window_reached_horizon = last_available_bar_dt >= horizon_end_dt

        # Evaluate chronologically
        first_touch_status: str | None = None
        first_touch_ts: str | None = None
        terminal_status: str | None = None
        evaluation_end_ts: str | None = None
        bars_evaluated = 0

        max_favorable_excursion = 0.0
        max_adverse_excursion = 0.0

        hit_t1_prior = False

        for b_dt, bar in valid_forward_candles:
            # If bar is beyond the evaluation horizon, stop evaluating
            if b_dt > horizon_end_dt:
                break

            bars_evaluated += 1
            evaluation_end_ts = bar.timestamp

            # Progressive MFE / MAE computation
            if is_long:
                favorable = max(0.0, bar.high - entry_price)
                adverse = max(0.0, entry_price - bar.low)
                hit_t1 = bar.high >= t1_price
                hit_t2 = bar.high >= t2_price
                hit_sl = bar.low <= sl_price
            else:
                favorable = max(0.0, entry_price - bar.low)
                adverse = max(0.0, bar.high - entry_price)
                hit_t1 = bar.low <= t1_price
                hit_t2 = bar.low <= t2_price
                hit_sl = bar.high >= sl_price

            max_favorable_excursion = max(max_favorable_excursion, favorable)
            max_adverse_excursion = max(max_adverse_excursion, adverse)

            # Check barrier conditions
            if not hit_t1_prior:
                # Neither barrier reached prior to this bar
                # SAME-CANDLE CONFLICT: Both Target (T1 or T2) and SL breached in the same bar
                if hit_sl and (hit_t1 or hit_t2):
                    terminal_status = "AMBIGUOUS"
                    first_touch_status = "AMBIGUOUS"
                    first_touch_ts = bar.timestamp
                    break
                elif hit_sl:
                    terminal_status = "SL"
                    first_touch_status = "SL"
                    first_touch_ts = bar.timestamp
                    break
                elif hit_t1:
                    hit_t1_prior = True
                    first_touch_status = "T1"
                    first_touch_ts = bar.timestamp
                    # If T2 also hit in this candle without SL
                    if hit_t2:
                        terminal_status = "T2"
                        break
            else:
                # T1 was already hit in a prior bar without SL
                # Check subsequent bar for T2 or SL
                if hit_sl and hit_t2:
                    # Same candle conflict between T2 and SL
                    terminal_status = "AMBIGUOUS"
                    break
                elif hit_sl:
                    # Stopped out after T1: Per OPB barrier semantics, T1-only is credited once reached
                    terminal_status = "T1_ONLY"
                    break
                elif hit_t2:
                    terminal_status = "T2"
                    break

        # Terminal state resolution after iterating bars
        if terminal_status is None:
            if hit_t1_prior:
                # T1 reached, horizon elapsed without hitting T2 or SL
                terminal_status = "T1_ONLY"
            elif window_reached_horizon:
                # Fully elapsed horizon with zero barrier touches
                terminal_status = "TIMEOUT"
            else:
                # Forward window did not reach horizon and no barrier touched
                terminal_status = "INSUFFICIENT_FORWARD_DATA"

        forward_complete = 1 if (terminal_status in ("T1_ONLY", "T2", "SL", "AMBIGUOUS") or window_reached_horizon) else 0
        is_ambiguous = 1 if terminal_status == "AMBIGUOUS" else 0
        is_insufficient = 1 if terminal_status == "INSUFFICIENT_FORWARD_DATA" else 0
        # MFE / MAE semantics (E5.1 requirement):
        # Incomplete forward windows must NOT report placeholder zeros.
        # If terminal_status is INSUFFICIENT_FORWARD_DATA or bars_evaluated == 0,
        # mfe and mae must be None (SQL NULL).
        has_valid_window = (terminal_status != "INSUFFICIENT_FORWARD_DATA" and bars_evaluated > 0)
        final_mfe = round(max_favorable_excursion, 4) if has_valid_window else None
        final_mae = round(max_adverse_excursion, 4) if has_valid_window else None

        return ReplayEvaluationResult(
            candidate_obs_id=candidate_obs_id,
            market_date=market_date,
            cycle_id=cycle_id,
            symbol=symbol,
            direction=direction,
            category=category,
            score=score,
            entry_price=entry_price,
            atr=atr,
            model_id=model.model_id,
            horizon=horizon_spec.horizon_id,
            target1_distance=t1_dist,
            target2_distance=t2_dist,
            stop_distance=sl_dist,
            target1_price=t1_price,
            target2_price=t2_price,
            stop_price=sl_price,
            forward_data_complete=forward_complete,
            terminal_status=terminal_status,
            first_touch_timestamp=first_touch_ts,
            evaluation_end_timestamp=evaluation_end_ts,
            mfe=final_mfe,
            mae=final_mae,
            bars_evaluated=bars_evaluated,
            ambiguous=is_ambiguous,
            insufficient_forward_data=is_insufficient,
        )

    def execute_replay_matrix(
        self,
        candidates: list[dict[str, Any]],
        symbol_candles_map: dict[str, list[ReplayCandle]],
        models: list[BarrierModel] | None = None,
        horizons: list[HorizonSpec] | None = None,
        enforce_category_horizons: bool = True,
        calendar_engine: ExchangeCalendarEngine | None = None,
    ) -> list[ReplayEvaluationResult]:
        """Execute exhaustive Model × Horizon replay across all provided candidates."""
        models_to_eval = models or list(PRE_AUTHORIZED_MODELS.values())
        horizons_to_eval = horizons or list(PRE_AUTHORIZED_HORIZONS.values())

        all_results: list[ReplayEvaluationResult] = []

        for cand in candidates:
            c_obs_id = cand["candidate_obs_id"]
            m_date = cand["market_date"]
            cyc_id = cand["cycle_id"]
            sym = cand["symbol"]
            direction = cand["direction"]
            cat = cand["category"]
            score = int(cand["score"])
            entry = float(cand["entry_price"])
            atr = float(cand["atr"]) if cand.get("atr") is not None else None
            ts_str = str(cand["candidate_timestamp"])

            candles = symbol_candles_map.get(sym, [])

            # Category constraint enforcement (E5.1 governance requirement):
            if enforce_category_horizons:
                authorized_h_ids = CATEGORY_AUTHORIZED_HORIZONS.get(cat.upper(), ["15m", "30m", "60m", "EOD"])
                cand_horizons = [h for h in horizons_to_eval if h.horizon_id in authorized_h_ids]
            else:
                cand_horizons = horizons_to_eval

            for model in models_to_eval:
                for horizon in cand_horizons:
                    res = self.evaluate_candidate_forward_window(
                        candidate_obs_id=c_obs_id,
                        market_date=m_date,
                        cycle_id=cyc_id,
                        symbol=sym,
                        direction=direction,
                        category=cat,
                        score=score,
                        entry_price=entry,
                        atr=atr,
                        candidate_timestamp=ts_str,
                        candles=candles,
                        model=model,
                        horizon_spec=horizon,
                        calendar_engine=calendar_engine,
                    )
                    all_results.append(res)

        # Persist to isolated research database
        self._db_manager.insert_results(all_results)
        return all_results

    def compute_aggregations(self) -> dict[str, Any]:
        """Compute exhaustive aggregations required by E5 specification from db/e5_research_results.db."""
        conn = self._db_manager._get_connection()
        try:
            cur = conn.cursor()

            # 1. Model x Horizon Aggregations
            cur.execute("""
                SELECT
                    model_id,
                    horizon,
                    COUNT(*) as total_eligible,
                    SUM(forward_data_complete) as complete_window,
                    SUM(insufficient_forward_data) as insufficient_data,
                    SUM(CASE WHEN terminal_status = 'T1_ONLY' THEN 1 ELSE 0 END) as t1_only_count,
                    SUM(CASE WHEN terminal_status = 'T2' THEN 1 ELSE 0 END) as t2_count,
                    SUM(CASE WHEN terminal_status IN ('T1_ONLY', 'T2') THEN 1 ELSE 0 END) as t1_or_better_count,
                    SUM(CASE WHEN terminal_status = 'SL' THEN 1 ELSE 0 END) as sl_count,
                    SUM(CASE WHEN terminal_status = 'TIMEOUT' THEN 1 ELSE 0 END) as timeout_count,
                    SUM(CASE WHEN terminal_status = 'AMBIGUOUS' THEN 1 ELSE 0 END) as ambiguous_count,
                    SUM(CASE WHEN terminal_status IN ('T1_ONLY', 'T2', 'SL', 'AMBIGUOUS') THEN 1 ELSE 0 END) as resolved_count,
                    AVG(CASE WHEN forward_data_complete = 1 AND terminal_status != 'INSUFFICIENT_FORWARD_DATA' THEN mfe ELSE NULL END) as mean_mfe,
                    AVG(CASE WHEN forward_data_complete = 1 AND terminal_status != 'INSUFFICIENT_FORWARD_DATA' THEN mae ELSE NULL END) as mean_mae
                FROM e5_barrier_evaluation_results
                GROUP BY model_id, horizon
                ORDER BY model_id, horizon
            """)
            mh_rows = [dict(r) for r in cur.fetchall()]

            # Compute median MFE/MAE per model x horizon strictly on complete windows
            for row in mh_rows:
                m_id = row["model_id"]
                h_id = row["horizon"]
                cur.execute(
                    """
                    SELECT mfe, mae, stop_distance
                    FROM e5_barrier_evaluation_results
                    WHERE model_id = ?
                      AND horizon = ?
                      AND forward_data_complete = 1
                      AND terminal_status != 'INSUFFICIENT_FORWARD_DATA'
                      AND mfe IS NOT NULL
                    ORDER BY mfe
                    """,
                    (m_id, h_id),
                )
                complete_rows = cur.fetchall()
                mfe_vals = [r[0] for r in complete_rows if r[0] is not None]
                mae_vals = [r[1] for r in complete_rows if r[1] is not None]
                mfe_r_vals = [r[0] / r[2] for r in complete_rows if r[0] is not None and r[2] > 0]
                mae_r_vals = [r[1] / r[2] for r in complete_rows if r[1] is not None and r[2] > 0]

                import statistics
                row["median_mfe"] = round(statistics.median(mfe_vals), 4) if mfe_vals else None
                row["median_mae"] = round(statistics.median(mae_vals), 4) if mae_vals else None
                row["median_mfe_r"] = round(statistics.median(mfe_r_vals), 4) if mfe_r_vals else None
                row["median_mae_r"] = round(statistics.median(mae_r_vals), 4) if mae_r_vals else None

                resolved = row["resolved_count"]
                complete = row["complete_window"]
                total = row["total_eligible"]

                row["resolution_rate"] = round(resolved / complete * 100, 2) if complete > 0 else 0.0
                row["t1_or_better_rate_resolved"] = round(row["t1_or_better_count"] / resolved * 100, 2) if resolved > 0 else 0.0
                row["sl_rate_resolved"] = round(row["sl_count"] / resolved * 100, 2) if resolved > 0 else 0.0
                row["timeout_rate"] = round(row["timeout_count"] / complete * 100, 2) if complete > 0 else 0.0

            # 2. Category Breakdown
            cur.execute("""
                SELECT
                    category,
                    model_id,
                    horizon,
                    COUNT(*) as total_eligible,
                    SUM(CASE WHEN terminal_status = 'T1_ONLY' THEN 1 ELSE 0 END) as t1_only_count,
                    SUM(CASE WHEN terminal_status = 'T2' THEN 1 ELSE 0 END) as t2_count,
                    SUM(CASE WHEN terminal_status IN ('T1_ONLY', 'T2') THEN 1 ELSE 0 END) as t1_or_better_count,
                    SUM(CASE WHEN terminal_status = 'SL' THEN 1 ELSE 0 END) as sl_count,
                    SUM(CASE WHEN terminal_status = 'TIMEOUT' THEN 1 ELSE 0 END) as timeout_count,
                    SUM(CASE WHEN terminal_status = 'AMBIGUOUS' THEN 1 ELSE 0 END) as ambiguous_count,
                    SUM(insufficient_forward_data) as insufficient_data,
                    SUM(CASE WHEN terminal_status IN ('T1_ONLY', 'T2', 'SL', 'AMBIGUOUS') THEN 1 ELSE 0 END) as resolved_count
                FROM e5_barrier_evaluation_results
                GROUP BY category, model_id, horizon
                ORDER BY category, model_id, horizon
            """)
            cat_rows = [dict(r) for r in cur.fetchall()]
            for r in cat_rows:
                res = r["resolved_count"]
                tot = r["total_eligible"]
                r["resolution_rate"] = round(res / tot * 100, 2) if tot > 0 else 0.0

            # 3. Score Bucket Breakdown
            # Fetch all rows with score to bucket in python
            cur.execute("""
                SELECT
                    score,
                    model_id,
                    horizon,
                    terminal_status,
                    insufficient_forward_data
                FROM e5_barrier_evaluation_results
            """)
            score_rows = cur.fetchall()
            bucket_map: dict[tuple[str, str, str], dict[str, int]] = {}

            for s_val, m_id, h_id, term_stat, is_insuf in score_rows:
                s_b = classify_score_bucket(s_val)
                key = (s_b, m_id, h_id)
                if key not in bucket_map:
                    bucket_map[key] = {
                        "score_bucket": s_b,
                        "model_id": m_id,
                        "horizon": h_id,
                        "total": 0,
                        "t1_or_better": 0,
                        "sl": 0,
                        "timeout": 0,
                        "ambiguous": 0,
                        "insufficient": 0,
                        "resolved": 0,
                    }
                entry = bucket_map[key]
                entry["total"] += 1
                if is_insuf:
                    entry["insufficient"] += 1
                if term_stat in ("T1_ONLY", "T2"):
                    entry["t1_or_better"] += 1
                    entry["resolved"] += 1
                elif term_stat == "SL":
                    entry["sl"] += 1
                    entry["resolved"] += 1
                elif term_stat == "AMBIGUOUS":
                    entry["ambiguous"] += 1
                    entry["resolved"] += 1
                elif term_stat == "TIMEOUT":
                    entry["timeout"] += 1

            score_bucket_results = list(bucket_map.values())
            for sb in score_bucket_results:
                tot = sb["total"]
                res = sb["resolved"]
                sb["resolution_rate"] = round(res / tot * 100, 2) if tot > 0 else 0.0

            return {
                "model_horizon_matrix": mh_rows,
                "category_breakdown": cat_rows,
                "score_bucket_breakdown": score_bucket_results,
            }
        finally:
            conn.close()
