"""
Lot Size Live Validation (Phase 1).

At startup and runtime, fetches the lot size from broker API
and validates it matches the config value. Halts on mismatch.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


DEFAULT_INDEX_LOT_SIZES = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 40,
    "MIDCPNIFTY": 75,
    "SENSEX": 10,
    "BANKEX": 10,
}


@dataclass
class LotSizeResult:
    index_name: str
    config_lot: int
    live_lot: int | None
    is_valid: bool
    error_message: str | None = None


class LotSizeValidator:
    """
    Validates lot sizes against live broker data.

    Runs at:
    - Startup validation
    - Pre-session checklist
    - Pre-order sizing validation
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}
        self._lock = threading.Lock()
        self._cached_lots: dict[str, int] = {}
        self._last_fetch: float | None = None
        self._cache_ttl_seconds = 300

    def set_config(self, cfg: dict[str, Any]) -> None:
        """Update config after initialization."""
        with self._lock:
            self._cfg = cfg

    def get_lot_size(self, index_name: str) -> int:
        """Get configured lot size for index."""
        config_key = f"{index_name}_LOT_SIZE"
        return self._cfg.get(config_key, DEFAULT_INDEX_LOT_SIZES.get(index_name, 50))

    def validate(self, broker_port=None, strict: bool = True) -> bool:
        """
        Validate lot sizes against live broker data.

        Args:
            broker_port: Optional broker adapter to fetch live lot sizes
            strict: If True, halts on mismatch. If False, warns only.

        Returns:
            True if validation passes, False otherwise
        """
        results = self.validate_all(broker_port)
        all_valid = all(r.is_valid for r in results)

        if not all_valid and strict:
            from core.safety_state import trip_hard_halt
            mismatches = [f"{r.index_name}: config={r.config_lot}, live={r.live_lot}"
                         for r in results if not r.is_valid]
            trip_hard_halt(
                f"Lot size mismatch detected: {mismatches}",
                source="LotSizeValidator"
            )

        return all_valid

    def validate_all(self, broker_port=None) -> list[LotSizeResult]:
        """Validate all configured indices."""
        results = []
        for index_name in DEFAULT_INDEX_LOT_SIZES:
            result = self.validate_one(index_name, broker_port)
            results.append(result)
        return results

    def validate_one(self, index_name: str, broker_port=None) -> LotSizeResult:
        """Validate single index lot size."""
        config_lot = self.get_lot_size(index_name)
        live_lot = self._get_cached_lot_size(index_name, broker_port)

        if live_lot is None:
            return LotSizeResult(
                index_name=index_name,
                config_lot=config_lot,
                live_lot=None,
                is_valid=True,
                error_message="Could not fetch live lot size - using config"
            )

        if live_lot != config_lot:
            log.critical(
                f"LOT SIZE MISMATCH for {index_name}: "
                f"config={config_lot}, live={live_lot}"
            )
            return LotSizeResult(
                index_name=index_name,
                config_lot=config_lot,
                live_lot=live_lot,
                is_valid=False,
                error_message=f"Mismatch: config={config_lot}, live={live_lot}"
            )

        log.info(f"Lot size validated for {index_name}: {config_lot}")
        return LotSizeResult(
            index_name=index_name,
            config_lot=config_lot,
            live_lot=live_lot,
            is_valid=True
        )

    def validate_order_size(self, index_name: str, qty: int, broker_port=None) -> tuple[bool, str]:
        """
        Validate order quantity is multiple of lot size.

        Args:
            index_name: Index name (e.g., "NIFTY")
            qty: Requested quantity
            broker_port: Optional broker for live validation

        Returns:
            (is_valid, error_message)
        """
        lot_size = self.get_lot_size(index_name)
        live_lot = self._get_cached_lot_size(index_name, broker_port)

        if live_lot and live_lot != lot_size:
            log.warning(f"Live lot size {live_lot} differs from config {lot_size} for {index_name}")
            lot_size = live_lot

        if qty % lot_size != 0:
            return False, f"Quantity {qty} not multiple of lot size {lot_size}"

        return True, ""

    def _get_cached_lot_size(self, index_name: str, broker_port=None) -> int | None:
        """Get lot size from cache or fetch fresh."""
        now = time.time()

        with self._lock:
            if self._last_fetch and (now - self._last_fetch) < self._cache_ttl_seconds:
                if index_name in self._cached_lots:
                    return self._cached_lots[index_name]

        live_lot = self._get_live_lot_size(index_name, broker_port)

        with self._lock:
            if live_lot:
                self._cached_lots[index_name] = live_lot
                self._last_fetch = now

        return live_lot

    def _get_live_lot_size(self, index_name: str, broker_port=None) -> int | None:
        """Fetch live lot size from broker API."""
        if broker_port is None:
            return None

        try:
            if hasattr(broker_port, "get_instruments"):
                instruments = broker_port.get_instruments()
                for inst in instruments:
                    symbol = inst.get("tradingsymbol", "")
                    if symbol.startswith(index_name):
                        lot_size = inst.get("lot_size", 0)
                        if lot_size:
                            return int(lot_size)

            if hasattr(broker_port, "get_lot_size"):
                return broker_port.get_lot_size(index_name)

        except Exception as e:
            log.warning(f"Could not fetch live lot size for {index_name}: {e}")

        return None

    def invalidate_cache(self) -> None:
        """Invalidate lot size cache to force refresh."""
        with self._lock:
            self._cached_lots.clear()
            self._last_fetch = None


def validate_lot_sizes(cfg: dict[str, Any], broker_port=None, strict: bool = True) -> bool:
    """Validate lot sizes at startup."""
    validator = LotSizeValidator(cfg)
    return validator.validate(broker_port, strict)
