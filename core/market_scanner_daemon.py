"""Real-Time Continuous Market Scanner Daemon (v3.5 Institutional Edition).

Operates during live NSE market hours (09:15 AM - 15:30 PM IST, Mon-Fri):
- Dynamically loads and synchronizes all 2,500+ NSE stocks daily
- Scans against the 16 Quantitative Strategies Engine in high-throughput parallel threads
- Dispatches real-time Telegram and HTML Gmail alerts immediately to all authorized users
- Automatically sleeps outside trading hours and resumes at 09:15 AM IST
- Provides --force-run mode for after-hours testing and demonstration
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import time as dtime
from pathlib import Path

# Add project root to sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.all_nse_scanner import AllNSEScanner
from core.datetime_ist import now_ist
from core.logging import get_logger

_log = get_logger("MARKET_DAEMON")

MARKET_OPEN_TIME = dtime(9, 15)
MARKET_CLOSE_TIME = dtime(15, 30)


def is_market_hours(force_run: bool = False) -> bool:
    """Check if current time is within any supported Indian market session (Equity, Derivatives, Currencies, Commodities)."""
    if force_run:
        return True
    now = now_ist()
    # Check weekday (0 = Mon, 4 = Fri, 5/6 = Sat/Sun)
    if now.weekday() >= 5:
        try:
            from core.exchange_calendar_engine import get_calendar_engine
            if not get_calendar_engine().is_muhurat_trading(now.date()):
                return False
        except Exception:
            return False
    try:
        from core.exchange_calendar_engine import get_calendar_engine, is_category_session_open
        cal = get_calendar_engine()
        if not cal.is_market_day(now.date()) and not cal.is_muhurat_trading(now.date()):
            return False
        for cat in ("EQUITY", "INDEX_OPTIONS", "CURRENCIES", "COMMODITIES"):
            if is_category_session_open(cat, now):
                return True
        return False
    except Exception:
        cur_time = now.time()
        return dtime(9, 0) <= cur_time <= dtime(23, 30)


def run_continuous_daemon(
    interval_secs: int = 60,
    symbols_limit: int | None = None,
    force_run: bool = False,
    max_workers: int = 20,
) -> None:
    """Run continuous market scanning daemon."""
    print("=" * 75)
    print("GAURAV REAL-TIME CONTINUOUS NSE MARKET SCANNER DAEMON")
    print(f"Started At: {now_ist().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"Scan Interval: {interval_secs}s | Workers: {max_workers} | Force Run: {force_run}")
    print("=" * 75)

    daemon_cfg = {"SCANNER_FORCE_RUN": True} if force_run else {}
    scanner = AllNSEScanner(max_workers=max_workers, cfg=daemon_cfg)

    # Load universe
    universe = scanner.load_nse_universe()
    _log.info("Initialized universe with %d active NSE stocks.", len(universe))

    iteration = 0
    while True:
        iteration += 1
        now = now_ist()
        in_market = is_market_hours(force_run)

        if not in_market:
            _log.info("[STANDBY] All market sessions currently CLOSED (Sessions: Equity 09:15-15:30, Derivatives 09:15-15:40, Currencies 09:00-17:00, Commodities 09:00-23:30 IST). Sleeping for 60s...")
            try:
                from core.signals.signal_outcome_tracker import SignalOutcomeTracker
                SignalOutcomeTracker.get_instance().run_stale_signal_expiry_sweep()
            except Exception as e:
                _log.debug("[STANDBY] Expiry sweep skipped: %s", e)
            time.sleep(60)
            continue

        _log.info("[CYCLE #%d] Running parallel 16-strategy scan across NSE universe at %s IST...",
                  iteration, now.strftime("%H:%M:%S"))

        try:
            signals = scanner.scan_universe(symbols_limit=symbols_limit, send_alerts=True)
            _log.info("[CYCLE #%d] Scan complete. Found %d actionable signal(s).", iteration, len(signals))
            for s in signals:
                _log.info(">> DISPATCHED: %s %s | Score: %d/100 (%s) | LTP: Rs %.2f",
                          s.direction, s.symbol, s.score, s.tier, s.price)
        except Exception as e:
            _log.error("[ERROR] Exception during scan cycle #%d: %s", iteration, e, exc_info=True)

        _log.info("Sleeping for %d seconds until next scan cycle...\n", interval_secs)
        time.sleep(interval_secs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-Time Continuous Market Scanner Daemon")
    parser.add_argument("--interval", type=int, default=60, help="Interval between scan cycles in seconds (default: 60)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of stocks to scan (e.g. 50, 100)")
    parser.add_argument("--force", action="store_true", help="Force run continuous scan even outside market hours")
    parser.add_argument("--workers", type=int, default=20, help="Number of parallel worker threads (default: 20)")

    args = parser.parse_args()
    run_continuous_daemon(
        interval_secs=args.interval,
        symbols_limit=args.limit,
        force_run=args.force,
        max_workers=args.workers,
    )
