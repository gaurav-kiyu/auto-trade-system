"""
FII/DII Institutional Flow Tracker (v2.45 Item 1).

Fetches NSE provisional FII/DII cash-market data, caches it locally, and
provides a score adjustment based on net institutional flow vs the signal
direction.

Public API
----------
    FIIDIITracker(cfg)               - main class
    FIIDIITracker.get_latest()       - FIIDIIData | None (from cache or fetch)
    FIIDIITracker.score_adjustment() - int (±5, 0 if disabled or no data)
    FIIDIITracker.start_background_refresh() - non-blocking daemon thread
    FIIDIITracker.get_eod_summary()  - "FII: ₹{X}Cr | DII: ₹{Y}Cr"

Config keys
-----------
    fii_dii_enabled        : bool   default false
    fii_cache_hours        : float  default 24.0
    fii_score_threshold    : float  default 2000.0  (Crores)
    fii_score_bonus        : int    default 5
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_CACHE_FILE   = Path("data/fii_dii_cache.json")
_NSE_HEADERS  = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}
# NSE provisional FII/DII cash-market URL (publishes ~17:00 IST)
_NSE_FII_URL  = "https://www.nseindia.com/api/fiidiiTradeReact"


# ── Dataclass ─────────────────────────────────────────────────────────────────

@dataclass
class FIIDIIData:
    date:        str
    fii_net:     float   # Crores; +ve = net buying, -ve = net selling
    dii_net:     float   # Crores; +ve = net buying, -ve = net selling
    fetched_at:  float   # time.time() when cached


# ── Tracker ───────────────────────────────────────────────────────────────────

class FIIDIITracker:
    """Thread-safe FII/DII data fetcher with local JSON cache."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self._cfg          = cfg or {}
        self._lock         = threading.RLock()
        self._data: FIIDIIData | None = None
        self._last_fetch   = 0.0
        self._bg_thread: threading.Thread | None = None
        self._stop_event   = threading.Event()
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._load_cache()

    # ── Cache I/O ─────────────────────────────────────────────────────────

    def _load_cache(self) -> None:
        try:
            if _CACHE_FILE.is_file():
                raw = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
                self._data = FIIDIIData(**raw)
                self._last_fetch = float(raw.get("fetched_at", 0))
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            _log.warning("[FII] cache load failed: %s", exc)
        except Exception as exc:
            _log.warning("[FII] cache load failed (unexpected: %s): %s", type(exc).__name__, exc)

    def _save_cache(self, d: FIIDIIData) -> None:
        try:
            _CACHE_FILE.write_text(
                json.dumps(asdict(d), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            _log.warning("[FII] cache save failed: %s", exc)
        except Exception as exc:
            _log.warning("[FII] cache save failed (unexpected: %s): %s", type(exc).__name__, exc)

    # ── Remote fetch ──────────────────────────────────────────────────────

    def _fetch_remote(self) -> FIIDIIData | None:
        try:
            import requests
            sess = requests.Session()
            # Warm up NSE session cookie
            sess.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=5)
            resp = sess.get(_NSE_FII_URL, headers=_NSE_HEADERS, timeout=8)
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list) or not rows:
                return None
            # Latest row is index 0; columns vary by NSE version
            row = rows[0]
            fii_net = float(
                row.get("netTurnOver") or row.get("fiiNetTurnOver") or 0.0
            )
            dii_net = float(
                row.get("diiNetTurnOver") or 0.0
            )
            date_str = str(row.get("date") or row.get("tradeDate") or "")
            data = FIIDIIData(
                date=date_str,
                fii_net=fii_net,
                dii_net=dii_net,
                fetched_at=time.time(),
            )
            _log.info("[FII] fetched: FII=%+.0fCr DII=%+.0fCr (%s)", fii_net, dii_net, date_str)
            return data
        except (ValueError, TypeError, KeyError, AttributeError, ConnectionError, TimeoutError, OSError) as exc:
            _log.warning("[FII] remote fetch failed: %s", exc)
            return None
        except Exception as exc:
            _log.warning("[FII] remote fetch failed (unexpected: %s): %s", type(exc).__name__, exc)
            return None

    # ── Public API ────────────────────────────────────────────────────────

    def get_latest(self) -> FIIDIIData | None:
        """Return cached data; refresh if stale."""
        if not self._cfg.get("fii_dii_enabled", False):
            return None
        cache_hours = float(self._cfg.get("fii_cache_hours", 24.0))
        with self._lock:
            age = time.time() - self._last_fetch
            if self._data is not None and age < cache_hours * 3600:
                return self._data
        # Stale - try remote
        fresh = self._fetch_remote()
        if fresh is not None:
            with self._lock:
                self._data = fresh
                self._last_fetch = fresh.fetched_at
            self._save_cache(fresh)
            return fresh
        # Return stale cache rather than None
        with self._lock:
            return self._data

    def score_adjustment(self, direction: str) -> int:
        """
        Return score delta (+5 / 0 / -5) based on FII flow vs trade direction.

        Logic:
            fii_net > +threshold AND direction=CALL → +bonus
            fii_net < -threshold AND direction=PUT  → +bonus
            fii_net < -threshold AND direction=CALL → -bonus (divergence)
            fii_net > +threshold AND direction=PUT  → -bonus (divergence)
        """
        if not self._cfg.get("fii_dii_enabled", False):
            return 0
        data = self.get_latest()
        if data is None:
            return 0
        threshold = float(self._cfg.get("fii_score_threshold", 2000.0))
        bonus     = int(self._cfg.get("fii_score_bonus", 5))
        d         = direction.upper()
        fii       = data.fii_net
        if fii > threshold:
            return bonus if d == "CALL" else -bonus
        if fii < -threshold:
            return bonus if d == "PUT" else -bonus
        return 0

    def start_background_refresh(self) -> None:
        """Launch a daemon thread that refreshes data every cache_hours."""
        if not self._cfg.get("fii_dii_enabled", False):
            return
        if self._bg_thread and self._bg_thread.is_alive():
            return

        def _loop() -> None:
            while not self._stop_event.is_set():
                cache_hours = float(self._cfg.get("fii_cache_hours", 24.0))
                fresh = self._fetch_remote()
                if fresh is not None:
                    with self._lock:
                        self._data = fresh
                        self._last_fetch = fresh.fetched_at
                    self._save_cache(fresh)
                self._stop_event.wait(timeout=cache_hours * 3600)

        self._bg_thread = threading.Thread(
            target=_loop, daemon=True, name="fii_dii_refresh"
        )
        self._bg_thread.start()

    def stop(self) -> None:
        """Signal background thread to stop."""
        self._stop_event.set()

    def get_eod_summary(self) -> str:
        """Return a one-line EOD string for Telegram."""
        if not self._cfg.get("fii_dii_enabled", False):
            return ""
        data = self.get_latest()
        if data is None:
            return "FII/DII: data unavailable"
        R = chr(0x20B9)
        return (
            f"FII: {R}{data.fii_net:+,.0f}Cr  |  DII: {R}{data.dii_net:+,.0f}Cr"
        )
