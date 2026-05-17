"""
PnL Attribution Engine - Item 18

Break PnL into components:
- alpha (signal quality)
- slippage
- fees
- STT
- missed fills
- execution degradation

Very valuable for understanding performance drivers.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Any

from core.time_provider import time_provider

_log = logging.getLogger(__name__)


@dataclass
class PnLAttribution:
    """PnL attribution breakdown"""
    trade_id: str
    total_pnl: float

    alpha_pnl: float
    slippage_pnl: float
    fees_pnl: float
    stt_pnl: float
    missed_pnl: float
    execution_pnl: float

    entry_price: float
    exit_price: float
    expected_price: float

    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PnLAttributionEngine:
    """
    PnL attribution analysis engine.
    Breaks down P&L into component parts for analysis.
    """

    PERSISTENCE_PATH = "pnl_attribution.db"

    def __init__(self):
        self._attributions: dict[str, PnLAttribution] = {}
        self._lock = threading.Lock()
        self._default_fees = {
            "brokerage": 0.0,
            "stt": 0.00125,
            "exchange_fee": 0.0000325,
            "sebi_charge": 0.0000015,
            "gst": 0.18,
        }
        self._init_durable_storage()

    def _init_durable_storage(self) -> None:
        """Initialize PnL attribution storage"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS pnl_attributions (
                        trade_id TEXT PRIMARY KEY,
                        total_pnl REAL,
                        alpha_pnl REAL,
                        slippage_pnl REAL,
                        fees_pnl REAL,
                        stt_pnl REAL,
                        missed_pnl REAL,
                        execution_pnl REAL,
                        entry_price REAL,
                        exit_price REAL,
                        expected_price REAL,
                        timestamp TEXT,
                        metadata_json TEXT
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_attribution (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        date TEXT,
                        total_pnl REAL,
                        alpha_pnl REAL,
                        slippage_pnl REAL,
                        fees_pnl REAL,
                        stt_pnl REAL,
                        missed_pnl REAL,
                        execution_pnl REAL,
                        trade_count INTEGER
                    )
                """)
                conn.commit()
            _log.info("PnLAttributionEngine: Storage initialized")
        except Exception as e:
            _log.error(f"PnLAttributionEngine: Failed to init storage: {e}")

    def calculate_attribution(
        self,
        trade_id: str,
        direction: str,
        quantity: int,
        entry_price: float,
        exit_price: float,
        expected_price: float = None,
        signal_price: float = None,
        fill_price: float = None,
        metadata: dict = None,
    ) -> PnLAttribution:
        """
        Calculate P&L attribution for a trade.
        
        Args:
            trade_id: Unique trade identifier
            direction: BUY or SELL
            quantity: Number of lots
            entry_price: Actual entry price
            exit_price: Actual exit price
            expected_price: Expected price (signal price)
            signal_price: Price when signal generated
            fill_price: Price when order filled
            metadata: Additional trade data
        """
        if expected_price is None:
            expected_price = signal_price or entry_price

        if fill_price is None:
            fill_price = entry_price

        multiplier = 1 if direction == "BUY" else -1
        total_pnl = (exit_price - entry_price) * quantity * multiplier

        alpha_pnl = (expected_price - entry_price) * quantity * multiplier

        slippage_pnl = (entry_price - fill_price) * quantity * multiplier

        fees_pnl = self._calculate_fees(entry_price, exit_price, quantity)

        stt_pnl = exit_price * quantity * self._default_fees["stt"] * multiplier

        if signal_price and abs(entry_price - signal_price) / signal_price > 0.01:
            missed_pnl = (entry_price - signal_price) * quantity * multiplier
        else:
            missed_pnl = 0.0

        execution_pnl = total_pnl - (alpha_pnl + slippage_pnl + fees_pnl + stt_pnl + missed_pnl)

        attribution = PnLAttribution(
            trade_id=trade_id,
            total_pnl=total_pnl,
            alpha_pnl=alpha_pnl,
            slippage_pnl=slippage_pnl,
            fees_pnl=fees_pnl,
            stt_pnl=stt_pnl,
            missed_pnl=missed_pnl,
            execution_pnl=execution_pnl,
            entry_price=entry_price,
            exit_price=exit_price,
            expected_price=expected_price,
            timestamp=time_provider.format_ts(),
            metadata=metadata or {},
        )

        with self._lock:
            self._attributions[trade_id] = attribution

        self._persist_attribution(attribution)
        _log.debug(f"Calculated P&L attribution for {trade_id}: {total_pnl:.2f}")

        return attribution

    def _calculate_fees(self, entry_price: float, exit_price: float, quantity: int) -> float:
        """Calculate total fees"""
        turnover = (entry_price + exit_price) * quantity

        brokerage = turnover * self._default_fees.get("brokerage", 0)

        exchange_fee = turnover * self._default_fees.get("exchange_fee", 0)

        sebi = turnover * self._default_fees.get("sebi_charge", 0)

        total_before_gst = brokerage + exchange_fee + sebi
        gst = total_before_gst * self._default_fees.get("gst", 0)

        return -(total_before_gst + gst)

    def get_attribution(self, trade_id: str) -> PnLAttribution | None:
        """Get attribution for specific trade"""
        return self._attributions.get(trade_id)

    def get_total_attribution(self) -> dict[str, float]:
        """Get total P&L attribution"""
        with self._lock:
            total = {
                "total_pnl": 0,
                "alpha_pnl": 0,
                "slippage_pnl": 0,
                "fees_pnl": 0,
                "stt_pnl": 0,
                "missed_pnl": 0,
                "execution_pnl": 0,
                "trade_count": len(self._attributions),
            }

            for attr in self._attributions.values():
                total["total_pnl"] += attr.total_pnl
                total["alpha_pnl"] += attr.alpha_pnl
                total["slippage_pnl"] += attr.slippage_pnl
                total["fees_pnl"] += attr.fees_pnl
                total["stt_pnl"] += attr.stt_pnl
                total["missed_pnl"] += attr.missed_pnl
                total["execution_pnl"] += attr.execution_pnl

            return total

    def get_top_slippage_trades(self, limit: int = 10) -> list[PnLAttribution]:
        """Get trades with highest slippage"""
        with self._lock:
            sorted_trades = sorted(
                self._attributions.values(),
                key=lambda a: abs(a.slippage_pnl),
                reverse=True,
            )
            return sorted_trades[:limit]

    def get_worst_execution_trades(self, limit: int = 10) -> list[PnLAttribution]:
        """Get trades with worst execution"""
        with self._lock:
            sorted_trades = sorted(
                self._attributions.values(),
                key=lambda a: abs(a.execution_pnl),
                reverse=True,
            )
            return sorted_trades[:limit]

    def get_attribution_by_date(self, date: str) -> dict[str, float]:
        """Get attribution summary for specific date"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                cursor = conn.execute("""
                    SELECT SUM(total_pnl), SUM(alpha_pnl), SUM(slippage_pnl),
                           SUM(fees_pnl), SUM(stt_pnl), SUM(missed_pnl), SUM(execution_pnl), COUNT(*)
                    FROM pnl_attributions
                    WHERE timestamp LIKE ?
                """, (f"{date}%",))

                row = cursor.fetchone()

                if row and row[0] is not None:
                    return {
                        "total_pnl": row[0],
                        "alpha_pnl": row[1],
                        "slippage_pnl": row[2],
                        "fees_pnl": row[3],
                        "stt_pnl": row[4],
                        "missed_pnl": row[5],
                        "execution_pnl": row[6],
                        "trade_count": row[7],
                    }
        except Exception as e:
            _log.error(f"Failed to get attribution by date: {e}")

        return {}

    def get_percentage_breakdown(self) -> dict[str, float]:
        """Get P&L breakdown as percentages"""
        totals = self.get_total_attribution()
        total_pnl = totals.get("total_pnl", 0)

        if total_pnl == 0:
            return {
                "alpha_pct": 0,
                "slippage_pct": 0,
                "fees_pct": 0,
                "stt_pct": 0,
                "missed_pct": 0,
                "execution_pct": 0,
            }

        return {
            "alpha_pct": (totals["alpha_pnl"] / total_pnl) * 100,
            "slippage_pct": (totals["slippage_pnl"] / total_pnl) * 100,
            "fees_pct": (totals["fees_pnl"] / total_pnl) * 100,
            "stt_pct": (totals["stt_pnl"] / total_pnl) * 100,
            "missed_pct": (totals["missed_pnl"] / total_pnl) * 100,
            "execution_pct": (totals["execution_pnl"] / total_pnl) * 100,
        }

    def _persist_attribution(self, attribution: PnLAttribution) -> None:
        """Persist attribution to DB"""
        try:
            with sqlite3.connect(self.PERSISTENCE_PATH) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO pnl_attributions
                    (trade_id, total_pnl, alpha_pnl, slippage_pnl, fees_pnl, stt_pnl,
                     missed_pnl, execution_pnl, entry_price, exit_price, expected_price,
                     timestamp, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    attribution.trade_id,
                    attribution.total_pnl,
                    attribution.alpha_pnl,
                    attribution.slippage_pnl,
                    attribution.fees_pnl,
                    attribution.stt_pnl,
                    attribution.missed_pnl,
                    attribution.execution_pnl,
                    attribution.entry_price,
                    attribution.exit_price,
                    attribution.expected_price,
                    attribution.timestamp,
                    json.dumps(attribution.metadata),
                ))
                conn.commit()
        except Exception as e:
            _log.error(f"Failed to persist attribution: {e}")


_pnl_engine: PnLAttributionEngine | None = None
_engine_lock = threading.Lock()


def get_pnl_attribution_engine() -> PnLAttributionEngine:
    """Get singleton P&L attribution engine"""
    global _pnl_engine
    with _engine_lock:
        if _pnl_engine is None:
            _pnl_engine = PnLAttributionEngine()
        return _pnl_engine
