import datetime
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Standard IST Offset: UTC + 5:30
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# ── NTP Clock Sync ───────────────────────────────────────────────────────────

@dataclass
class NTPStatus:
    """Result of an NTP synchronization check."""
    ntp_time: float = 0.0        # NTP server timestamp
    system_time: float = 0.0     # Local system timestamp
    drift_seconds: float = 0.0   # system - ntp (positive = system ahead)
    drift_acceptable: bool = True
    server_reachable: bool = True
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ntp_time": round(self.ntp_time, 3),
            "system_time": round(self.system_time, 3),
            "drift_seconds": round(self.drift_seconds, 3),
            "drift_acceptable": self.drift_acceptable,
            "server_reachable": self.server_reachable,
            "error": self.error,
        }


class NTPClockSync:
    """NTP-based clock synchronization monitoring for the trading platform.

    Periodically queries NTP servers to detect system clock drift.
    Drift beyond MAX_DRIFT_SECONDS triggers warnings but does NOT
    automatically adjust the system clock (OS-level NTP daemon required
    for adjustment).

    Config:
        ntp_servers: list of NTP server hostnames (default:
                     ["pool.ntp.org", "time.google.com", "time.windows.com"])
        ntp_timeout: query timeout in seconds (default 5)
        ntp_max_drift: maximum acceptable drift in seconds (default 2)
        ntp_check_interval: interval between checks in seconds (default 3600)
    """

    DEFAULT_SERVERS = ["pool.ntp.org", "time.google.com", "time.windows.com"]
    MAX_DRIFT_SECONDS = 2.0
    TIMEOUT = 5

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._servers = list(cfg.get("ntp_servers", self.DEFAULT_SERVERS)) if cfg else list(self.DEFAULT_SERVERS)
        self._timeout = float(cfg.get("ntp_timeout", self.TIMEOUT)) if cfg else self.TIMEOUT
        self._max_drift = float(cfg.get("ntp_max_drift", self.MAX_DRIFT_SECONDS)) if cfg else self.MAX_DRIFT_SECONDS
        self._lock = threading.RLock()
        self._last_status: NTPStatus | None = None
        self._drift_history: list[float] = []
        self._max_history = 100

    def check_sync(self, server: str | None = None) -> NTPStatus:
        """Query an NTP server and compute drift."""
        try:
            import ntplib
            client = ntplib.NTPClient()
            target = server or self._servers[0]
            response = client.request(target, timeout=self._timeout, version=4)
            ntp_time = response.tx_time
            sys_time = time.time()
            drift = sys_time - ntp_time

            status = NTPStatus(
                ntp_time=ntp_time,
                system_time=sys_time,
                drift_seconds=drift,
                drift_acceptable=abs(drift) <= self._max_drift,
                server_reachable=True,
            )
        except ImportError:
            status = NTPStatus(
                error="ntplib not installed (pip install ntplib)",
                server_reachable=False,
            )
        except Exception as exc:
            # Try next server or report error
            status = NTPStatus(
                error=str(exc),
                server_reachable=False,
            )

        with self._lock:
            self._last_status = status
            if status.server_reachable:
                self._drift_history.append(status.drift_seconds)
                if len(self._drift_history) > self._max_history:
                    self._drift_history.pop(0)

        return status

    @property
    def last_status(self) -> NTPStatus | None:
        return self._last_status

    @property
    def drift_ok(self) -> bool:
        """True if the last check was within acceptable drift."""
        return self._last_status is not None and self._last_status.drift_acceptable

    @property
    def avg_drift(self) -> float:
        """Average drift from history, or 0 if no data."""
        with self._lock:
            if not self._drift_history:
                return 0.0
            return sum(self._drift_history) / len(self._drift_history)

    def get_stats(self) -> dict[str, Any]:
        """Return NTP sync statistics."""
        with self._lock:
            return {
                "servers": self._servers,
                "max_drift_seconds": self._max_drift,
                "last_status": self._last_status.to_dict() if self._last_status else None,
                "drift_ok": self.drift_ok,
                "avg_drift_seconds": round(self.avg_drift, 3),
                "n_checks": len(self._drift_history),
            }


# ── NTP-aware TimeProvider ───────────────────────────────────────────────────

_ntp_sync: NTPClockSync | None = None
_ntp_lock = threading.RLock()


def get_ntp_sync(cfg: dict[str, Any] | None = None) -> NTPClockSync:
    """Get the global NTP clock sync singleton."""
    global _ntp_sync
    with _ntp_lock:
        if _ntp_sync is None:
            _ntp_sync = NTPClockSync(cfg)
        return _ntp_sync


def check_ntp_drift() -> NTPStatus:
    """Convenience: check NTP drift using the singleton."""
    return get_ntp_sync().check_sync()


# ── TimeProvider (original, enhanced with NTP awareness) ─────────────────────

class TimeProvider:
    """
    Authoritative time source for the entire trading system.
    Prevents time-drift and ensures consistency across signals,
    risk checks, and order execution.

    Enhanced with NTP clock synchronization monitoring.
    """

    _now_fn: Callable[[], datetime.datetime] = datetime.datetime.now

    @classmethod
    def set_now_fn(cls, fn: Callable[[], datetime.datetime]):
        """
        Allows overriding the time source for deterministic backtesting
        or simulation.
        """
        cls._now_fn = fn

    @classmethod
    def now(cls) -> datetime.datetime:
        """Returns the current time in IST."""
        dt = cls._now_fn()
        if dt.tzinfo is None:
            return dt.replace(tzinfo=IST)
        return dt.astimezone(IST)

    @classmethod
    def today(cls) -> datetime.date:
        """Returns the current date in IST."""
        return cls.now().date()

    @classmethod
    def format_ts(cls, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
        """Standardized timestamp formatting."""
        return cls.now().strftime(fmt)

    @classmethod
    def check_drift(cls) -> NTPStatus:
        """Check system clock drift against NTP servers."""
        return check_ntp_drift()


# Singleton instance for easy import
time_provider = TimeProvider()


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m core.time_provider")
    ap.add_argument("--check-ntp", action="store_true", help="Check NTP drift")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    if args.check_ntp:
        status = check_ntp_drift()
        if args.json:
            import json
            print(json.dumps(status.to_dict(), indent=2))
        else:
            icon = "[OK]" if status.drift_acceptable else "[X]"
            print(f"{icon} NTP Drift: {status.drift_seconds:.3f}s")
            if not status.server_reachable:
                print(f"    Server unreachable: {status.error}")
            print(f"    Max acceptable: {get_ntp_sync()._max_drift}s")
        return

    # Default: show current time
    print(f"IST Time: {time_provider.format_ts()}")
    print(f"IST Date: {time_provider.today()}")


if __name__ == "__main__":
    _cli()
