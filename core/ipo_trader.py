"""IPO / FPO / OFS / QIP Trader (v2.57.0) — Primary & secondary issue trading engine.

Supports trading in primary market events with:
  - IPO subscription monitoring and allocation tracking
  - FPO / OFS / QIP issue participation
  - Listing-day trading signals
  - Price band & grey market premium tracking
  - Config-driven event tracking

Config keys:
    IPO_ENABLED: true/false
    IPO_MAP: issue definitions (symbol, issuer, bands, dates)
    IPO_PRIORITY: scan order
    IPO_SL_PCT / IPO_TARGET_PCT: listing-day risk thresholds
    IPO_DEFAULT_QTY: default subscription quantity
    IPO_MAX_ACTIVE_ISSUES: max concurrent tracked issues

Usage:
    from core.ipo_trader import IPOTrader, run_ipo_trader
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.reentry_evaluator import build_reentry_trackers

_log = logging.getLogger(__name__)

_DEFAULT_IPO_PRIORITY = []
_DEFAULT_SL_PCT = 0.85
_DEFAULT_TARGET_PCT = 1.20
_DEFAULT_MAX_ACTIVE = 10
_DEFAULT_QTY = 1
_IPO_HOURS = (9, 15)  # subscription window: 09:00-15:30 on working days
_IPO_CLOSE = (15, 30)

# Issue status lifecycle
ISSUE_STATUS_UPCOMING = "UPCOMING"
ISSUE_STATUS_OPEN = "OPEN"
ISSUE_STATUS_CLOSED = "CLOSED"
ISSUE_STATUS_ALLOTTED = "ALLOTTED"
ISSUE_STATUS_LISTED = "LISTED"
ISSUE_STATUS_CANCELLED = "CANCELLED"


class IPOTradePosition:
    """An IPO / FPO / OFS / QIP position or tracked issue.

    Attributes:
        symbol: Issue symbol (e.g. "XYZIPO").
        issue_type: IPO, FPO, OFS, QIP, or RIGHTS.
        issuer_name: Company / issuer name.
        direction: BUY (subscription) or SELL (OFS exit).
        qty: Number of shares applied / allotted.
        entry_price: Bid price (for IPO = upper price band).
        current_price: Latest market price (post-listing).
        listing_price: Listing-day opening price.
        price_band_low: Lower price band.
        price_band_high: Upper price band.
        lot_size: Minimum lot size.
        status: Issue lifecycle status.
        grey_market_premium: Estimated GMP percentage.
        allotment_date: Expected allotment date.
        listing_date: Expected listing date.
        entry_time: Timestamp of tracking start.
    """

    def __init__(
        self,
        symbol: str,
        issue_type: str = "IPO",
        issuer_name: str = "",
        direction: str = "BUY",
        qty: int = 1,
        entry_price: float = 0.0,
        current_price: float = 0.0,
        listing_price: float = 0.0,
        price_band_low: float = 0.0,
        price_band_high: float = 0.0,
        lot_size: int = 1,
        status: str = ISSUE_STATUS_UPCOMING,
        grey_market_premium: float = 0.0,
        allotment_date: str = "",
        listing_date: str = "",
        entry_time: float = 0.0,
        asset_class: str = "IPO",
        score: int = 0,
        reason: str = "",
    ) -> None:
        self.symbol = symbol
        self.issue_type = issue_type
        self.issuer_name = issuer_name
        self.direction = direction
        self.qty = qty
        self.entry_price = entry_price
        self.current_price = current_price
        self.listing_price = listing_price
        self.price_band_low = price_band_low
        self.price_band_high = price_band_high
        self.lot_size = lot_size
        self.status = status
        self.grey_market_premium = grey_market_premium
        self.allotment_date = allotment_date
        self.listing_date = listing_date
        self.entry_time = entry_time
        self.asset_class = asset_class
        self.score = score
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "issue_type": self.issue_type,
            "issuer_name": self.issuer_name,
            "direction": self.direction,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "listing_price": self.listing_price,
            "price_band": f"{self.price_band_low}–{self.price_band_high}",
            "lot_size": self.lot_size,
            "status": self.status,
            "grey_market_premium": self.grey_market_premium,
            "allotment_date": self.allotment_date,
            "listing_date": self.listing_date,
            "asset_class": self.asset_class,
            "score": self.score,
            "reason": self.reason,
        }

    @property
    def expected_listing_gain_pct(self) -> float:
        """Estimated listing gain % based on grey market premium or price band mid."""
        if self.entry_price <= 0:
            return 0.0
        if self.listing_price > 0:
            return (self.listing_price - self.entry_price) / self.entry_price
        # Estimate from grey market premium
        mid_price = (self.price_band_low + self.price_band_high) / 2
        if mid_price <= 0:
            return 0.0
        if self.grey_market_premium != 0:
            return self.grey_market_premium
        return 0.0


class IPOTrader:
    """IPO / FPO / OFS / QIP trading and tracking engine.

    Manages primary market issue tracking with subscription monitoring,
    allotment tracking, listing-day execution, and config-driven risk.
    Thread-safe.
    """

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        send_fn: Callable | None = None,
        get_price_fn: Callable[[str], float | None] | None = None,
        execute_entry_fn: Callable | None = None,
        execute_exit_fn: Callable | None = None,
    ):
        self._cfg = cfg or {}
        self._send_fn = send_fn or (lambda msg, critical=False, **kw: None)
        self._get_price_fn = get_price_fn or (lambda sym: None)
        self._execute_entry_fn = execute_entry_fn
        self._execute_exit_fn = execute_exit_fn
        self._lock = threading.RLock()
        self._positions: dict[str, IPOTradePosition] = {}
        self._running = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Build tracked issue symbols
        self._symbols = self._build_symbols()
        self._reentry_trackers = build_reentry_trackers(self._symbols)

        # Risk parameters
        self._sl_pct = float(self._cfg.get("IPO_SL_PCT", _DEFAULT_SL_PCT))
        self._target_pct = float(self._cfg.get("IPO_TARGET_PCT", _DEFAULT_TARGET_PCT))
        self._max_active = int(self._cfg.get("IPO_MAX_ACTIVE_ISSUES", _DEFAULT_MAX_ACTIVE))
        self._default_qty = int(self._cfg.get("IPO_DEFAULT_QTY", _DEFAULT_QTY))

        _log.info("[IPO] Loaded %d tracked issues", len(self._symbols))

    def _build_symbols(self) -> list[str]:
        if not self._cfg.get("IPO_ENABLED", False):
            return []
        asset_map = self._cfg.get("IPO_MAP", {})
        priority = self._cfg.get("IPO_PRIORITY", _DEFAULT_IPO_PRIORITY)
        if priority:
            return [sym for sym in priority if sym in asset_map and asset_map[sym].get("enabled", True)]
        # If no priority list, use all enabled symbols
        return [sym for sym, meta in asset_map.items() if meta.get("enabled", True)]

    @property
    def positions(self) -> dict[str, Any]:
        with self._lock:
            return {k: v.to_dict() for k, v in self._positions.items()}

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def all_symbols(self) -> list[str]:
        return list(self._symbols)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        _log.info("[IPO] Trader started with %d tracked issues", len(self._symbols))
        self._send_fn(f"[IPO] Trader started ({len(self._symbols)} issues tracked)")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        _log.info("[IPO] Trader stopped")

    def can_trade(self) -> tuple[bool, str]:
        if not self._symbols:
            return False, "No IPO issues configured"
        with self._lock:
            if len(self._positions) >= self._max_active:
                return False, f"Max active issues ({self._max_active}) reached"
        return True, "Trading allowed"  # Primary market has no market-hours restriction for subscription

    def track_issue(self, symbol: str, issue_data: dict[str, Any]) -> bool:
        """Start tracking a new IPO/FPO/OFS/QIP issue.

        Args:
            symbol: Issue symbol.
            issue_data: Issue metadata (issue_type, issuer_name, price_band_low,
                       price_band_high, lot_size, open_date, close_date, etc.).

        Returns:
            True if tracking started.
        """
        with self._lock:
            if symbol in self._positions:
                _log.info("[IPO] %s: already tracked", symbol)
                return False
            if len(self._positions) >= self._max_active:
                _log.info("[IPO] Max active issues (%d) reached", self._max_active)
                return False

        issue_type = str(issue_data.get("issue_type", "IPO"))
        issuer_name = str(issue_data.get("issuer_name", ""))
        price_band_low = float(issue_data.get("price_band_low", 0))
        price_band_high = float(issue_data.get("price_band_high", 0))
        lot_size = int(issue_data.get("lot_size", 1))
        status = str(issue_data.get("status", ISSUE_STATUS_UPCOMING))
        grey_market_premium = float(issue_data.get("grey_market_premium", 0.0))
        allotment_date = str(issue_data.get("allotment_date", ""))
        listing_date = str(issue_data.get("listing_date", ""))
        entry_price = price_band_high  # Default bid = upper band
        direction = "BUY"

        pos = IPOTradePosition(
            symbol=symbol, issue_type=issue_type, issuer_name=issuer_name,
            direction=direction, qty=self._default_qty,
            entry_price=entry_price, price_band_low=price_band_low,
            price_band_high=price_band_high, lot_size=lot_size,
            status=status, grey_market_premium=grey_market_premium,
            allotment_date=allotment_date, listing_date=listing_date,
            entry_time=time.time(), reason=issue_data.get("reason", "new_issue"),
        )

        with self._lock:
            self._positions[symbol] = pos

        _log.info("[IPO] Tracking %s [%s]: %s", symbol, issue_type, issuer_name)
        self._send_fn(f"[IPO] Tracking {symbol} [{issue_type}]: {issuer_name}")
        return True

    def update_issue_status(self, symbol: str, status: str, **metadata: Any) -> bool:
        """Update the lifecycle status of a tracked issue.

        Args:
            symbol: Issue symbol.
            status: New status (UPCOMING, OPEN, CLOSED, ALLOTTED, LISTED, CANCELLED).
            **metadata: Optional fields to update (listing_price, grey_market_premium, etc.).

        Returns:
            True if update succeeded.
        """
        with self._lock:
            pos = self._positions.get(symbol)
            if pos is None:
                return False
            pos.status = status
            for key, value in metadata.items():
                if hasattr(pos, key):
                    setattr(pos, key, value)
        _log.info("[IPO] %s: status → %s", symbol, status)
        return True

    def enter_position(
        self, symbol: str, direction: str, score: int,
        entry_price: float = 0.0, reason: str = "", qty: int = 0,
    ) -> bool:
        """Submit an issue application / bid.

        For IPOs: subscribe at upper price band.
        For OFS: participate in offer.
        """
        with self._lock:
            if len(self._positions) >= self._max_active:
                return False
            if symbol in self._positions:
                return False

        issue_data = self._cfg.get("IPO_MAP", {}).get(symbol, {})
        lot_qty = qty if qty > 0 else self._default_qty
        price = entry_price if entry_price > 0 else float(issue_data.get("price_band_high", 0))
        issue_type = str(issue_data.get("issue_type", "IPO"))
        issuer_name = str(issue_data.get("issuer_name", ""))

        if self._execute_entry_fn is not None:
            try:
                if not self._execute_entry_fn(symbol, direction, lot_qty, price):
                    return False
            except (ValueError, TypeError, OSError) as e:
                _log.error("[IPO] %s: entry failed - %s", symbol, e)
                return False

        pos = IPOTradePosition(
            symbol=symbol, issue_type=issue_type, issuer_name=issuer_name,
            direction=direction, qty=lot_qty, entry_price=price,
            price_band_low=float(issue_data.get("price_band_low", 0)),
            price_band_high=float(issue_data.get("price_band_high", 0)),
            lot_size=int(issue_data.get("lot_size", 1)),
            status=ISSUE_STATUS_OPEN,
            allotment_date=str(issue_data.get("allotment_date", "")),
            listing_date=str(issue_data.get("listing_date", "")),
            entry_time=time.time(), score=score, reason=reason or "subscription",
        )

        with self._lock:
            self._positions[symbol] = pos

        _log.info("[IPO] Subscribed %s [%s] x%d @ %.2f", symbol, issue_type, lot_qty, price)
        self._send_fn(f"[IPO] Subscribed {symbol} [{issue_type}] x{lot_qty} @ {price:.2f}")
        return True

    def exit_position(self, symbol: str, reason: str, exit_price: float = 0.0) -> bool:
        """Exit a position (sell on listing day or cancel subscription).

        Args:
            symbol: Issue symbol.
            reason: Exit reason (LISTING_SELL, STOP_LOSS, TARGET, CANCELLED).
            exit_price: Sale price (for listed issues).

        Returns:
            True if position was exited.
        """
        with self._lock:
            pos = self._positions.pop(symbol, None)
        if pos is None:
            return False

        price = exit_price if exit_price > 0 else (self._get_price_fn(symbol) or pos.entry_price)
        pnl = 0.0
        if pos.listing_price > 0:
            pnl = (price - pos.entry_price) * pos.qty
        elif pos.status == ISSUE_STATUS_LISTED:
            pnl = (price - pos.entry_price) * pos.qty

        if self._execute_exit_fn is not None:
            try:
                self._execute_exit_fn(symbol, pos.qty, price)
            except (ValueError, TypeError, OSError) as e:
                _log.error("[IPO] %s: exit failed - %s", symbol, e)

        _log.info("[IPO] Exited %s: %s @ %.2f (P&L=%.0f)", symbol, reason, price, pnl)
        self._send_fn(f"[IPO] Exited {symbol}: {reason} @ {price:.2f} P&L={pnl:.0f}")
        rt = self._reentry_trackers.get(symbol)
        if rt is not None:
            rt.record_outcome(pnl > 0)
        return True

    def _run_loop(self) -> None:
        interval = max(30, int(self._cfg.get("SCAN_INTERVAL", 60)))  # IPO updates less frequent
        while self._running and not self._stop_event.is_set():
            try:
                self._monitor_issues()
            except (ValueError, TypeError, OSError) as e:
                _log.warning("[IPO] Loop error: %s", e)
            self._stop_event.wait(interval)

    def _monitor_issues(self) -> None:
        """Monitor tracked issues for status changes and listing-day exits."""
        for symbol in list(self._positions.keys()):
            with self._lock:
                pos = self._positions.get(symbol)
                if pos is None:
                    continue

            if pos.status == ISSUE_STATUS_LISTED:
                # Check for listing-day exit signals
                current_price = self._get_price_fn(symbol)
                if current_price is None or current_price <= 0:
                    continue

                with self._lock:
                    if symbol in self._positions:
                        self._positions[symbol].current_price = current_price
                        if self._positions[symbol].listing_price <= 0:
                            self._positions[symbol].listing_price = current_price

                # Listing-day price check against SL/Target
                if pos.listing_price > 0:
                    move_pct = (current_price - pos.listing_price) / pos.listing_price
                    if move_pct <= -(1.0 - self._sl_pct):
                        self.exit_position(symbol, "LISTING_SL_HIT", current_price)
                    elif move_pct >= (self._target_pct - 1.0):
                        self.exit_position(symbol, "LISTING_TARGET_HIT", current_price)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "active_issues": len(self._positions),
                "max_active_issues": self._max_active,
                "tracked_symbols": len(self._symbols),
                "issues_by_status": self._count_by_status(),
            }

    def _count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for pos in self._positions.values():
            counts[pos.status] = counts.get(pos.status, 0) + 1
        return counts


def run_ipo_trader(**kwargs: Any) -> IPOTrader:
    trader = IPOTrader(**kwargs)
    trader.start()
    return trader


__all__ = [
    "IPOTradePosition",
    "IPOTrader",
    "run_ipo_trader",
    "ISSUE_STATUS_UPCOMING",
    "ISSUE_STATUS_OPEN",
    "ISSUE_STATUS_CLOSED",
    "ISSUE_STATUS_ALLOTTED",
    "ISSUE_STATUS_LISTED",
    "ISSUE_STATUS_CANCELLED",
]
