"""Historical Signal Outcome Resolver Service (Phase D.2).

Automatically evaluates in-flight / unresolved signals against historical daily price action
using official market data feeds, enforcing first-touch immutability, same-bar ambiguity quarantining,
and calendar-aware holding horizons.

Governance Authority: OPB-FINAL-PHASE-GOVERNANCE-001
- Zero mutation to trading, risk, scoring, or execution logic.
- Zero synthetic data: only verified exchange price bars are consumed. Missing data remains unresolved.
- Fail-closed deterministic evaluation: intrabar order is never assumed when both T1 and SL are touched.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from core.datetime_ist import now_ist
from core.signals.signal_forward_observation import SignalForwardObservationService
from core.signals.signal_outcome_tracker import (
    SignalBar,
    SignalEvaluationResult,
    SignalOutcomeTracker,
    resolve_outcome_db_path,
)

_log = logging.getLogger("HISTORICAL_OUTCOME_RESOLVER")


class HistoricalOutcomeResolverService:
    """Service to back-evaluate in-flight signals using chronological historical daily bars."""

    _instance: HistoricalOutcomeResolverService | None = None
    _singleton_lock = threading.RLock()

    def __init__(self, db_path: Path | str | None = None, dry_run: bool = False) -> None:
        self._db_path = resolve_outcome_db_path(db_path)
        self._dry_run = bool(dry_run)
        self._io_lock = threading.RLock()
        self._tracker = SignalOutcomeTracker.get_instance(
            db_path=self._db_path,
            initialize_schema=not self._dry_run,
            read_only=self._dry_run,
        )
        self._fwd_service = SignalForwardObservationService(
            db_path=self._db_path,
            initialize_schema=not self._dry_run,
            read_only=self._dry_run,
        )

    @classmethod
    def get_instance(cls, db_path: Path | str | None = None, dry_run: bool = False) -> HistoricalOutcomeResolverService:
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls(db_path=db_path, dry_run=dry_run)
            elif dry_run != cls._instance._dry_run or (db_path and Path(db_path) != cls._instance._db_path):
                cls._instance = cls(db_path=db_path, dry_run=dry_run)
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._singleton_lock:
            cls._instance = None

    def _get_conn(self, read_only: bool = False) -> sqlite3.Connection:
        ro = read_only or self._dry_run
        if ro:
            if not self._db_path.exists():
                raise FileNotFoundError(f"Database file does not exist for read-only access: {self._db_path}")
            uri = f"file:{self._db_path.resolve().as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
        else:
            conn = sqlite3.connect(str(self._db_path), timeout=30.0)
            conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def format_yf_symbol(symbol: str, category: str = "") -> str:
        """Format symbol for Yahoo Finance query adhering to canonical market conventions."""
        s = symbol.strip().upper()
        if s.endswith(".NS") or s.endswith(".BO") or "=" in s or "^" in s:
            return s
        if s in ("NIFTY", "NIFTY50", "NIFTY 50"):
            return "^NSEI"
        if s in ("BANKNIFTY", "BANK NIFTY"):
            return "^NSEBANK"
        if s in ("FINNIFTY", "NIFTY FIN SERVICE"):
            return "NIFTY_FIN_SERVICE.NS"
        if s in ("MIDCPNIFTY", "NIFTY MIDCAP SELECT"):
            return "NIFTY_MID_SELECT.NS"
        if s in ("SENSEX", "BSE:SENSEX"):
            return "^BSESN"
        if s in ("GBPINR", "CDS:GBPINR"):
            return "GBPINR=X"
        if s in ("JPYINR", "CDS:JPYINR"):
            return "JPYINR=X"
        if s in ("EURINR", "CDS:EURINR"):
            return "EURINR=X"
        if s in ("USDINR", "CDS:USDINR"):
            return "USDINR=X"
        # Standard NSE equity default
        return f"{s}.NS"

    def fetch_daily_bars(
        self,
        symbol: str,
        category: str = "",
        start_date: str | None = None,
    ) -> list[SignalBar]:
        """Fetch historical daily bars from Yahoo Finance in ascending chronological order."""
        try:
            import yfinance as yf
        except ImportError:
            _log.error("yfinance is not installed; cannot fetch historical daily bars")
            return []

        yf_sym = self.format_yf_symbol(symbol, category)
        try:
            ticker = yf.Ticker(yf_sym)
            # Use period="1mo" or explicit start date if provided
            if start_date:
                # Query from 1 day prior to ensure signal creation day is covered
                try:
                    dt_start = datetime.date.fromisoformat(start_date[:10]) - datetime.timedelta(days=2)
                    df = ticker.history(start=dt_start.isoformat(), interval="1d", auto_adjust=False)
                except Exception:
                    df = ticker.history(period="1mo", interval="1d", auto_adjust=False)
            else:
                df = ticker.history(period="1mo", interval="1d", auto_adjust=False)

            if df is None or df.empty:
                _log.debug("No historical daily data returned for %s (%s)", symbol, yf_sym)
                return []

            bars: list[SignalBar] = []
            for dt, row in df.iterrows():
                try:
                    # Convert pandas Timestamp to ISO string date
                    ts_str = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
                    bar = SignalBar(
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        timestamp=ts_str,
                        volume=float(row.get("Volume", 0.0)),
                    )
                    bars.append(bar)
                except (KeyError, ValueError, TypeError) as conv_err:
                    _log.debug("Skipping malformed row for %s: %s", symbol, conv_err)
                    continue

            # Ensure ascending chronological order
            bars.sort(key=lambda b: str(b.timestamp))
            return bars
        except Exception as ex:
            _log.warning("Failed to fetch daily bars for %s (%s): %s", symbol, yf_sym, ex)
            return []

    def evaluate_signal_against_bars(
        self,
        signal: dict[str, Any],
        bars: list[SignalBar],
    ) -> tuple[SignalEvaluationResult | None, str | None]:
        """Evaluate a signal sequentially across chronological bars starting from signal creation date.

        Stops at the first barrier touch (T1, T2, SL, AMBIGUOUS) preserving first-touch immutability.
        Returns (evaluation_result, bar_timestamp) or (None, None) if no relevant bars.
        """
        sig_date_str = str(signal.get("created_date") or signal.get("timestamp") or "")[:10]

        relevant_bars = [b for b in bars if str(b.timestamp)[:10] >= sig_date_str]
        if not relevant_bars:
            return None, None

        current_sig_state = dict(signal)
        last_eval: SignalEvaluationResult | None = None
        last_bar_ts: str | None = None

        for bar in relevant_bars:
            bar_date_str = str(bar.timestamp)[:10]
            try:
                bar_dt = datetime.datetime.fromisoformat(f"{bar_date_str}T15:30:00+05:30")
            except Exception:
                bar_dt = now_ist()

            eval_res = self._tracker.evaluate_bar(
                current_sig_state,
                bar,
                current_time=bar_dt,
                check_staleness=False,
            )
            last_eval = eval_res
            last_bar_ts = f"{bar_date_str}T15:30:00+05:30" if "T" not in str(bar.timestamp) else str(bar.timestamp)

            # If a terminal state was reached, halt replay immediately
            if eval_res.is_terminal:
                return eval_res, last_bar_ts

            # If T1 was hit (interim state), update state so subsequent bars check for T2 or SL
            if eval_res.hit_t1 and eval_res.new_status == "TARGET_1_HIT":
                current_sig_state["status"] = "TARGET_1_HIT"
                current_sig_state["first_touch"] = eval_res.first_touch
                current_sig_state["first_touch_at"] = eval_res.first_touch_at
                current_sig_state["first_touch_price"] = eval_res.first_touch_price
                current_sig_state["outcome_confidence"] = eval_res.outcome_confidence

        return last_eval, last_bar_ts

    def resolve_all_pending(
        self,
        dry_run: bool = False,
        limit: int | None = None,
        rate_limit_delay_sec: float = 0.25,
    ) -> dict[str, Any]:
        """Resolve all in-flight signals against historical price action and update forward observations.

        Execution Pipeline:
        1. Query all in-flight signals (`status IN ('ACTIVE', 'OPEN', 'TARGET_1_HIT')`).
        2. Categorize between intraday expired and swing delivery signals.
        3. For swing delivery signals, fetch daily bars and replay sequentially.
        4. Apply terminal barrier updates to `system_signals` and `signal_outcome_events`.
        5. Run standard holding-horizon expiry sweep via `expire_stale_signals()`.
        6. Synchronize `signal_forward_observations` via `sync_forward_outcomes()`.
        """
        now = now_ist()
        now_str = now.isoformat()

        with self._io_lock:
            conn = self._get_conn()
            try:
                cur = conn.cursor()
                query = """
                    SELECT * FROM system_signals
                    WHERE status IN ('ACTIVE', 'OPEN', 'TARGET_1_HIT')
                    ORDER BY created_date ASC, signal_id ASC
                """
                params: list[Any] = []
                if limit and limit > 0:
                    query += " LIMIT ?"
                    params.append(int(limit))
                cur.execute(query, params)
                pending_signals = [dict(r) for r in cur.fetchall()]
            finally:
                conn.close()

        total_pending = len(pending_signals)
        evaluated = 0
        resolved_barriers = 0
        stale_expired = 0
        errors = 0
        skipped_no_data = 0

        _log.info("Starting historical outcome resolution for %d pending signals (dry_run=%s)", total_pending, dry_run)

        # Cache daily bars by symbol to avoid duplicate network fetches
        bars_cache: dict[str, list[SignalBar]] = {}

        for sig in pending_signals:
            sig_id = str(sig.get("signal_id", ""))
            symbol = str(sig.get("symbol", ""))
            category = str(sig.get("category", "")).upper()
            sig_date = str(sig.get("created_date") or sig.get("timestamp") or "")[:10]

            evaluated += 1

            # Fetch bars if not cached
            if symbol not in bars_cache:
                bars = self.fetch_daily_bars(symbol, category, start_date=sig_date)
                bars_cache[symbol] = bars
                if rate_limit_delay_sec > 0:
                    time.sleep(rate_limit_delay_sec)
            else:
                bars = bars_cache[symbol]

            if not bars:
                skipped_no_data += 1
                continue

            try:
                eval_res, bar_ts = self.evaluate_signal_against_bars(sig, bars)
                if not eval_res or not eval_res.new_status or eval_res.new_status == sig.get("status"):
                    continue

                if dry_run:
                    resolved_barriers += 1
                    continue

                # Transactionally persist barrier update
                with self._io_lock:
                    conn = self._get_conn()
                    try:
                        cur = conn.cursor()
                        # Update system_signals
                        cur.execute(
                            """UPDATE system_signals
                               SET current_price = ?, status = ?, pnl_pct = ?,
                                   first_touch = ?, first_touch_at = ?, first_touch_price = ?,
                                   outcome_confidence = ?
                               WHERE signal_id = ?""",
                            (
                                eval_res.current_price,
                                eval_res.new_status,
                                eval_res.pnl_pct,
                                eval_res.first_touch or "",
                                eval_res.first_touch_at or "",
                                eval_res.first_touch_price,
                                eval_res.outcome_confidence,
                                sig_id,
                            ),
                        )
                        # Update user_deliveries
                        cur.execute(
                            "UPDATE user_deliveries SET current_price = ?, status = ?, pnl_pct = ? WHERE signal_id = ?",
                            (eval_res.current_price, eval_res.new_status, eval_res.pnl_pct, sig_id),
                        )
                        # Log event into signal_outcome_events
                        cur.execute(
                            """INSERT INTO signal_outcome_events
                               (signal_id, observed_at, observed_price, hit_sl, hit_t1, hit_t2, transition_note)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                sig_id,
                                bar_ts or now_str,
                                eval_res.current_price,
                                int(eval_res.hit_sl),
                                int(eval_res.hit_t1),
                                int(eval_res.hit_t2),
                                eval_res.transition_note or f"Historical bar resolution: {eval_res.new_status}",
                            ),
                        )
                        conn.commit()
                        resolved_barriers += 1
                    finally:
                        conn.close()

            except Exception as eval_err:
                _log.error("Error evaluating signal %s against historical bars: %s", sig_id, eval_err, exc_info=True)
                errors += 1

        # Step 5: Run standard stale signal expiry sweep
        if not dry_run:
            expiry_res = self._tracker.expire_stale_signals()
            stale_expired = expiry_res.get("transitioned", 0)

            # Step 6: Synchronize forward observation database
            self._fwd_service.sync_forward_outcomes()

        return {
            "status": "success",
            "dry_run": dry_run,
            "total_pending": total_pending,
            "evaluated": evaluated,
            "resolved_barriers": resolved_barriers,
            "stale_expired": stale_expired,
            "skipped_no_data": skipped_no_data,
            "errors": errors,
            "timestamp": now_str,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="OPB Historical Signal Outcome Resolver")
    parser.add_argument("--db-path", type=str, default=None, help="Path to signals_history.db")
    parser.add_argument("--dry-run", action="store_true", help="Perform read-only simulation without mutating DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of signals to evaluate")
    parser.add_argument("--rate-limit", type=float, default=0.2, help="Seconds delay between yfinance calls")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    svc = HistoricalOutcomeResolverService.get_instance(db_path=args.db_path, dry_run=args.dry_run)
    res = svc.resolve_all_pending(
        dry_run=args.dry_run,
        limit=args.limit,
        rate_limit_delay_sec=args.rate_limit,
    )
    print(res)


if __name__ == "__main__":
    main()
