"""Signal Tracking, Accuracy Analytics & User Delivery History Engine (v3.0).

Manages:
- System-wide generated signals history across all 8 market categories
- Real-time outcome & accuracy tracking (Win Rate %, Target 1 Hit, Target 2 Hit, SL Hit, P&L %)
- Multi-timeframe analytics (Daily, Weekly, Monthly, Yearly) for Super Admin
- Personalized signal delivery history per user with time filters (Year, Month, Week, Day)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist

_log = logging.getLogger("SIGNAL_TRACKER")
_ROOT = Path(__file__).resolve().parent.parent.parent
_DB_PATH = _ROOT / "db" / "signals_history.db"


class SignalTracker:
    """Thread-safe SQLite Tracker for System Signals & User Delivery History."""

    _instance: SignalTracker | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or _DB_PATH
        self._io_lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None) -> SignalTracker:
        """Process-wide singleton. *db_path* only matters on first
        construction (same convention as this codebase's other cfg-driven
        singletons, e.g. get_intraday_monitor()) - pass it once, early
        (or call reset_instance() first in tests), to redirect this
        previously hardcoded db/signals_history.db path for isolation."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = SignalTracker(db_path=Path(db_path) if db_path is not None else None)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Test-only reset of the singleton."""
        with cls._lock:
            cls._instance = None

    def _get_conn(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create tables and seed initial historical records if empty."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # 1. System-wide signals table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS system_signals (
                        signal_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        created_date TEXT NOT NULL,
                        created_week TEXT NOT NULL,
                        created_month TEXT NOT NULL,
                        created_year TEXT NOT NULL,
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
                        recipients_count INTEGER DEFAULT 0,
                        raw_data TEXT,
                        raw_score REAL,
                        normalized_score REAL,
                        score_saturated INTEGER DEFAULT 0,
                        opportunity_key TEXT,
                        outcome_confidence TEXT DEFAULT 'POLLING'
                    )
                """)

                # Backward-compatible migrations for databases created by older releases.
                for col, ddl in (
                    ("raw_score", "ALTER TABLE system_signals ADD COLUMN raw_score REAL"),
                    ("normalized_score", "ALTER TABLE system_signals ADD COLUMN normalized_score REAL"),
                    ("score_saturated", "ALTER TABLE system_signals ADD COLUMN score_saturated INTEGER DEFAULT 0"),
                    ("opportunity_key", "ALTER TABLE system_signals ADD COLUMN opportunity_key TEXT"),
                    ("outcome_confidence", "ALTER TABLE system_signals ADD COLUMN outcome_confidence TEXT DEFAULT 'POLLING'"),
                ):
                    try:
                        cur.execute(f"SELECT {col} FROM system_signals LIMIT 1")
                    except sqlite3.OperationalError:
                        try:
                            cur.execute(ddl)
                        except sqlite3.OperationalError:
                            pass
                cur.execute("CREATE INDEX IF NOT EXISTS idx_system_signals_opportunity_key ON system_signals(opportunity_key)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_system_signals_symbol_time ON system_signals(symbol, timestamp)")

                # Scan-cycle observability: aggregate scanner evaluations without
                # persisting every candidate row.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS scan_cycle_metrics (
                        cycle_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        symbols_scanned INTEGER NOT NULL,
                        evaluated INTEGER NOT NULL,
                        accepted INTEGER NOT NULL,
                        delivered_candidates INTEGER NOT NULL,
                        errors INTEGER NOT NULL,
                        metadata TEXT
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_scan_cycle_timestamp ON scan_cycle_metrics(timestamp)")

                # 2. User personal delivery history table
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
                        channels_sent TEXT NOT NULL,
                        FOREIGN KEY (signal_id) REFERENCES system_signals (signal_id)
                    )
                """)

                # 3. Outcome observations: preserves the price path evidence needed
                # to distinguish a true first-touch from an ambiguous polling interval.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS signal_outcome_events (
                        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        signal_id TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        observed_price REAL NOT NULL,
                        hit_sl INTEGER NOT NULL DEFAULT 0,
                        hit_t1 INTEGER NOT NULL DEFAULT 0,
                        hit_t2 INTEGER NOT NULL DEFAULT 0,
                        FOREIGN KEY (signal_id) REFERENCES system_signals(signal_id)
                    )
                """)

                # Migration: order-placed marking (admin manually records "I
                # placed a real/paper order off this signal" for historical
                # tracking - see mark_order_placed()). ADD COLUMN has no
                # IF NOT EXISTS in the SQLite versions this must run on, so
                # catch the duplicate-column error the same way this
                # codebase's other SQLite migrations do (see
                # core/auth/handler/handler.py).
                for col, col_type in (
                    ("order_placed", "INTEGER DEFAULT 0"),
                    ("order_placed_by", "TEXT DEFAULT ''"),
                    ("order_placed_at", "TEXT DEFAULT ''"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE system_signals ADD COLUMN {col} {col_type}")
                    except sqlite3.OperationalError:
                        pass  # column already exists

                for col, col_type in (
                    ("first_touch", "TEXT DEFAULT ''"),
                    ("first_touch_at", "TEXT DEFAULT ''"),
                    ("outcome_confidence", "TEXT DEFAULT 'UNKNOWN'"),
                ):
                    try:
                        cur.execute(f"ALTER TABLE system_signals ADD COLUMN {col} {col_type}")
                    except sqlite3.OperationalError:
                        pass

                # Check if empty, then seed sample historical data
                cur.execute("SELECT COUNT(*) as cnt FROM system_signals")
                row = cur.fetchone()
                if row and row["cnt"] == 0:
                    self._seed_sample_history(cur)

                conn.commit()
            except Exception as ex:
                _log.error("Failed to initialize signals database: %s", ex)
            finally:
                conn.close()

    def _seed_sample_history(self, cur: sqlite3.Cursor) -> None:
        """Seed realistic signals history across categories strictly within valid market running hours."""
        sample_signals = [
            # (symbol, company_name, category, direction, score, tier, entry, sl, t1, t2, curr, status, pnl, day_offset, hour, minute, second)
            ("TCS", "Tata Consultancy Services", "LARGE_CAP_EQUITY", "CALL", 92, "STRONG", 2268.0, 2200.0, 2358.7, 2449.4, 2362.0, "TARGET_1_HIT", 4.14, 0, 11, 45, 12),
            ("RELIANCE", "Reliance Industries Ltd", "LARGE_CAP_EQUITY", "CALL", 88, "STRONG", 1385.0, 1343.4, 1440.4, 1495.8, 1445.0, "TARGET_1_HIT", 4.33, 1, 10, 15, 30),
            ("NIFTY24AUG24500CE", "NIFTY 24500 CE", "INDEX_OPTIONS", "CALL", 90, "STRONG", 125.0, 85.0, 165.0, 210.0, 172.0, "TARGET_1_HIT", 37.6, 1, 9, 25, 0),
            ("BANKNIFTY24AUG52000CE", "BANK NIFTY 52000 CE", "INDEX_OPTIONS", "CALL", 95, "STRONG", 280.0, 195.0, 380.0, 490.0, 502.0, "TARGET_2_HIT", 79.2, 2, 9, 35, 10),
            ("SUZLON", "Suzlon Energy Ltd", "PENNY_SME", "CALL", 84, "STRONG", 42.50, 41.20, 44.20, 45.90, 44.50, "TARGET_1_HIT", 4.70, 1, 14, 20, 45),
            ("IDEA", "Vodafone Idea Ltd", "PENNY_SME", "CALL", 72, "MODERATE", 7.80, 7.55, 8.12, 8.42, 7.60, "ACTIVE", -2.56, 1, 13, 10, 20),
            ("GOLDM24SEP", "MCX Gold Mini", "COMMODITIES", "CALL", 86, "STRONG", 71500.0, 70500.0, 72800.0, 74200.0, 73050.0, "TARGET_1_HIT", 2.17, 2, 19, 30, 0),
            ("CRUDEOIL24SEP", "MCX Crude Oil", "COMMODITIES", "PUT", 82, "STRONG", 6450.0, 6600.0, 6250.0, 6050.0, 6220.0, "TARGET_1_HIT", 3.56, 2, 20, 45, 0),
            ("USDINR24AUGFUT", "USD/INR Currency Future", "CURRENCIES", "CALL", 76, "MODERATE", 83.92, 83.75, 84.15, 84.35, 84.18, "TARGET_1_HIT", 0.31, 2, 15, 15, 0),
            ("NIFTYBEES", "Nippon India Nifty 50 ETF", "ETFS_REITS", "CALL", 85, "STRONG", 265.50, 260.0, 274.0, 282.0, 275.20, "TARGET_1_HIT", 3.65, 2, 14, 50, 0),
            ("KAYNES", "Kaynes Technology India Ltd", "MID_SMALL_CAP", "CALL", 89, "STRONG", 5420.0, 5250.0, 5636.8, 5853.6, 5650.0, "TARGET_1_HIT", 4.24, 1, 11, 5, 30),
            ("TATACOMM", "Tata Communications Ltd", "MID_SMALL_CAP", "CALL", 78, "MODERATE", 1890.0, 1833.0, 1965.0, 2040.0, 1970.0, "TARGET_1_HIT", 4.23, 1, 10, 40, 15),
        ]

        now = now_ist()
        for idx, (sym, cname, cat, dirn, score, tier, entry, sl, t1, t2, curr, status, pnl, day_offset, h, m, s) in enumerate(sample_signals):
            target_date = (now - timedelta(days=day_offset)).date()
            sig_time = datetime(target_date.year, target_date.month, target_date.day, h, m, s)
            sig_id = f"SIG-{sig_time.strftime('%Y%m%d')}-{sym}-{idx+100}"
            date_str = sig_time.date().isoformat()
            week_str = f"{sig_time.year}-W{sig_time.isocalendar()[1]}"
            month_str = f"{sig_time.year}-{sig_time.month:02d}"
            year_str = str(sig_time.year)

            cur.execute("""
                INSERT OR IGNORE INTO system_signals (
                    signal_id, timestamp, created_date, created_week, created_month, created_year,
                    symbol, company_name, category, direction, score, tier, entry_price, stop_loss,
                    target_1, target_2, current_price, status, pnl_pct, recipients_count, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sig_id, sig_time.strftime("%Y-%m-%d %H:%M:%S"), date_str, week_str, month_str, year_str,
                sym, cname, cat, dirn, score, tier, entry, sl, t1, t2, curr, status, pnl, 2,
                # Marks this row as seeded sample content, not a real generated
                # signal - "My Signals"/admin analytics previously showed this
                # data with zero indication it wasn't real, on every fresh install.
                '{"is_seed_sample": true}',
            ))

            # Deliveries for admin
            cur.execute("""
                INSERT OR IGNORE INTO user_deliveries (
                    delivery_id, signal_id, username, timestamp, delivery_date, delivery_week,
                    delivery_month, delivery_year, symbol, company_name, category, direction,
                    score, tier, entry_price, stop_loss, target_1, target_2, current_price,
                    status, pnl_pct, channels_sent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"DEL-{sig_id}-admin", sig_id, "admin", sig_time.strftime("%Y-%m-%d %H:%M:%S"), date_str, week_str,
                month_str, year_str, sym, cname, cat, dirn, score, tier, entry, sl, t1, t2, curr,
                status, pnl, "Telegram, Email"
            ))

    def record_scan_cycle(self, stats: dict[str, Any], *, symbols_scanned: int, timestamp: str | None = None) -> str:
        """Persist one aggregate scanner-cycle metric row.

        This deliberately stores counts rather than every rejected candidate,
        keeping the production DB bounded while making candidate-vs-signal
        volume auditable.
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                now = timestamp or now_ist().isoformat()
                cycle_id = f"SCAN-{now.replace(':','').replace('-','').replace('.','')}-{uuid.uuid4().hex[:8]}"
                conn.execute(
                    """INSERT INTO scan_cycle_metrics
                       (cycle_id,timestamp,symbols_scanned,evaluated,accepted,delivered_candidates,errors,metadata)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (cycle_id, now, int(symbols_scanned), int(stats.get("evaluated",0)),
                     int(stats.get("accepted",0)), int(stats.get("delivered_candidates",0)),
                     int(stats.get("errors",0)), json.dumps(stats, default=str))
                )
                conn.commit()
                return cycle_id
            except Exception as ex:
                _log.error("Failed to record scan cycle: %s", ex)
                return ""
            finally:
                conn.close()

    def record_generated_signal(
        self,
        signal_dict: dict[str, Any],
        eligible_users: list[Any] | None = None,
    ) -> str:
        """Record a unique generated signal and its per-user deliveries.

        A signal is distinct from a scan/evaluation.  Repeated evaluations of
        the same opportunity within the configured cooldown are suppressed
        before persistence/delivery.  The opportunity key is persisted so
        deduplication survives process restarts.
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                now = now_ist()
                sym = str(signal_dict.get("symbol", "UNKNOWN")).upper()
                direction = str(signal_dict.get("direction", "CALL")).upper()
                cat = str(signal_dict.get("category", "LARGE_CAP_EQUITY")).upper()
                strategy = str(signal_dict.get("strategy") or signal_dict.get("strategy_name") or "default").lower()
                regime = str(signal_dict.get("regime") or "UNKNOWN").upper()
                entry_price = float(signal_dict.get("price", 0.0))
                sl_price = float(signal_dict.get("stop_loss", round(entry_price * 0.97, 2)))
                t1_price = float(signal_dict.get("target_1", round(entry_price * 1.04, 2)))
                t2_price = float(signal_dict.get("target_2", round(entry_price * 1.08, 2)))
                score = int(signal_dict.get("score", 80))
                raw_score = float(signal_dict.get("raw_score", score))
                normalized_score = float(signal_dict.get("normalized_score", score))
                saturated = int(bool(signal_dict.get("score_saturated", raw_score > 100 and score >= 100)))
                tier = str(signal_dict.get("tier", "STRONG"))
                cname = signal_dict.get("company_name", sym)

                # Stable opportunity identity intentionally excludes the live
                # price/targets. The v18 fingerprint included rounded prices,
                # so every small market move could create a new opportunity and
                # bypass the intended lifecycle deduplication.
                opportunity_key = str(signal_dict.get("opportunity_key") or
                    f"{sym}|{direction}|{cat}|{strategy}")

                cooldown = int(signal_dict.get("dedup_cooldown_secs", 900))
                cutoff = (now - timedelta(seconds=max(0, cooldown))).strftime("%Y-%m-%d %H:%M:%S")

                # First suppress any still-active opportunity regardless of the
                # price change. This is the durable lifecycle lock.
                cur.execute(
                    """SELECT signal_id FROM system_signals
                       WHERE opportunity_key = ? AND status = 'ACTIVE'
                       ORDER BY timestamp DESC LIMIT 1""",
                    (opportunity_key,),
                )
                duplicate = cur.fetchone()
                if not duplicate:
                    cur.execute(
                        """SELECT signal_id FROM system_signals
                           WHERE opportunity_key = ? AND timestamp >= ?
                           ORDER BY timestamp DESC LIMIT 1""",
                        (opportunity_key, cutoff),
                    )
                    duplicate = cur.fetchone()
                if duplicate:
                    _log.info("[SIGNAL_DEDUP] Suppressed duplicate %s -> %s", sym, duplicate["signal_id"])
                    return ""

                sig_id = f"SIG-{now.strftime('%Y%m%d%H%M%S')}-{sym}-{uuid.uuid4().hex[:6]}"
                date_str = now.date().isoformat()
                week_str = f"{now.year}-W{now.isocalendar()[1]}"
                month_str = f"{now.year}-{now.month:02d}"
                year_str = str(now.year)
                recipients_count = len(eligible_users) if eligible_users else 0

                cur.execute("""
                    INSERT INTO system_signals (
                        signal_id, timestamp, created_date, created_week, created_month, created_year,
                        symbol, company_name, category, direction, score, tier, entry_price, stop_loss,
                        target_1, target_2, current_price, status, pnl_pct, recipients_count, raw_data,
                        raw_score, normalized_score, score_saturated, opportunity_key, outcome_confidence
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    sig_id, now.strftime("%Y-%m-%d %H:%M:%S"), date_str, week_str, month_str, year_str,
                    sym, cname, cat, direction, score, tier, entry_price, sl_price,
                    t1_price, t2_price, entry_price, "ACTIVE", 0.0, recipients_count,
                    json.dumps(signal_dict, default=str), raw_score, normalized_score, saturated,
                    opportunity_key, "POLLING"
                ))

                if eligible_users:
                    for u in eligible_users:
                        uname = getattr(u, "username", str(u))
                        channels = []
                        if getattr(u, "telegram_enabled", False):
                            channels.append("Telegram")
                        if getattr(u, "email_enabled", False):
                            channels.append("Email")
                        ch_str = ", ".join(channels) if channels else "Web Dashboard"
                        cur.execute("""
                            INSERT INTO user_deliveries (
                                delivery_id, signal_id, username, timestamp, delivery_date, delivery_week,
                                delivery_month, delivery_year, symbol, company_name, category, direction,
                                score, tier, entry_price, stop_loss, target_1, target_2, current_price,
                                status, pnl_pct, channels_sent
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            f"DEL-{sig_id}-{uname}", sig_id, uname, now.strftime("%Y-%m-%d %H:%M:%S"),
                            date_str, week_str, month_str, year_str, sym, cname, cat, direction, score, tier,
                            entry_price, sl_price, t1_price, t2_price, entry_price, "ACTIVE", 0.0, ch_str
                        ))
                conn.commit()
                _log.info("[SIGNAL_TRACKER] Logged signal %s for %s (%s, Recipients: %d)",
                          sig_id, sym, cat, recipients_count)
                return sig_id
            except Exception as ex:
                _log.error("Failed to record generated signal: %s", ex)
                return ""
            finally:
                conn.close()

    def count_generated_today(self) -> int:
        """Return the number of real generated signals for the current IST date."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM system_signals "
                    "WHERE created_date = ? AND (raw_data IS NULL OR raw_data NOT LIKE '%is_seed_sample%')",
                    (now_ist().date().isoformat(),),
                ).fetchone()
                return int(row["n"] if row else 0)
            except (sqlite3.Error, OSError, TypeError, ValueError):
                return 0
            finally:
                conn.close()

    def update_active_signal_outcomes(self, price_lookup_fn: Any) -> dict[str, int]:
        """Grade every still-ACTIVE signal against real subsequent price
        action, closing SIGNAL_ONLY mode's real gap: record_generated_signal()
        inserts status="ACTIVE" and nothing ever updated it afterward, so
        get_admin_signal_analytics()'s win_rate/t1_hit_rate stayed stuck at
        0 forever regardless of how many real signals fired. This is a
        SIGNAL-ACCURACY track record (was the call right?), independent of
        whether any order was ever placed - it is NOT the same thing as
        core.live_readiness_checker's paper/live trade-count gate (that one
        specifically requires real fills in db/trades.db by design). Both
        are meaningful; this one is simply the only track record that can
        accumulate at all while running purely SIGNAL_ONLY.

        Args:
            price_lookup_fn: Callable[[symbol: str], float | None] - the
                caller's own LTP resolver. Returning None for a symbol skips
                it this pass (fails open - never crashes the caller).

        Returns:
            {"checked": n, "resolved": n, "expired": n} - resolved means a
            SL/target was actually hit this pass; expired means a stale
            ACTIVE signal (from a prior IST calendar day) was closed out at
            its last known price without ever hitting either.

        """
        checked = resolved = expired = 0
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                # Continue observing signals after the first barrier hit.
                # first_touch is immutable historical truth; status represents
                # the latest observed lifecycle state.
                cur.execute(
                    """SELECT * FROM system_signals
                       WHERE status IN (
                           'ACTIVE',
                           'TARGET_1_HIT',
                           'TARGET_2_HIT',
                           'SL_HIT',
                           'AMBIGUOUS'
                       )"""
                )
                active_rows = [dict(r) for r in cur.fetchall()]
                today_str = now_ist().date().isoformat()

                for row in active_rows:
                    checked += 1
                    symbol = row["symbol"]
                    direction = str(row["direction"]).upper()
                    entry = float(row["entry_price"])
                    sl = float(row["stop_loss"])
                    t1 = float(row["target_1"])
                    t2 = float(row["target_2"])

                    try:
                        price = price_lookup_fn(symbol)
                    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
                        price = None
                    if price is None:
                        continue
                    price = float(price)

                    is_call = direction in ("CALL", "BUY", "LONG")
                    if is_call:
                        hit_sl, hit_t1, hit_t2 = price <= sl, price >= t1, price >= t2
                    else:
                        hit_sl, hit_t1, hit_t2 = price >= sl, price <= t1, price <= t2

                    observed_at = now_ist().isoformat()
                    # Persist a lifecycle observation only when the
                    # observed barrier combination changes. This prevents
                    # repeated polling of the same already-crossed barrier
                    # from creating duplicate lifecycle events.
                    current_hits = (int(hit_sl), int(hit_t1), int(hit_t2))

                    cur.execute(
                        """SELECT hit_sl, hit_t1, hit_t2
                           FROM signal_outcome_events
                           WHERE signal_id = ?
                           ORDER BY event_id DESC
                           LIMIT 1""",
                        (row["signal_id"],),
                    )

                    previous_event = cur.fetchone()

                    previous_hits = (
                        (
                            int(previous_event["hit_sl"]),
                            int(previous_event["hit_t1"]),
                            int(previous_event["hit_t2"]),
                        )
                        if previous_event is not None
                        else None
                    )

                    new_event = previous_hits != current_hits

                    if new_event:
                        cur.execute(
                            """INSERT INTO signal_outcome_events
                               (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2)
                               VALUES (?, ?, ?, ?, ?, ?)""",
                            (
                                row["signal_id"],
                                observed_at,
                                price,
                                int(hit_sl),
                                int(hit_t1),
                                int(hit_t2),
                            ),
                        )

                    new_status = None
                    first_touch = None
                    confidence = "UNKNOWN"
                    # A single polling observation can cross multiple barriers.
                    # Never declare a win merely because T2 is checked first.
                    existing_first_touch = str(
                        row.get("first_touch") or ""
                    ).strip()

                    existing_first_touch_at = str(
                        row.get("first_touch_at") or ""
                    ).strip()

                    if sum((hit_sl, hit_t1, hit_t2)) > 1:
                        observed_touch = "AMBIGUOUS_SAME_OBSERVATION"
                        observed_confidence = "AMBIGUOUS"
                        new_status = "AMBIGUOUS"

                    elif hit_t2:
                        observed_touch = "T2"
                        observed_confidence = "EXACT_OBSERVATION"
                        new_status = "TARGET_2_HIT"

                    elif hit_t1:
                        observed_touch = "T1"
                        observed_confidence = "EXACT_OBSERVATION"
                        new_status = "TARGET_1_HIT"

                    elif hit_sl:
                        observed_touch = "SL"
                        observed_confidence = "EXACT_OBSERVATION"
                        new_status = "SL_HIT"

                    elif not existing_first_touch and row["created_date"] < today_str:
                        observed_touch = "UNRESOLVED"
                        observed_confidence = "UNRESOLVED"
                        new_status = "EXPIRED"
                        expired += 1

                    else:
                        observed_touch = ""
                        observed_confidence = "UNKNOWN"

                    # first_touch is write-once historical truth.
                    # A later SL/T1/T2 event must never replace it.
                    if existing_first_touch:
                        first_touch = existing_first_touch
                        confidence = str(
                            row.get("outcome_confidence") or "UNKNOWN"
                        )
                        first_touch_at = existing_first_touch_at

                    elif observed_touch:
                        first_touch = observed_touch
                        confidence = observed_confidence
                        first_touch_at = observed_at

                    else:
                        first_touch = ""
                        confidence = str(
                            row.get("outcome_confidence") or "UNKNOWN"
                        )
                        first_touch_at = ""

                    pnl_pct = round((price - entry) / entry * 100, 2) if is_call else round((entry - price) / entry * 100, 2)

                    if new_status is not None:
                        cur.execute(
                            """UPDATE system_signals
                               SET current_price = ?, status = ?, pnl_pct = ?,
                                   first_touch = ?, first_touch_at = ?, outcome_confidence = ?
                               WHERE signal_id = ?""",
                            (
                                price,
                                new_status,
                                pnl_pct,
                                first_touch or "",
                                first_touch_at,
                                confidence,
                                row["signal_id"],
                            ),
                        )
                        cur.execute(
                            "UPDATE user_deliveries SET current_price = ?, status = ?, pnl_pct = ? WHERE signal_id = ?",
                            (price, new_status, pnl_pct, row["signal_id"]),
                        )
                        if new_status != "EXPIRED":
                            resolved += 1
                    else:
                        cur.execute(
                            "UPDATE system_signals SET current_price = ? WHERE signal_id = ?",
                            (price, row["signal_id"]),
                        )
                        cur.execute(
                            "UPDATE user_deliveries SET current_price = ? WHERE signal_id = ?",
                            (price, row["signal_id"]),
                        )
                conn.commit()
            except Exception as ex:
                _log.error("Failed to update active signal outcomes: %s", ex)
            finally:
                conn.close()
        return {"checked": checked, "resolved": resolved, "expired": expired}

    def mark_order_placed(self, signal_id: str, placed: bool, username: str) -> bool:
        """Record that an admin/user actually placed a real (or paper) order
        off this specific signal - a manual complement to
        update_active_signal_outcomes()'s automatic price-based grading.
        That method answers "was the SIGNAL right"; this answers "did I
        actually act on it", which is what a manual/SIGNAL_ONLY admin needs
        for their own historical record of which signals they traded.

        Returns False if signal_id doesn't exist (caller should 404), True
        on a successful mark/unmark either way.
        """
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute("SELECT 1 FROM system_signals WHERE signal_id = ?", (signal_id,))
                if cur.fetchone() is None:
                    return False
                placed_at = now_ist().strftime("%Y-%m-%d %H:%M:%S") if placed else ""
                placed_by = username if placed else ""
                cur.execute(
                    "UPDATE system_signals SET order_placed = ?, order_placed_by = ?, order_placed_at = ? WHERE signal_id = ?",
                    (1 if placed else 0, placed_by, placed_at, signal_id),
                )
                conn.commit()
                return True
            except Exception as ex:
                _log.error("Failed to mark order_placed for %s: %s", signal_id, ex)
                return False
            finally:
                conn.close()

    def prune_old_signals(
        self, max_age_days: int, archive_dir: str | Path = _ROOT / "backups" / "signal_archives",
    ) -> int:
        """SQLite row-level retention for db/signals_history.db.

        core/data_governance.py's CleanupScheduler only knows how to prune
        file-glob categories (logs, audit jsonl, model pkl, report pdf,
        telemetry csv) - it has no way to reach into a database, and
        all_nse_scanner.py's 2,500+ stock universe scan means system_signals/
        user_deliveries would otherwise grow unbounded forever.

        Rather than a bare DELETE, every aged-out row is first written to a
        dated .zip archive under archive_dir (one JSON file per run, holding
        both the system_signals and their linked user_deliveries rows) so
        the history isn't actually lost - just moved out of the live,
        continuously-queried table. The archive is a plain file the admin
        can inspect, restore from, or delete by hand whenever they no longer
        want it; this method never deletes the archives themselves. If the
        archive write fails for any reason, the live rows are left alone -
        never delete without a confirmed backup on disk.

        Only already-resolved signals (status != ACTIVE) older than
        max_age_days are eligible; an ACTIVE signal is never archived or
        pruned regardless of age, since update_active_signal_outcomes()
        still needs it to grade a real outcome eventually.

        Returns the number of system_signals rows removed (0 if none aged
        out, if the archive write failed, or if max_age_days <= 0 disables
        pruning entirely).
        """
        if max_age_days <= 0:
            return 0
        cutoff = (now_ist().date() - timedelta(days=max_age_days)).isoformat()
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM system_signals WHERE created_date < ? AND status != 'ACTIVE'",
                    (cutoff,),
                )
                signal_rows = [dict(row) for row in cur.fetchall()]
                if not signal_rows:
                    return 0
                ids = [row["signal_id"] for row in signal_rows]
                placeholders = ",".join("?" * len(ids))
                cur.execute(f"SELECT * FROM user_deliveries WHERE signal_id IN ({placeholders})", ids)
                delivery_rows = [dict(row) for row in cur.fetchall()]

                try:
                    self._archive_signals(signal_rows, delivery_rows, archive_dir)
                except Exception as archive_ex:
                    _log.error(
                        "Failed to archive %d aging-out signal(s) - leaving them in place, not deleting: %s",
                        len(signal_rows), archive_ex,
                    )
                    return 0

                cur.execute(f"DELETE FROM user_deliveries WHERE signal_id IN ({placeholders})", ids)
                cur.execute(f"DELETE FROM system_signals WHERE signal_id IN ({placeholders})", ids)
                conn.commit()
                return len(ids)
            except Exception as ex:
                _log.error("Failed to prune old signals: %s", ex)
                return 0
            finally:
                conn.close()

    def _archive_signals(
        self, signal_rows: list[dict[str, Any]], delivery_rows: list[dict[str, Any]], archive_dir: str | Path,
    ) -> Path:
        """Writes aging-out rows to a timestamped .zip under archive_dir
        before prune_old_signals() deletes them from the live tables."""
        archive_path = Path(archive_dir)
        archive_path.mkdir(parents=True, exist_ok=True)
        stamp = now_ist().strftime("%Y%m%d_%H%M%S")
        zip_path = archive_path / f"signals_archive_{stamp}.zip"
        payload = json.dumps(
            {"archived_at": now_ist().isoformat(), "system_signals": signal_rows, "user_deliveries": delivery_rows},
            default=str,
        )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"signals_archive_{stamp}.json", payload)
        _log.info("Archived %d signal(s) to %s before pruning", len(signal_rows), zip_path)
        return zip_path

    def get_admin_signal_analytics(
        self,
        timeframe: str = "all",  # today, week, month, year, all
        category: str = "all",
        tier: str = "all",
        status: str = "all",
    ) -> dict[str, Any]:
        """Compute system-wide signal metrics, category accuracy, and historical logs."""
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

                # Fetch signals
                cur.execute(f"""
                    SELECT * FROM system_signals
                    WHERE {where_clause}
                    ORDER BY timestamp DESC
                """, params)
                rows = [dict(r) for r in cur.fetchall()]

                total_signals = len(rows)
                t1_hits = sum(1 for r in rows if r["status"] in ("TARGET_1_HIT", "TARGET_2_HIT"))
                t2_hits = sum(1 for r in rows if r["status"] == "TARGET_2_HIT")
                sl_hits = sum(1 for r in rows if r["status"] == "SL_HIT")
                active_signals = sum(1 for r in rows if r["status"] == "ACTIVE")

                # Previously defaulted to 100.0 when nothing had resolved yet
                # (0 T1 hits, 0 SL hits) - "100% win rate" is a misleading way
                # to present "no resolved signals yet".
                win_rate = round((t1_hits / max(t1_hits + sl_hits, 1)) * 100, 1) if (t1_hits + sl_hits) > 0 else 0.0
                contains_demo_data = any(bool(r.get("raw_data") and "is_seed_sample" in r["raw_data"]) for r in rows)
                t1_rate = round((t1_hits / max(total_signals, 1)) * 100, 1)
                t2_rate = round((t2_hits / max(total_signals, 1)) * 100, 1)
                avg_pnl = round(sum(r["pnl_pct"] for r in rows) / max(total_signals, 1), 2)
                orders_placed_count = sum(1 for r in rows if r.get("order_placed"))

                # Category breakdown
                cat_breakdown: dict[str, dict[str, Any]] = {}
                for r in rows:
                    c = r["category"]
                    if c not in cat_breakdown:
                        cat_breakdown[c] = {"total": 0, "t1_hits": 0, "sl_hits": 0, "avg_score": 0, "sum_score": 0}
                    cat_breakdown[c]["total"] += 1
                    cat_breakdown[c]["sum_score"] += r["score"]
                    if r["status"] in ("TARGET_1_HIT", "TARGET_2_HIT"):
                        cat_breakdown[c]["t1_hits"] += 1
                    elif r["status"] == "SL_HIT":
                        cat_breakdown[c]["sl_hits"] += 1

                for c, stats in cat_breakdown.items():
                    stats["avg_score"] = round(stats["sum_score"] / max(stats["total"], 1), 1)
                    stats["win_rate"] = round((stats["t1_hits"] / max(stats["t1_hits"] + stats["sl_hits"], 1)) * 100, 1)

                return {
                    "timeframe": timeframe,
                    "category": category,
                    "tier": tier,
                    "status": status,
                    "total_signals": total_signals,
                    "win_rate_pct": win_rate,
                    "t1_hit_rate_pct": t1_rate,
                    "t2_hit_rate_pct": t2_rate,
                    "active_signals": active_signals,
                    "average_pnl_pct": avg_pnl,
                    "orders_placed_count": orders_placed_count,
                    "category_breakdown": cat_breakdown,
                    "signals": rows,
                    "contains_demo_data": contains_demo_data,
                }
            except Exception as ex:
                _log.error("Failed to compute admin signal analytics: %s", ex)
                return {"error": str(ex), "signals": []}
            finally:
                conn.close()

    def get_user_received_signals(
        self,
        username: str,
        year: str = "all",
        month: str = "all",
        week: str = "all",
        day: str = "all",
        category: str = "all",
    ) -> dict[str, Any]:
        """Fetch personalized historical signal deliveries for a specific user."""
        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                conditions = ["ud.username = ?"]
                params: list[Any] = [username]

                if year != "all":
                    conditions.append("ud.delivery_year = ?")
                    params.append(year)
                if month != "all":
                    conditions.append("ud.delivery_month = ?")
                    params.append(month)
                if week != "all":
                    conditions.append("ud.delivery_week = ?")
                    params.append(week)
                if day != "all":
                    conditions.append("ud.delivery_date = ?")
                    params.append(day)
                if category != "all":
                    conditions.append("ud.category = ?")
                    params.append(category)

                where_clause = " AND ".join(conditions)

                # LEFT JOIN system_signals to surface raw_data's
                # is_seed_sample marker (see _seed_sample_history) - the
                # feed previously showed the same 12 hardcoded demo signals
                # to every fresh install with zero indication they weren't
                # real received signals.
                cur.execute(f"""
                    SELECT ud.*, ss.raw_data AS _signal_raw_data FROM user_deliveries ud
                    LEFT JOIN system_signals ss ON ud.signal_id = ss.signal_id
                    WHERE {where_clause}
                    ORDER BY ud.timestamp DESC
                """, params)
                rows = []
                any_demo = False
                for r in cur.fetchall():
                    row = dict(r)
                    raw = row.pop("_signal_raw_data", None)
                    is_demo = bool(raw and "is_seed_sample" in raw)
                    row["is_demo_data"] = is_demo
                    any_demo = any_demo or is_demo
                    rows.append(row)

                # Available filter options for the user
                cur.execute("SELECT DISTINCT delivery_year FROM user_deliveries WHERE username = ?", (username,))
                years = [r["delivery_year"] for r in cur.fetchall()]
                cur.execute("SELECT DISTINCT delivery_month FROM user_deliveries WHERE username = ?", (username,))
                months = [r["delivery_month"] for r in cur.fetchall()]
                cur.execute("SELECT DISTINCT category FROM user_deliveries WHERE username = ?", (username,))
                categories = [r["category"] for r in cur.fetchall()]

                return {
                    "username": username,
                    "total_received": len(rows),
                    "signals": rows,
                    "available_years": sorted(years, reverse=True),
                    "available_months": sorted(months, reverse=True),
                    "available_categories": categories,
                    "contains_demo_data": any_demo,
                }
            except Exception as ex:
                _log.error("Failed to fetch user signals for %s: %s", username, ex)
                return {"username": username, "total_received": 0, "signals": []}
            finally:
                conn.close()
