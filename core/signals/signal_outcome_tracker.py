"""Signal Outcome Tracker & Real-Time Win Rate Observational Engine (Phase 2.1).

Observational analytics subsystem consuming persisted signals and market data.
Tracks, evaluates, and records real-market outcomes (Target 1, Target 2, Stop Loss,
Ambiguous Same-Bar, Expired, Unresolved) for all generated signals independently of
whether they were converted to paper trades.

Strict Governance Invariants:
- Zero mutations to signal generation, scoring, thresholds, entry price, SL, targets,
  scanner universe, permissions, or broker execution logic.
- First-Touch Immutability: first_touch, first_touch_at, and outcome_confidence are
  write-once historical truth.
- Same-Candle Ambiguity Quarantining: When a bar crosses both T1 and SL, it is
  mathematically quarantined. Intrabar ordering is never assumed from OHLC data.
- Calendar & Session Edge-Cases: Weekends and exchange holidays are skipped. Signals
  generated within 15 minutes of market close receive a 1-session grace period.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.exchange_calendar_engine import ExchangeCalendarEngine

_log = logging.getLogger("SIGNAL_OUTCOME_TRACKER")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _ROOT / "db" / "signals_history.db"

MARKET_CLOSE_TIME = datetime.time(15, 30)
NEAR_CLOSE_THRESHOLD_TIME = datetime.time(15, 15)


class OutcomeState(str, Enum):
    """Discrete lifecycle states of a trade signal."""

    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    TARGET_1_HIT = "TARGET_1_HIT"
    TARGET_2_HIT = "TARGET_2_HIT"
    SL_HIT = "SL_HIT"
    AMBIGUOUS = "AMBIGUOUS"
    AMBIGUOUS_SAME_BAR = "AMBIGUOUS_SAME_BAR"
    EXPIRED = "EXPIRED"
    UNRESOLVED = "UNRESOLVED"


class OutcomeConfidence(str, Enum):
    """Confidence categorization of outcome evaluation."""

    EXACT_OBSERVATION = "EXACT_OBSERVATION"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"
    POLLING = "POLLING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SignalBar:
    """Standard OHLCV price bar for bar-level outcome evaluation."""

    open: float
    high: float
    low: float
    close: float
    timestamp: datetime.datetime | str
    volume: float = 0.0


@dataclass
class SignalEvaluationResult:
    """Result of an outcome evaluation tick or bar."""

    signal_id: str
    symbol: str
    new_status: str | None
    first_touch: str | None
    first_touch_at: str | None
    outcome_confidence: str
    current_price: float
    pnl_pct: float
    is_terminal: bool
    event_logged: bool
    hit_sl: bool
    hit_t1: bool
    hit_t2: bool
    first_touch_price: float = 0.0
    transition_note: str = ""


class SignalOutcomeTracker:
    """Observational subsystem for tracking and evaluating real-market signal outcomes."""

    _instances: dict[Path, SignalOutcomeTracker] = {}
    _instance: SignalOutcomeTracker | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        db_path: Path | str | None = None,
        calendar_engine: ExchangeCalendarEngine | None = None,
    ) -> None:
        self._db_path = Path(db_path) if db_path is not None else _DEFAULT_DB_PATH
        self._calendar_engine = calendar_engine or ExchangeCalendarEngine()
        self._io_lock = threading.Lock()
        self._last_sweep_ts: float = 0.0
        self._sweep_min_interval: float = 60.0
        self._ensure_schema()

    @classmethod
    def get_instance(
        cls,
        db_path: Path | str | None = None,
        calendar_engine: ExchangeCalendarEngine | None = None,
    ) -> SignalOutcomeTracker:
        target_path = Path(db_path or _DEFAULT_DB_PATH).resolve()
        with cls._lock:
            if target_path not in cls._instances:
                cls._instances[target_path] = cls(db_path=target_path, calendar_engine=calendar_engine)
            inst = cls._instances[target_path]
            cls._instance = inst
            return inst

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            cls._instances.clear()
            cls._instance = None

    def _get_conn(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Ensure outcome tracking tables and columns exist in signals_history.db."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signal_outcome_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        signal_id TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        observed_price REAL NOT NULL,
                        hit_sl INTEGER NOT NULL DEFAULT 0,
                        hit_t1 INTEGER NOT NULL DEFAULT 0,
                        hit_t2 INTEGER NOT NULL DEFAULT 0,
                        transition_note TEXT DEFAULT '',
                        FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_deliveries (
                        delivery_id TEXT PRIMARY KEY,
                        signal_id TEXT NOT NULL,
                        username TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        delivery_date TEXT NOT NULL,
                        delivery_week TEXT NOT NULL,
                        delivery_month TEXT NOT NULL,
                        delivery_year TEXT NOT NULL,
                        symbol TEXT NOT NULL,
                        company_name TEXT,
                        category TEXT NOT NULL,
                        direction TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        tier TEXT NOT NULL,
                        entry_price REAL NOT NULL,
                        stop_loss REAL NOT NULL,
                        target_1 REAL NOT NULL,
                        target_2 REAL NOT NULL,
                        current_price REAL NOT NULL,
                        status TEXT NOT NULL,
                        pnl_pct REAL NOT NULL,
                        channels_sent TEXT NOT NULL
                    )
                """)
                # Migrations for transition_note
                try:
                    cur.execute("ALTER TABLE signal_outcome_events ADD COLUMN transition_note TEXT DEFAULT ''")
                except sqlite3.OperationalError:
                    pass

                for col, col_type in (
                    ("first_touch", "TEXT DEFAULT ''"),
                    ("first_touch_at", "TEXT DEFAULT ''"),
                    ("first_touch_price", "REAL DEFAULT 0.0"),
                    ("outcome_confidence", "TEXT DEFAULT 'UNKNOWN'"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE system_signals ADD COLUMN {col} {col_type}")
                    except sqlite3.OperationalError:
                        pass
                conn.commit()
            except Exception as ex:
                _log.error("Failed to ensure outcome tracker schema: %s", ex)
            finally:
                conn.close()

    def evaluate_bar(
        self,
        signal: dict[str, Any],
        bar: SignalBar,
        current_time: datetime.datetime | None = None,
        check_staleness: bool = False,
    ) -> SignalEvaluationResult:
        """Evaluate a signal against an OHLC price bar.

        Enforces:
        - Same-candle ambiguity: If both T1 and SL are touched in the same bar,
          never assume intrabar sequence. Quarantines as AMBIGUOUS_SAME_BAR.
        - First-touch immutability: Once first_touch is recorded, it is never overwritten.
        - Stale/invalid data safety: Returns no-op if bar data is invalid or stale (>15m when check_staleness is True).
        - Calendar awareness: Respects weekends, holidays, and near-close grace periods.
        """
        now = current_time or now_ist()
        now_str = now.isoformat()

        sig_id = str(signal.get("signal_id", ""))
        symbol = str(signal.get("symbol", ""))
        direction = str(signal.get("direction", "CALL")).upper()
        current_status = str(signal.get("status", "ACTIVE")).upper()
        existing_first_touch = str(signal.get("first_touch") or "").strip()
        existing_first_touch_at = str(signal.get("first_touch_at") or "").strip()
        existing_first_touch_price = float(signal.get("first_touch_price") or 0.0)
        existing_confidence = str(signal.get("outcome_confidence") or "UNKNOWN").strip()
        created_date_str = str(signal.get("created_date") or "").strip()
        category = str(signal.get("category") or "").upper()

        entry = float(signal.get("entry_price") or 0.0)
        sl = float(signal.get("stop_loss") or 0.0)
        t1 = float(signal.get("target_1") or 0.0)
        t2 = float(signal.get("target_2") or 0.0)

        # Baseline fallback result (no state change)
        current_price = float(signal.get("current_price") or entry)
        pnl_pct = float(signal.get("pnl_pct") or 0.0)
        no_op_result = SignalEvaluationResult(
            signal_id=sig_id,
            symbol=symbol,
            new_status=None,
            first_touch=existing_first_touch or None,
            first_touch_at=existing_first_touch_at or None,
            first_touch_price=existing_first_touch_price,
            outcome_confidence=existing_confidence,
            current_price=current_price,
            pnl_pct=pnl_pct,
            is_terminal=existing_first_touch in ("SL", "AMBIGUOUS", "EXPIRED", "AMBIGUOUS_SAME_BAR"),
            event_logged=False,
            hit_sl=False,
            hit_t1=False,
            hit_t2=False,
            transition_note="No change or invalid data",
        )

        # 1. Price validation: entry, sl, t1 must be strictly positive
        if entry <= 0 or sl <= 0 or t1 <= 0:
            return no_op_result

        # Bar validation: high >= low, prices > 0
        if bar.high < bar.low or bar.open <= 0 or bar.close <= 0 or bar.high <= 0 or bar.low <= 0:
            return no_op_result

        # Stale bar validation: if bar timestamp is older than 15m from evaluation time
        if check_staleness:
            bar_dt = bar.timestamp
            if isinstance(bar_dt, str):
                try:
                    bar_dt = datetime.datetime.fromisoformat(bar_dt)
                except Exception:
                    bar_dt = None
            if isinstance(bar_dt, datetime.datetime):
                if bar_dt.tzinfo is None and now.tzinfo is not None:
                    bar_dt = bar_dt.replace(tzinfo=now.tzinfo)
                if (now - bar_dt).total_seconds() > 900:  # > 15 minutes
                    _log.debug("Stale bar rejected for %s (age > 15m)", symbol)
                    return no_op_result

        # Determine price barrier hits based on direction
        is_call = direction in ("CALL", "BUY", "LONG")
        if is_call:
            hit_sl = bar.low <= sl
            hit_t1 = bar.high >= t1
            hit_t2 = bar.high >= t2 if t2 > 0 else False
            bar_pnl = round((bar.close - entry) / entry * 100, 2)
        else:
            hit_sl = bar.high >= sl
            hit_t1 = bar.low <= t1
            hit_t2 = bar.low <= t2 if t2 > 0 else False
            bar_pnl = round((entry - bar.close) / entry * 100, 2)

        # 2. Check Expiration on weekends / holidays / market close
        today_date = now.date()
        is_trading_day = self._calendar_engine.is_market_day(today_date)

        # Intraday options vs swing holding
        is_intraday = ("OPTION" in category) or ("0DTE" in category) or ("INTRADAY" in category)

        new_status = None
        new_first_touch = existing_first_touch
        new_first_touch_at = existing_first_touch_at
        new_first_touch_price = existing_first_touch_price
        new_confidence = existing_confidence
        transition_note = ""

        # 3. State Machine Transitions
        if not existing_first_touch:
            # Signal is currently OPEN / ACTIVE without prior barrier touch
            # SAME-CANDLE AMBIGUITY: Both Target (T1 or T2) and SL hit in the same bar!
            if hit_sl and (hit_t1 or hit_t2):
                new_status = "AMBIGUOUS"
                new_first_touch = "AMBIGUOUS_SAME_BAR"
                new_first_touch_at = now_str
                new_first_touch_price = bar.close
                new_confidence = OutcomeConfidence.AMBIGUOUS.value
                transition_note = f"Both Target and SL ({sl}) touched in same candle [{bar.low} - {bar.high}]. Quarantined as Ambiguous."
            elif hit_t2:
                new_status = "TARGET_2_HIT"
                new_first_touch = "T1" if hit_t1 else "T2"
                new_first_touch_at = now_str
                new_first_touch_price = t1 if hit_t1 else t2
                new_confidence = OutcomeConfidence.EXACT_OBSERVATION.value
                transition_note = f"Target 2 hit at bar high/low {bar.high if is_call else bar.low}"
            elif hit_t1:
                new_status = "TARGET_1_HIT"
                new_first_touch = "T1"
                new_first_touch_at = now_str
                new_first_touch_price = t1
                new_confidence = OutcomeConfidence.EXACT_OBSERVATION.value
                transition_note = f"Target 1 hit at bar high/low {bar.high if is_call else bar.low}"
            elif hit_sl:
                new_status = "SL_HIT"
                new_first_touch = "SL"
                new_first_touch_at = now_str
                new_first_touch_price = sl
                new_confidence = OutcomeConfidence.EXACT_OBSERVATION.value
                transition_note = f"Stop loss hit at bar low/high {bar.low if is_call else bar.high}"
            else:
                # No barrier hit in this bar. Check if signal has reached horizon expiry.
                created_d = None
                if created_date_str:
                    try:
                        created_d = datetime.date.fromisoformat(created_date_str[:10])
                    except Exception:
                        pass
                if created_d is None and signal.get("timestamp"):
                    try:
                        created_d = datetime.date.fromisoformat(str(signal["timestamp"])[:10])
                    except Exception:
                        pass
                if created_d is None:
                    created_d = today_date

                # Near-close grace period:
                # If signal was generated today after 15:15 IST, it receives a 1-session grace
                # period and is not expired today at 15:30 IST.
                sig_ts_raw = str(signal.get("timestamp") or "")
                near_close_created = False
                if sig_ts_raw:
                    try:
                        # parse HH:MM
                        time_part = sig_ts_raw.split(" ")[-1].split("T")[-1]
                        h, m = int(time_part[:2]), int(time_part[3:5])
                        if datetime.time(h, m) >= NEAR_CLOSE_THRESHOLD_TIME:
                            near_close_created = True
                    except Exception:
                        pass

                # Intraday expiration check (suppressed on weekends and holidays)
                if not is_trading_day:
                    pass
                elif is_intraday:
                    if created_d < today_date:
                        # From a previous calendar day -> Expired
                        new_status = "EXPIRED"
                        new_first_touch = "EXPIRED"
                        new_first_touch_at = now_str
                        new_first_touch_price = bar.close
                        new_confidence = OutcomeConfidence.UNRESOLVED.value
                        transition_note = f"Intraday signal expired (created {created_date_str}, current {today_date})"
                    elif created_d == today_date and now.time() >= MARKET_CLOSE_TIME and not near_close_created:
                        # Created today before 15:15, and now market is closed (>= 15:30)
                        new_status = "EXPIRED"
                        new_first_touch = "EXPIRED"
                        new_first_touch_at = now_str
                        new_first_touch_price = bar.close
                        new_confidence = OutcomeConfidence.UNRESOLVED.value
                        transition_note = "Intraday signal expired at session close (15:30 IST)"
                else:
                    # Swing / Delivery: expires after 5 trading days without touching T1 or SL
                    trading_days_elapsed = self._count_trading_days(created_d, today_date)
                    if trading_days_elapsed >= 5:
                        new_status = "EXPIRED"
                        new_first_touch = "EXPIRED"
                        new_first_touch_at = now_str
                        new_first_touch_price = bar.close
                        new_confidence = OutcomeConfidence.UNRESOLVED.value
                        transition_note = f"Swing signal expired after {trading_days_elapsed} trading days"
        else:
            # FIRST-TOUCH IMMUTABILITY: first_touch, first_touch_at, first_touch_price are write-once historical truth.
            new_first_touch_price = existing_first_touch_price
            if existing_first_touch == "T1" and current_status == "TARGET_1_HIT":
                if hit_t2 and not hit_sl:
                    new_status = "TARGET_2_HIT"
                    transition_note = "Target 2 reached following initial T1 hit"
                elif hit_sl:
                    new_status = "SL_HIT"
                    transition_note = "Stop loss hit following initial T1 hit (Lifecycle progression recorded)"
                else:
                    # Horizon expiry check after initial T1 hit
                    created_d = None
                    if created_date_str:
                        try:
                            created_d = datetime.date.fromisoformat(created_date_str[:10])
                        except Exception:
                            pass
                    if created_d is None and signal.get("timestamp"):
                        try:
                            created_d = datetime.date.fromisoformat(str(signal["timestamp"])[:10])
                        except Exception:
                            pass
                    if created_d is None:
                        created_d = today_date

                    sig_ts_raw = str(signal.get("timestamp") or "")
                    near_close_created = False
                    if sig_ts_raw:
                        try:
                            time_part = sig_ts_raw.split(" ")[-1].split("T")[-1]
                            h, m = int(time_part[:2]), int(time_part[3:5])
                            if datetime.time(h, m) >= NEAR_CLOSE_THRESHOLD_TIME:
                                near_close_created = True
                        except Exception:
                            pass

                    if is_intraday:
                        if created_d < today_date or (created_d == today_date and is_trading_day and now.time() >= MARKET_CLOSE_TIME and not near_close_created):
                            new_status = "EXPIRED"
                            transition_note = "Intraday signal expired after hitting T1 (first_touch preserved)"
                    else:
                        trading_days_elapsed = self._count_trading_days(created_d, today_date)
                        if trading_days_elapsed >= 5:
                            new_status = "EXPIRED"
                            transition_note = f"Swing signal expired after {trading_days_elapsed} trading days (first_touch preserved)"
            elif existing_first_touch in ("SL", "AMBIGUOUS", "EXPIRED", "AMBIGUOUS_SAME_BAR"):
                # Terminal states remain unchanged
                new_status = current_status

        is_terminal = (new_status in ("SL_HIT", "AMBIGUOUS", "EXPIRED", "TARGET_2_HIT")) or (
            new_first_touch in ("SL", "AMBIGUOUS", "EXPIRED", "AMBIGUOUS_SAME_BAR")
        )

        return SignalEvaluationResult(
            signal_id=sig_id,
            symbol=symbol,
            new_status=new_status,
            first_touch=new_first_touch or None,
            first_touch_at=new_first_touch_at or None,
            first_touch_price=new_first_touch_price,
            outcome_confidence=new_confidence,
            current_price=bar.close,
            pnl_pct=bar_pnl,
            is_terminal=is_terminal,
            event_logged=False,
            hit_sl=hit_sl,
            hit_t1=hit_t1,
            hit_t2=hit_t2,
            transition_note=transition_note,
        )

    def evaluate_tick(
        self,
        signal: dict[str, Any],
        price: float,
        timestamp: datetime.datetime | str | None = None,
        current_time: datetime.datetime | None = None,
    ) -> SignalEvaluationResult:
        """Evaluate a signal against a single LTP tick.

        Equivalent to evaluating a bar where open = high = low = close = price.
        Also maintains backward compatibility for simultaneous multi-barrier polling checks.
        """
        now = current_time or now_ist()
        ts = timestamp or now
        bar = SignalBar(
            open=price,
            high=price,
            low=price,
            close=price,
            timestamp=ts,
            volume=0.0,
        )
        return self.evaluate_bar(signal, bar, current_time=now)

    def _count_trading_days(self, start_date: datetime.date, end_date: datetime.date) -> int:
        """Count actual exchange trading days between start_date and end_date (inclusive)."""
        if start_date >= end_date:
            return 0
        cur = start_date + datetime.timedelta(days=1)
        count = 0
        while cur <= end_date:
            if self._calendar_engine.is_market_day(cur):
                count += 1
            cur += datetime.timedelta(days=1)
        return count

    def update_active_signal_outcomes(
        self,
        price_lookup_fn: Callable[[str], float | None],
        bar_lookup_fn: Callable[[str], SignalBar | None] | None = None,
    ) -> dict[str, int]:
        """Grade all non-terminal signals against live market price action.

        Thread-safe execution writing to SQLite `system_signals`, `user_deliveries`,
        and append-only `signal_outcome_events`.
        """
        checked = resolved = expired = 0
        now = now_ist()
        now_str = now.isoformat()

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """SELECT * FROM system_signals
                       WHERE status IN (
                           'ACTIVE',
                           'OPEN',
                           'TARGET_1_HIT',
                           'TARGET_2_HIT',
                           'SL_HIT',
                           'AMBIGUOUS'
                       )"""
                )
                active_rows = [dict(r) for r in cur.fetchall()]

                for row in active_rows:
                    checked += 1
                    symbol = row["symbol"]

                    # Lookup price / bar
                    eval_result: SignalEvaluationResult | None = None
                    if bar_lookup_fn is not None:
                        try:
                            bar = bar_lookup_fn(symbol)
                            if bar is not None:
                                eval_result = self.evaluate_bar(row, bar, current_time=now)
                        except Exception as ex:
                            _log.debug("Bar lookup failed for %s: %s", symbol, ex)

                    if eval_result is None:
                        try:
                            price = price_lookup_fn(symbol)
                        except Exception as ex:
                            _log.debug("Price lookup failed for %s: %s", symbol, ex)
                            price = None

                        if price is None or price <= 0:
                            # RCA Fix: Do not skip horizon evaluation when price is None or off-market!
                            expiry_check = self.check_signal_expiry(row, current_time=now)
                            if expiry_check["would_expire"]:
                                existing_ft = str(row.get("first_touch") or "").strip()
                                eval_result = SignalEvaluationResult(
                                    signal_id=str(row["signal_id"]),
                                    symbol=symbol,
                                    new_status="EXPIRED",
                                    first_touch=existing_ft or "EXPIRED",
                                    first_touch_at=row.get("first_touch_at") or now_str,
                                    first_touch_price=float(row.get("first_touch_price") or row.get("current_price") or row.get("entry_price") or 0.0),
                                    outcome_confidence=row.get("outcome_confidence") if existing_ft else OutcomeConfidence.UNRESOLVED.value,
                                    current_price=float(row.get("current_price") or row.get("entry_price") or 0.0),
                                    pnl_pct=float(row.get("pnl_pct") or 0.0),
                                    is_terminal=True,
                                    event_logged=False,
                                    hit_sl=False,
                                    hit_t1=False,
                                    hit_t2=False,
                                    transition_note=f"Holding horizon expired: {expiry_check['reason']}",
                                )
                            else:
                                continue
                        else:
                            # Tick evaluation
                            # Backward-compatibility logic for single-point polling:
                            direction = str(row["direction"]).upper()
                            _entry = float(row["entry_price"])
                            sl = float(row["stop_loss"])
                            t1 = float(row["target_1"])
                            t2 = float(row["target_2"])
                            price_flt = float(price)


                            is_call = direction in ("CALL", "BUY", "LONG")
                            if is_call:
                                hit_sl, hit_t1, hit_t2 = price_flt <= sl, price_flt >= t1, price_flt >= t2
                            else:
                                hit_sl, hit_t1, hit_t2 = price_flt >= sl, price_flt <= t1, price_flt <= t2

                            eval_result = self.evaluate_tick(row, price_flt, current_time=now)

                            # In single LTP observation, if multiple targets crossed in one poll
                            # (e.g. price moved from 100 to 190, crossing both T1 and T2), existing tests
                            # assert AMBIGUOUS_SAME_OBSERVATION for single-tick polling if sum > 1:
                            existing_first_touch = str(row.get("first_touch") or "").strip()
                            if not existing_first_touch and sum((hit_sl, hit_t1, hit_t2)) > 1:
                                eval_result.first_touch = "AMBIGUOUS_SAME_OBSERVATION"
                                eval_result.first_touch_price = price_flt
                                eval_result.outcome_confidence = OutcomeConfidence.AMBIGUOUS.value
                                eval_result.new_status = "AMBIGUOUS"

                    if eval_result is None:
                        continue

                    # Persist lifecycle event if barrier status changed or expired (Idempotency)
                    current_hits = (int(eval_result.hit_sl), int(eval_result.hit_t1), int(eval_result.hit_t2))
                    cur.execute(
                        """SELECT hit_sl, hit_t1, hit_t2
                           FROM signal_outcome_events
                           WHERE signal_id = ?
                           ORDER BY event_id DESC
                           LIMIT 1""",
                        (row["signal_id"],),
                    )
                    prev_event = cur.fetchone()
                    prev_hits = (
                        (int(prev_event["hit_sl"]), int(prev_event["hit_t1"]), int(prev_event["hit_t2"]))
                        if prev_event is not None
                        else None
                    )

                    should_log_barrier = prev_hits != current_hits and (eval_result.hit_sl or eval_result.hit_t1 or eval_result.hit_t2)
                    should_log_expiry = eval_result.new_status == "EXPIRED"

                    if should_log_barrier or should_log_expiry:
                        already_logged = False
                        if should_log_expiry:
                            cur.execute(
                                """SELECT event_id FROM signal_outcome_events
                                   WHERE signal_id = ? AND transition_note LIKE '%expired%'""",
                                (row["signal_id"],),
                            )
                            already_logged = cur.fetchone() is not None

                        if not already_logged:
                            cur.execute(
                                """INSERT INTO signal_outcome_events
                                   (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2, transition_note)
                                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                (
                                    row["signal_id"],
                                    now_str,
                                    eval_result.current_price,
                                    int(eval_result.hit_sl),
                                    int(eval_result.hit_t1),
                                    int(eval_result.hit_t2),
                                    eval_result.transition_note,
                                ),
                            )

                    # Update system_signals and user_deliveries if new status
                    if eval_result.new_status is not None:
                        cur.execute(
                            """UPDATE system_signals
                               SET current_price = ?, status = ?, pnl_pct = ?,
                                   first_touch = ?, first_touch_at = ?, first_touch_price = ?, outcome_confidence = ?
                               WHERE signal_id = ?""",
                            (
                                eval_result.current_price,
                                eval_result.new_status,
                                eval_result.pnl_pct,
                                eval_result.first_touch or "",
                                eval_result.first_touch_at or "",
                                eval_result.first_touch_price,
                                eval_result.outcome_confidence,
                                row["signal_id"],
                            ),
                        )
                        cur.execute(
                            "UPDATE user_deliveries SET current_price = ?, status = ?, pnl_pct = ? WHERE signal_id = ?",
                            (eval_result.current_price, eval_result.new_status, eval_result.pnl_pct, row["signal_id"]),
                        )
                        if eval_result.new_status == "EXPIRED":
                            expired += 1
                        else:
                            resolved += 1
                    else:
                        # Status unchanged, update current price
                        cur.execute(
                            "UPDATE system_signals SET current_price = ?, pnl_pct = ? WHERE signal_id = ?",
                            (eval_result.current_price, eval_result.pnl_pct, row["signal_id"]),
                        )
                        cur.execute(
                            "UPDATE user_deliveries SET current_price = ?, pnl_pct = ? WHERE signal_id = ?",
                            (eval_result.current_price, eval_result.pnl_pct, row["signal_id"]),
                        )

                conn.commit()
            except Exception as ex:
                _log.error("Failed to update active signal outcomes: %s", ex)
            finally:
                conn.close()

        return {"checked": checked, "resolved": resolved, "expired": expired}

    def check_signal_expiry(
        self,
        signal: dict[str, Any],
        current_time: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Pure, read-only classification of whether a signal has reached holding horizon expiry.

        Determined solely by canonical holding horizon and exchange calendar rules.
        Strictly zero database mutation.
        """
        now = current_time or now_ist()
        today_d = now.date()
        sig_id = str(signal.get("signal_id", ""))
        symbol = str(signal.get("symbol", ""))
        category = str(signal.get("category") or "").upper()
        current_status = str(signal.get("status", "ACTIVE")).upper()
        existing_first_touch = str(signal.get("first_touch") or "").strip()
        if not existing_first_touch and current_status in ("TARGET_1_HIT", "T1"):
            existing_first_touch = "T1"
        created_date_str = str(signal.get("created_date") or "").strip()
        timestamp_str = str(signal.get("timestamp") or "").strip()

        # Terminal state check
        is_already_terminal = (
            current_status in ("EXPIRED", "SL_HIT", "AMBIGUOUS", "TARGET_2_HIT")
            or existing_first_touch in ("SL", "AMBIGUOUS", "EXPIRED", "AMBIGUOUS_SAME_BAR", "AMBIGUOUS_SAME_OBSERVATION")
        )

        # Parse creation date
        created_d: datetime.date | None = None
        if created_date_str:
            try:
                created_d = datetime.date.fromisoformat(created_date_str[:10])
            except Exception:
                pass
        if created_d is None and timestamp_str:
            try:
                created_d = datetime.date.fromisoformat(timestamp_str[:10])
            except Exception:
                pass

        if created_d is None:
            return {
                "signal_id": sig_id,
                "symbol": symbol,
                "category": category,
                "created_at": created_date_str or timestamp_str,
                "holding_horizon": "UNKNOWN",
                "calculated_expiry": "UNKNOWN",
                "current_status": current_status,
                "terminal_state": current_status,
                "would_expire": False,
                "classification": "INVALID/UNRESOLVED",
                "reason": "Missing or unparseable creation date and timestamp",
            }

        # Check category horizon
        is_intraday = ("OPTION" in category) or ("0DTE" in category) or ("INTRADAY" in category)

        # Near-close generation check (after 15:15 IST)
        near_close_created = False
        if timestamp_str:
            try:
                time_part = timestamp_str.split(" ")[-1].split("T")[-1]
                h, m = int(time_part[:2]), int(time_part[3:5])
                if datetime.time(h, m) >= NEAR_CLOSE_THRESHOLD_TIME:
                    near_close_created = True
            except Exception:
                pass

        would_expire = False
        reason = ""
        calculated_expiry = ""

        if is_intraday:
            holding_horizon = "INTRADAY"
            if near_close_created:
                # 1-session grace period: expires on next trading session close
                next_session = created_d + datetime.timedelta(days=1)
                while not self._calendar_engine.is_market_day(next_session):
                    next_session += datetime.timedelta(days=1)
                calculated_expiry = f"{next_session.isoformat()} 15:30:00 IST"
                if today_d > next_session:
                    would_expire = True
                    reason = f"Intraday signal with near-close grace period expired past session {next_session.isoformat()}"
                elif today_d == next_session:
                    if self._calendar_engine.is_market_day(today_d) and now.time() >= MARKET_CLOSE_TIME:
                        would_expire = True
                        reason = f"Intraday signal with grace period expired at market close on {today_d.isoformat()}"
                    else:
                        would_expire = False
                        reason = f"Intraday signal with grace period active on session {today_d.isoformat()}"
                else:
                    would_expire = False
                    reason = f"Intraday signal within near-close grace period until {next_session.isoformat()}"
            else:
                calculated_expiry = f"{created_d.isoformat()} 15:30:00 IST"
                if created_d < today_d:
                    would_expire = True
                    reason = f"Intraday signal created on prior date ({created_d.isoformat()} < {today_d.isoformat()})"
                elif created_d == today_d:
                    if self._calendar_engine.is_market_day(today_d) and now.time() >= MARKET_CLOSE_TIME:
                        would_expire = True
                        reason = f"Intraday signal expired at market close on {today_d.isoformat()}"
                    else:
                        would_expire = False
                        reason = f"Intraday signal active within current session ({now.strftime('%H:%M')} < 15:30)"
                else:
                    would_expire = False
                    reason = f"Intraday signal future dated ({created_d.isoformat()})"
        else:
            holding_horizon = "SWING_5_DAYS"
            # Calculate 5th trading day
            d = created_d
            td_count = 0
            while td_count < 5:
                d += datetime.timedelta(days=1)
                if self._calendar_engine.is_market_day(d):
                    td_count += 1
            calculated_expiry = f"{d.isoformat()} 15:30:00 IST"

            trading_days_elapsed = self._count_trading_days(created_d, today_d)
            if trading_days_elapsed >= 5:
                would_expire = True
                reason = f"Swing signal exceeded 5 trading days ({trading_days_elapsed} elapsed >= 5)"
            else:
                would_expire = False
                reason = f"Swing signal within validity ({trading_days_elapsed}/5 trading days elapsed)"

        if is_already_terminal:
            classification = "ALREADY_TERMINAL"
            terminal_state = current_status
            would_expire = False
            reason = f"Already terminal with status {current_status}"
        elif would_expire:
            classification = "WOULD_EXPIRE"
            terminal_state = "EXPIRED"
        else:
            classification = "WOULD_REMAIN_ACTIVE"
            terminal_state = current_status

        return {
            "signal_id": sig_id,
            "symbol": symbol,
            "category": category,
            "created_at": created_date_str or timestamp_str,
            "holding_horizon": holding_horizon,
            "calculated_expiry": calculated_expiry,
            "current_status": current_status,
            "terminal_state": terminal_state,
            "would_expire": would_expire,
            "classification": classification,
            "reason": reason,
        }

    def dry_run_signal_expiry(
        self,
        current_time: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Execute a read-only dry-run expiry classification across system_signals.

        Reports detailed per-candidate records and exact aggregate totals.
        Strictly zero database mutation.
        """
        now = current_time or now_ist()
        candidates: list[dict[str, Any]] = []
        counts = {
            "TOTAL_EVALUATED": 0,
            "WOULD_EXPIRE": 0,
            "WOULD_REMAIN_ACTIVE": 0,
            "ALREADY_TERMINAL": 0,
            "INVALID/UNRESOLVED": 0,
        }

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT * FROM system_signals ORDER BY signal_id ASC")
                rows = [dict(r) for r in cur.fetchall()]
                counts["TOTAL_EVALUATED"] = len(rows)

                for r in rows:
                    res = self.check_signal_expiry(r, current_time=now)
                    candidates.append(res)
                    classification = res.get("classification", "INVALID/UNRESOLVED")
                    if classification in counts:
                        counts[classification] += 1
                    else:
                        counts["INVALID/UNRESOLVED"] += 1
            finally:
                conn.close()

        return {
            "summary": counts,
            "evaluation_time": now.isoformat(),
            "candidates": candidates,
        }

    def expire_stale_signals(
        self,
        dry_run: bool = False,
        current_time: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Expire stale signals past canonical holding horizon.

        If dry_run is True, performs a read-only classification with zero mutation.
        If dry_run is False, transactionally updates signals where would_expire is True,
        preserving first-touch immutability and idempotency.
        """
        now = current_time or now_ist()
        now_str = now.isoformat()

        dry_run_report = self.dry_run_signal_expiry(current_time=now)
        if dry_run:
            return dry_run_report

        candidates_to_expire = [
            c for c in dry_run_report["candidates"] if c["would_expire"]
        ]

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # 1. Before counts
                cur.execute("SELECT status, count(*) as cnt FROM system_signals GROUP BY status")
                before_status_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
                cur.execute("SELECT count(*) as cnt FROM signal_outcome_events")
                events_before = cur.fetchone()["cnt"]

                transitioned = 0
                for c in candidates_to_expire:
                    sig_id = c["signal_id"]
                    cur.execute("SELECT * FROM system_signals WHERE signal_id = ?", (sig_id,))
                    row_raw = cur.fetchone()
                    if not row_raw:
                        continue
                    row = dict(row_raw)

                    current_status = row["status"]
                    if current_status in ("EXPIRED", "SL_HIT", "AMBIGUOUS"):
                        continue

                    existing_first_touch = str(row["first_touch"] or "").strip()
                    if not existing_first_touch and current_status in ("TARGET_1_HIT", "T1"):
                        existing_first_touch = "T1"
                    existing_ft_at = str(row["first_touch_at"] or "").strip()
                    existing_ft_price = float(row["first_touch_price"] or 0.0)
                    existing_conf = str(row["outcome_confidence"] or "UNKNOWN").strip()
                    curr_price = float(row["current_price"] or row["entry_price"] or 0.0)

                    # FIRST-TOUCH PROTECTION: write-once immutable preservation
                    if not existing_first_touch:
                        new_ft = "EXPIRED"
                        new_ft_at = now_str
                        new_ft_price = curr_price
                        new_conf = OutcomeConfidence.UNRESOLVED.value
                    else:
                        new_ft = existing_first_touch
                        new_ft_at = existing_ft_at or str(row.get("created_date") or now_str)
                        new_ft_price = existing_ft_price or float(row.get("target_1") or curr_price)
                        new_conf = existing_conf if existing_conf != "UNKNOWN" else OutcomeConfidence.EXACT_OBSERVATION.value

                    cur.execute(
                        """UPDATE system_signals
                           SET status = 'EXPIRED',
                               first_touch = ?,
                               first_touch_at = ?,
                               first_touch_price = ?,
                               outcome_confidence = ?
                           WHERE signal_id = ?""",
                        (new_ft, new_ft_at, new_ft_price, new_conf, sig_id),
                    )

                    cur.execute(
                        "UPDATE user_deliveries SET status = 'EXPIRED' WHERE signal_id = ?",
                        (sig_id,),
                    )

                    # Idempotent logging into signal_outcome_events
                    cur.execute(
                        """SELECT event_id FROM signal_outcome_events
                           WHERE signal_id = ? AND transition_note LIKE '%expired%'""",
                        (sig_id,),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            """INSERT INTO signal_outcome_events
                               (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2, transition_note)
                               VALUES (?, ?, ?, 0, 0, 0, ?)""",
                            (sig_id, now_str, curr_price, f"Holding horizon expired: {c['reason']}"),
                        )

                    transitioned += 1

                conn.commit()

                # After counts
                cur.execute("SELECT status, count(*) as cnt FROM system_signals GROUP BY status")
                after_status_counts = {r["status"]: r["cnt"] for r in cur.fetchall()}
                cur.execute("SELECT count(*) as cnt FROM signal_outcome_events")
                events_after = cur.fetchone()["cnt"]

                return {
                    "status": "ok",
                    "transitioned": transitioned,
                    "skipped": len(candidates_to_expire) - transitioned,
                    "already_terminal": dry_run_report["summary"]["ALREADY_TERMINAL"],
                    "unresolved": dry_run_report["summary"]["INVALID/UNRESOLVED"],
                    "before_status_counts": before_status_counts,
                    "after_status_counts": after_status_counts,
                    "events_before": events_before,
                    "events_after": events_after,
                }
            finally:
                conn.close()

    @classmethod
    def sweep_stale_signals(
        cls,
        db_path: Path | str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Convenience classmethod to sweep stale signals for a given DB path."""
        tracker = cls.get_instance(db_path=db_path)
        return tracker.run_stale_signal_expiry_sweep(force=force)

    def run_stale_signal_expiry_sweep(
        self,
        force: bool = False,
        current_time: datetime.datetime | None = None,
    ) -> dict[str, Any]:
        """Periodically sweep and transition stale non-terminal signals to EXPIRED.

        Rate-limited to run at most once per 60 seconds (unless force=True).
        Safe to call from any daemon loop, scheduler, or checklist.
        """
        now = current_time or now_ist()
        now_epoch = time.time() if current_time is None else current_time.timestamp()
        with self._io_lock:
            if not force and (now_epoch - self._last_sweep_ts) < self._sweep_min_interval:
                return {"status": "throttled", "transitioned": 0}
            self._last_sweep_ts = now_epoch

        res = self.expire_stale_signals(dry_run=False, current_time=now)
        if res.get("transitioned", 0) > 0:
            _log.info(
                "[OUTCOME_TRACKER] Stale signal expiry sweep transitioned %d signal(s) to EXPIRED",
                res["transitioned"],
            )
        return res

    def get_outcome_statistics(

        self,
        timeframe: str = "all",
        category: str = "all",
        tier: str = "all",
        status: str = "all",
        include_seed_samples: bool = False,
    ) -> dict[str, Any]:
        """Compute empirical signal metrics with rigorous quarantining of ambiguous and expired signals.

        Win Rate Formula:
            Win Rate % = (T1 Hits) / (T1 Hits + SL Hits) * 100
            Ambiguous and Expired signals are explicitly quarantined from the ratio.
        Profit Factor Formula:
            Profit Factor = (Sum of Gains from Wins) / (Sum of Losses from SL)
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                now = now_ist()
                conditions = ["1=1"]
                params: list[Any] = []

                if timeframe == "today":
                    conditions.append("created_date = ?")
                    params.append(now.date().isoformat())
                elif timeframe == "week":
                    conditions.append("created_week = ?")
                    params.append(f"{now.year}-W{now.isocalendar()[1]}")
                elif timeframe == "month":
                    conditions.append("created_month = ?")
                    params.append(f"{now.year}-{now.month:02d}")
                elif timeframe == "year":
                    conditions.append("created_year = ?")
                    params.append(str(now.year))

                if category != "all":
                    conditions.append("category = ?")
                    params.append(category)

                if tier != "all":
                    conditions.append("tier = ?")
                    params.append(tier)

                if status != "all":
                    conditions.append("status = ?")
                    params.append(status)

                where_clause = " AND ".join(conditions)

                cur.execute(
                    f"SELECT * FROM system_signals WHERE {where_clause} ORDER BY timestamp DESC",
                    params,
                )
                all_rows = [dict(r) for r in cur.fetchall()]

                if not include_seed_samples:
                    rows = [r for r in all_rows if not (r.get("raw_data") and "is_seed_sample" in r["raw_data"])]
                else:
                    rows = all_rows

                total_signals = len(rows)
                open_signals = sum(1 for r in rows if r["status"] in ("OPEN", "ACTIVE") and not r.get("first_touch"))
                t1_hits = sum(1 for r in rows if r.get("first_touch") in ("T1", "T2") or (not r.get("first_touch") and r["status"] in ("TARGET_1_HIT", "TARGET_2_HIT")))
                t2_hits = sum(1 for r in rows if r["status"] == "TARGET_2_HIT")
                sl_hits = sum(1 for r in rows if (r.get("first_touch") == "SL") or (not r.get("first_touch") and r["status"] == "SL_HIT"))
                ambiguous = sum(1 for r in rows if r.get("first_touch") in ("AMBIGUOUS", "AMBIGUOUS_SAME_BAR") or r["status"] == "AMBIGUOUS")
                expired = sum(1 for r in rows if r.get("first_touch") == "EXPIRED" or r["status"] == "EXPIRED")
                lifecycle_sl_after_t1 = sum(1 for r in rows if r.get("first_touch") in ("T1", "T2") and r["status"] == "SL_HIT")

                # Empirical Win Rate: excludes ambiguous and expired
                resolved_signals = t1_hits + sl_hits
                if resolved_signals > 0:
                    win_rate_pct = round((t1_hits / resolved_signals) * 100, 2)
                    win_rate_display = f"{win_rate_pct}%"
                    loss_rate_pct = round((sl_hits / resolved_signals) * 100, 2)
                    loss_rate_display = f"{loss_rate_pct}%"
                else:
                    win_rate_pct = None
                    win_rate_display = "N/A (0 resolved)"
                    loss_rate_pct = 0.0
                    loss_rate_display = "0.0%"

                # Profit Factor calculation
                winning_pnl = sum(r["pnl_pct"] for r in rows if r["status"] in ("TARGET_1_HIT", "TARGET_2_HIT") and r["pnl_pct"] > 0)
                losing_pnl = abs(sum(r["pnl_pct"] for r in rows if r["status"] == "SL_HIT" and r["pnl_pct"] < 0))

                if losing_pnl > 0:
                    profit_factor = round(winning_pnl / losing_pnl, 2)
                elif winning_pnl > 0:
                    profit_factor = 999.99  # Infinite / zero losses
                else:
                    profit_factor = 0.0

                # Detailed average win / loss PnL lists
                winning_pnls: list[float] = []
                for r in rows:
                    if r.get("first_touch") in ("T1", "T2") or (not r.get("first_touch") and r.get("status") in ("TARGET_1_HIT", "TARGET_2_HIT")):
                        p = float(r.get("pnl_pct") or 0.0)
                        if p > 0:
                            winning_pnls.append(p)
                        elif r.get("entry_price") and r.get("target_1") and float(r["entry_price"]) > 0:
                            ep = float(r["entry_price"])
                            t1 = float(r["target_1"])
                            calc_p = abs((t1 - ep) / ep * 100.0)
                            winning_pnls.append(calc_p)

                losing_pnls: list[float] = []
                for r in rows:
                    if r.get("first_touch") == "SL" or (not r.get("first_touch") and r.get("status") == "SL_HIT"):
                        p = float(r.get("pnl_pct") or 0.0)
                        if p != 0:
                            losing_pnls.append(abs(p))
                        elif r.get("entry_price") and r.get("stop_loss") and float(r["entry_price"]) > 0:
                            ep = float(r["entry_price"])
                            sl = float(r["stop_loss"])
                            calc_p = abs((ep - sl) / ep * 100.0)
                            losing_pnls.append(calc_p)

                avg_win_pnl = round(sum(winning_pnls) / len(winning_pnls), 2) if winning_pnls else 0.0
                avg_loss_pnl = round(sum(losing_pnls) / len(losing_pnls), 2) if losing_pnls else 0.0

                # Mathematical Expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
                if resolved_signals > 0:
                    win_frac = t1_hits / resolved_signals
                    loss_frac = sl_hits / resolved_signals
                    expectancy_pct = round((win_frac * avg_win_pnl) - (loss_frac * avg_loss_pnl), 2)
                    expectancy_display = f"{expectancy_pct:+.2f}%"
                else:
                    expectancy_pct = None
                    expectancy_display = "N/A (0 resolved)"

                # MFE / MAE computation from signal_outcome_events and barrier touches
                events_by_signal: dict[str, list[float]] = {}
                sig_ids = [r["signal_id"] for r in rows if r.get("signal_id")]
                if sig_ids:
                    chunk_size = 500
                    for i in range(0, len(sig_ids), chunk_size):
                        chunk = sig_ids[i:i + chunk_size]
                        placeholders = ",".join("?" for _ in chunk)
                        cur.execute(
                            f"SELECT signal_id, observed_price FROM signal_outcome_events WHERE signal_id IN ({placeholders})",
                            chunk,
                        )
                        for ev in cur.fetchall():
                            events_by_signal.setdefault(ev["signal_id"], []).append(float(ev["observed_price"]))

                all_mfes: list[float] = []
                all_maes: list[float] = []
                for r in rows:
                    ep = float(r.get("entry_price") or 0.0)
                    if ep <= 0:
                        continue
                    is_b = str(r.get("direction", "")).upper() in ("BUY", "CALL", "LONG")
                    prices = list(events_by_signal.get(r["signal_id"], []))
                    if r.get("first_touch_price") and float(r["first_touch_price"]) > 0:
                        prices.append(float(r["first_touch_price"]))
                    if r.get("current_price") and float(r["current_price"]) > 0:
                        prices.append(float(r["current_price"]))
                    if r.get("first_touch") in ("T1", "T2") or r.get("status") in ("TARGET_1_HIT", "TARGET_2_HIT"):
                        if r.get("target_1") and float(r["target_1"]) > 0:
                            prices.append(float(r["target_1"]))
                    if r.get("first_touch") == "T2" or r.get("status") == "TARGET_2_HIT":
                        if r.get("target_2") and float(r["target_2"]) > 0:
                            prices.append(float(r["target_2"]))
                    if r.get("first_touch") == "SL" or r.get("status") == "SL_HIT":
                        if r.get("stop_loss") and float(r["stop_loss"]) > 0:
                            prices.append(float(r["stop_loss"]))

                    if prices:
                        sig_mfes = []
                        sig_maes = []
                        for p in prices:
                            if is_b:
                                fav = (p - ep) / ep * 100.0
                                adv = (ep - p) / ep * 100.0
                            else:
                                fav = (ep - p) / ep * 100.0
                                adv = (p - ep) / ep * 100.0
                            sig_mfes.append(max(0.0, fav))
                            sig_maes.append(max(0.0, adv))
                        if sig_mfes:
                            all_mfes.append(max(sig_mfes))
                            all_maes.append(max(sig_maes))

                avg_mfe_pct = round(sum(all_mfes) / len(all_mfes), 2) if all_mfes else 0.0
                max_mfe_pct = round(max(all_mfes), 2) if all_mfes else 0.0
                avg_mae_pct = round(sum(all_maes) / len(all_maes), 2) if all_maes else 0.0
                max_mae_pct = round(max(all_maes), 2) if all_maes else 0.0

                # Duration to first touch
                durations: list[float] = []
                win_durations: list[float] = []
                loss_durations: list[float] = []
                for r in rows:
                    ts_created = r.get("timestamp")
                    ts_touch = r.get("first_touch_at")
                    if ts_created and ts_touch:
                        try:
                            dt1 = datetime.datetime.fromisoformat(str(ts_created).replace("Z", "+00:00").replace(" ", "T"))
                            dt2 = datetime.datetime.fromisoformat(str(ts_touch).replace("Z", "+00:00").replace(" ", "T"))
                            dur_mins = (dt2 - dt1).total_seconds() / 60.0
                            if dur_mins >= 0:
                                durations.append(dur_mins)
                                if r.get("first_touch") in ("T1", "T2") or r.get("status") in ("TARGET_1_HIT", "TARGET_2_HIT"):
                                    win_durations.append(dur_mins)
                                elif r.get("first_touch") == "SL" or r.get("status") == "SL_HIT":
                                    loss_durations.append(dur_mins)
                        except Exception:
                            pass

                avg_duration_to_first_touch_mins = round(sum(durations) / len(durations), 1) if durations else None
                avg_duration_to_win_mins = round(sum(win_durations) / len(win_durations), 1) if win_durations else None
                avg_duration_to_loss_mins = round(sum(loss_durations) / len(loss_durations), 1) if loss_durations else None

                # Multi-dimensional Segmentation
                def _calc_segment(sub_rows: list[dict[str, Any]]) -> dict[str, Any]:
                    sub_total = len(sub_rows)
                    sub_t1 = sum(1 for r in sub_rows if r.get("first_touch") in ("T1", "T2") or (not r.get("first_touch") and r.get("status") in ("TARGET_1_HIT", "TARGET_2_HIT")))
                    sub_sl = sum(1 for r in sub_rows if r.get("first_touch") == "SL" or (not r.get("first_touch") and r.get("status") == "SL_HIT"))
                    sub_res = sub_t1 + sub_sl
                    sub_win = round((sub_t1 / sub_res) * 100, 2) if sub_res > 0 else None
                    sub_loss = round((sub_sl / sub_res) * 100, 2) if sub_res > 0 else 0.0

                    sub_w = []
                    for r in sub_rows:
                        if r.get("first_touch") in ("T1", "T2") or (not r.get("first_touch") and r.get("status") in ("TARGET_1_HIT", "TARGET_2_HIT")):
                            p = float(r.get("pnl_pct") or 0.0)
                            if p > 0:
                                sub_w.append(p)
                            elif r.get("entry_price") and r.get("target_1") and float(r["entry_price"]) > 0:
                                sub_w.append(abs((float(r["target_1"]) - float(r["entry_price"])) / float(r["entry_price"]) * 100.0))

                    sub_l = []
                    for r in sub_rows:
                        if r.get("first_touch") == "SL" or (not r.get("first_touch") and r.get("status") == "SL_HIT"):
                            p = float(r.get("pnl_pct") or 0.0)
                            if p != 0:
                                sub_l.append(abs(p))
                            elif r.get("entry_price") and r.get("stop_loss") and float(r["entry_price"]) > 0:
                                sub_l.append(abs((float(r["entry_price"]) - float(r["stop_loss"])) / float(r["entry_price"]) * 100.0))

                    s_avg_w = round(sum(sub_w) / len(sub_w), 2) if sub_w else 0.0
                    s_avg_l = round(sum(sub_l) / len(sub_l), 2) if sub_l else 0.0
                    s_exp = round(((sub_t1 / sub_res) * s_avg_w) - ((sub_sl / sub_res) * s_avg_l), 2) if sub_res > 0 else None
                    warn = sub_total < 5
                    return {
                        "total_signals": sub_total,
                        "resolved_signals": sub_res,
                        "t1_hits": sub_t1,
                        "sl_hits": sub_sl,
                        "win_rate_pct": sub_win,
                        "loss_rate_pct": sub_loss,
                        "avg_win_pnl": s_avg_w,
                        "avg_loss_pnl": s_avg_l,
                        "expectancy_pct": s_exp,
                        "sample_size_warning": warn,
                        "warning": "Low sample size (< 5). Results may not be statistically significant." if warn else None,
                    }

                segmentation: dict[str, dict[str, Any]] = {
                    "by_direction": {},
                    "by_tier": {},
                    "by_category": {},
                    "by_score_band": {},
                    "by_symbol": {},
                }

                # Group by direction
                dir_groups: dict[str, list[dict[str, Any]]] = {}
                for r in rows:
                    d = str(r.get("direction") or "UNKNOWN").upper()
                    dir_groups.setdefault(d, []).append(r)
                for d, g in dir_groups.items():
                    segmentation["by_direction"][d] = _calc_segment(g)

                # Group by tier
                tier_groups: dict[str, list[dict[str, Any]]] = {}
                for r in rows:
                    t = str(r.get("tier") or "UNKNOWN").upper()
                    tier_groups.setdefault(t, []).append(r)
                for t, g in tier_groups.items():
                    segmentation["by_tier"][t] = _calc_segment(g)

                # Group by category
                cat_groups: dict[str, list[dict[str, Any]]] = {}
                for r in rows:
                    c = str(r.get("category") or "UNKNOWN").upper()
                    cat_groups.setdefault(c, []).append(r)
                for c, g in cat_groups.items():
                    segmentation["by_category"][c] = _calc_segment(g)

                # Group by score band
                score_groups: dict[str, list[dict[str, Any]]] = {">=80": [], "70-79": [], "<70": []}
                for r in rows:
                    sc = float(r.get("score") or 0.0)
                    if sc >= 80:
                        score_groups[">=80"].append(r)
                    elif sc >= 70:
                        score_groups["70-79"].append(r)
                    else:
                        score_groups["<70"].append(r)
                for sb, g in score_groups.items():
                    segmentation["by_score_band"][sb] = _calc_segment(g)

                # Group by symbol (top 20 symbols by signal count)
                sym_groups: dict[str, list[dict[str, Any]]] = {}
                for r in rows:
                    s = str(r.get("symbol") or "UNKNOWN").upper()
                    sym_groups.setdefault(s, []).append(r)
                sorted_syms = sorted(sym_groups.items(), key=lambda item: len(item[1]), reverse=True)[:20]
                for s, g in sorted_syms:
                    segmentation["by_symbol"][s] = _calc_segment(g)

                overall_sample_warning = total_signals < 5

                return {
                    "total_signals": total_signals,
                    "open_signals": open_signals,
                    "t1_hits": t1_hits,
                    "t2_hits": t2_hits,
                    "sl_hits": sl_hits,
                    "ambiguous": ambiguous,
                    "expired": expired,
                    "resolved_signals": resolved_signals,
                    "first_touch_win_rate_pct": win_rate_pct,
                    "first_touch_win_rate_display": win_rate_display,
                    "win_rate_pct": win_rate_pct,
                    "win_rate_display": win_rate_display,
                    "loss_rate_pct": loss_rate_pct,
                    "loss_rate_display": loss_rate_display,
                    "avg_win_pnl": avg_win_pnl,
                    "avg_loss_pnl": avg_loss_pnl,
                    "expectancy_pct": expectancy_pct,
                    "expectancy_display": expectancy_display,
                    "mfe_stats": {"avg_pct": avg_mfe_pct, "max_pct": max_mfe_pct, "samples": len(all_mfes)},
                    "mae_stats": {"avg_pct": avg_mae_pct, "max_pct": max_mae_pct, "samples": len(all_maes)},
                    "avg_mfe_pct": avg_mfe_pct,
                    "max_mfe_pct": max_mfe_pct,
                    "avg_mae_pct": avg_mae_pct,
                    "max_mae_pct": max_mae_pct,
                    "avg_duration_to_first_touch_mins": avg_duration_to_first_touch_mins,
                    "avg_duration_to_win_mins": avg_duration_to_win_mins,
                    "avg_duration_to_loss_mins": avg_duration_to_loss_mins,
                    "segmentation": segmentation,
                    "sample_size_warning": overall_sample_warning,
                    "sample_size_note": "Low sample size (< 5). Results may not be statistically significant." if overall_sample_warning else None,
                    "metric_type": "FIRST_TOUCH_OBSERVATIONAL",
                    "lifecycle_sl_after_t1": lifecycle_sl_after_t1,
                    "profit_factor": profit_factor,
                    "calculated_at": now.isoformat(),
                }
            except Exception as ex:
                _log.error("Failed to compute outcome statistics: %s", ex)
                return {
                    "error": str(ex),
                    "total_signals": 0,
                    "open_signals": 0,
                    "t1_hits": 0,
                    "t2_hits": 0,
                    "sl_hits": 0,
                    "ambiguous": 0,
                    "expired": 0,
                    "resolved_signals": 0,
                    "first_touch_win_rate_pct": None,
                    "first_touch_win_rate_display": "N/A",
                    "win_rate_pct": None,
                    "win_rate_display": "N/A",
                    "loss_rate_pct": 0.0,
                    "loss_rate_display": "0.0%",
                    "avg_win_pnl": 0.0,
                    "avg_loss_pnl": 0.0,
                    "expectancy_pct": None,
                    "expectancy_display": "N/A",
                    "mfe_stats": {"avg_pct": 0.0, "max_pct": 0.0, "samples": 0},
                    "mae_stats": {"avg_pct": 0.0, "max_pct": 0.0, "samples": 0},
                    "avg_mfe_pct": 0.0,
                    "max_mfe_pct": 0.0,
                    "avg_mae_pct": 0.0,
                    "max_mae_pct": 0.0,
                    "avg_duration_to_first_touch_mins": None,
                    "avg_duration_to_win_mins": None,
                    "avg_duration_to_loss_mins": None,
                    "segmentation": {},
                    "sample_size_warning": False,
                    "sample_size_note": None,
                    "metric_type": "FIRST_TOUCH_OBSERVATIONAL",
                    "lifecycle_sl_after_t1": 0,
                    "profit_factor": 0.0,
                    "calculated_at": now_ist().isoformat(),
                }
            finally:
                conn.close()
