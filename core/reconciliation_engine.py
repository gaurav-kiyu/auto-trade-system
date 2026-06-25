from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


__all__ = [
    "ReconciliationEngine",
    "ReconciliationItem",
    "ReconciliationReport",
]

@dataclass(frozen=True)
class ReconciliationItem:
    symbol: str
    ok: bool
    local_qty: int
    broker_qty: int
    local_price: float
    broker_price: float
    note: str = ""
    has_qty_mismatch: bool = False  # True when local_qty != broker_qty (both may be > 0)


@dataclass(frozen=True)
class ReconciliationReport:
    ok: bool
    items: list[ReconciliationItem]
    mismatches: int


class ReconciliationEngine:
    """Compare local tracked positions/orders against broker truth."""

    def __init__(
        self,
        *,
        broker_snapshot_fn: Callable[[], dict[str, Any] | list[dict[str, Any]]],
        price_tolerance_pct: float = 0.05,
        qty_mismatch_halts: bool = True,
        report_broker_only_positions: bool = True,
    ) -> None:
        self._broker_snapshot_fn = broker_snapshot_fn
        self._price_tolerance_pct = float(price_tolerance_pct)
        self._qty_mismatch_halts = bool(qty_mismatch_halts)
        self._report_broker_only_positions = bool(report_broker_only_positions)

    def _normalize(self, snapshot: dict[str, Any] | list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        if isinstance(snapshot, dict):
            return {str(k): dict(v or {}) for k, v in snapshot.items()}
        result: dict[str, dict[str, Any]] = {}
        for row in snapshot or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("tradingsymbol") or row.get("symbol") or row.get("name") or "")
            if not symbol:
                continue
            result[symbol] = dict(row)
        return result

    def reconcile_positions(self, local_positions: dict[str, dict[str, Any]]) -> ReconciliationReport:
        broker_raw = self._broker_snapshot_fn()
        broker = self._normalize(broker_raw)
        items: list[ReconciliationItem] = []
        mismatches = 0

        local_map = dict(local_positions or {})
        for symbol, local in local_map.items():
            broker_row = broker.get(symbol, {})
            try:
                local_qty = int(local.get("qty") or 0)
            except (TypeError, ValueError, KeyError):
                local_qty = 0
            try:
                broker_qty = int(broker_row.get("qty") or broker_row.get("quantity") or 0)
            except (TypeError, ValueError, KeyError):
                broker_qty = 0
            try:
                local_price = float(local.get("entry") or 0.0)
            except (TypeError, ValueError, KeyError):
                local_price = 0.0
            try:
                broker_price = float(
                    broker_row.get("avg_price")
                    or broker_row.get("average_price")
                    or broker_row.get("price")
                    or 0.0
                )
            except (TypeError, ValueError, KeyError):
                broker_price = 0.0

            qty_ok = local_qty == broker_qty
            price_ok = True
            note_parts: list[str] = []
            if not qty_ok:
                mismatches += 1
                note_parts.append("qty mismatch")
            if local_price > 0 and broker_price > 0:
                diff_pct = abs(local_price - broker_price) / local_price
                if diff_pct > self._price_tolerance_pct:
                    price_ok = False
                    mismatches += 1
                    note_parts.append(f"price mismatch {diff_pct:.2%}")
            if broker_qty == 0 and local_qty > 0:
                note_parts.append("broker empty")
            item_ok = qty_ok and price_ok
            items.append(
                ReconciliationItem(
                    symbol=str(symbol),
                    ok=item_ok,
                    local_qty=local_qty,
                    broker_qty=broker_qty,
                    local_price=round(local_price, 4),
                    broker_price=round(broker_price, 4),
                    note=", ".join(note_parts),
                    has_qty_mismatch=not qty_ok,
                )
            )

        if self._report_broker_only_positions:
            local_keys = set(local_map.keys())
            for symbol, broker_row in broker.items():
                if symbol in local_keys:
                    continue
                if not isinstance(broker_row, dict):
                    continue
                try:
                    broker_qty = int(broker_row.get("qty") or broker_row.get("quantity") or 0)
                except (TypeError, ValueError, KeyError):
                    broker_qty = 0
                if broker_qty <= 0:
                    continue
                try:
                    broker_price = float(
                        broker_row.get("avg_price")
                        or broker_row.get("average_price")
                        or broker_row.get("price")
                        or 0.0
                    )
                except (TypeError, ValueError, KeyError):
                    broker_price = 0.0
                mismatches += 1
                items.append(
                    ReconciliationItem(
                        symbol=str(symbol),
                        ok=False,
                        local_qty=0,
                        broker_qty=broker_qty,
                        local_price=0.0,
                        broker_price=round(broker_price, 4),
                        note="broker-only position (not in bot state)",
                        has_qty_mismatch=False,  # broker-only is a different class of mismatch
                    )
                )

        # Report is OK when:
        #   a) no mismatches at all, OR
        #   b) qty_mismatch_halts is disabled AND every non-OK item is ONLY a qty mismatch
        #      (not a price mismatch, broker-only position, or other anomaly).
        # Uses typed has_qty_mismatch rather than string matching for correctness.
        report_ok = (mismatches == 0) or (
            not self._qty_mismatch_halts
            and all(item.ok or item.has_qty_mismatch for item in items)
        )
        return ReconciliationReport(
            ok=report_ok,
            items=items,
            mismatches=mismatches,
        )
