import datetime
from datetime import timezone
from typing import Callable
import logging

logger = logging.getLogger(__name__)

# Standard IST Offset: UTC + 5:30
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

class TimeProvider:
    """
    Authoritative time source for the entire trading system.
    Prevents time-drift and ensures consistency across signals, 
    risk checks, and order execution.
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
        # If the provided function returns a naive datetime, we force it to IST
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

# Singleton instance for easy import
time_provider = TimeProvider()
