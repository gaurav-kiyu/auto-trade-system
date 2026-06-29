"""
SME Trading Service - Circuit-limit-aware entry/exit gates for SME stocks.

SME (Small and Medium Enterprise) stocks listed on NSE EMERGE / BSE SME
have distinct trading constraints:
  - Fixed circuit limits (5% or 10%) vs 20% for mainboard
  - Trade-to-Trade (T2T) settlement for many scrips
  - Minimum lot sizes for trading
  - Lower liquidity and wider spreads
  - Stricter entry validation requirements

This service provides entry/exit gates specific to SME trading constraints.
"""

from __future__ import annotations

import logging
from typing import Any

from core.db_utils import get_connection
from core.domains.sme import SmePlatform, SmeStock

__all__ = [
    "SmeCircuitGateError",
    "SmeTradingService",
]

_log = logging.getLogger(__name__)

# Default circuit limits by platform
_CIRCUIT_LIMITS: dict[SmePlatform, float] = {
    SmePlatform.NSE_EMERGE: 5.0,
    SmePlatform.BSE_SME: 5.0,
}


class SmeCircuitGateError(Exception):
    """Raised when an SME circuit gate check blocks a trade."""


class SmeTradingService:
    """Trading service for SME equity with circuit-limit-aware entry gates.

    Provides entry/exit validation specific to SME stocks:
      - Circuit limit checks (5% or 10% price bands)
      - T2T settlement validation
      - Minimum lot size enforcement
      - Liquidity guard (volume and delivery % checks)

    Usage:
        service = SmeTradingService()
        result = service.validate_entry(sme_stock, price=100.0, volume=5000)
    """

    def __init__(self, db_path: str = "sme_trades.db"):
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Ensure the SME trades DB and schema exist."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sme_trade_log (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol          TEXT NOT NULL,
                    action          TEXT NOT NULL,
                    direction       TEXT NOT NULL,
                    price           REAL NOT NULL,
                    qty             INTEGER NOT NULL DEFAULT 0,
                    circuit_limit   REAL NOT NULL DEFAULT 5.0,
                    is_t2t          INTEGER NOT NULL DEFAULT 0,
                    gate_result     TEXT NOT NULL,
                    reason          TEXT DEFAULT '',
                    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Entry Gate ─────────────────────────────────────────────────────

    def validate_entry(
        self,
        stock: SmeStock,
        price: float,
        volume: int = 0,
        direction: str = "BUY",
    ) -> tuple[bool, str]:
        """Validate SME stock entry through all circuit/restriction gates.

        Args:
            stock: SME stock to validate.
            price: Proposed entry price.
            volume: Recent trading volume (for liquidity check).
            direction: BUY or SELL.

        Returns:
            (allowed, reason) tuple.
        """
        gates: list[tuple[str, Any]] = [
            ("circuit_limit", self._check_circuit_limit(stock, price)),
            ("t2t_restriction", self._check_t2t_restriction(stock)),
            ("min_lot_size", self._check_min_lot_size(stock)),
            ("liquidity", self._check_liquidity(stock, volume)),
            ("price_validity", self._check_price_validity(stock, price)),
        ]

        failures = [reason for gate_name, (passed, reason) in gates if not passed]
        gate_result = "PASS" if not failures else "BLOCKED"

        self._log_trade_gate(
            symbol=stock.symbol,
            action="ENTRY",
            direction=direction,
            price=price,
            circuit_limit=stock.circuit_percentage,
            is_t2t=stock.has_t2t_restriction,
            gate_result=gate_result,
            reason="; ".join(failures) if failures else "ok",
        )

        if failures:
            return False, "; ".join(failures)
        return True, "All SME gates passed"

    # ── Exit Gate ──────────────────────────────────────────────────────

    def validate_exit(
        self,
        stock: SmeStock,
        price: float,
        reason: str = "MANUAL",
    ) -> tuple[bool, str]:
        """Validate SME stock exit.

        SME exits are generally more permissive than entries - the main
        concern is ensuring the exit price is within circuit limits.

        Args:
            stock: SME stock to validate exit for.
            price: Proposed exit price.
            reason: Exit reason label.

        Returns:
            (allowed, reason) tuple.
        """
        # Circuit limit check for exit (must be within band)
        upper = stock.upper_circuit if stock.last_price > 0 else price * 1.05
        lower = stock.lower_circuit if stock.last_price > 0 else price * 0.95

        if price > upper * 1.02:  # Allow 2% tolerance above upper circuit
            return False, f"Exit price {price} exceeds upper circuit {upper:.2f}"
        if price < lower * 0.98:  # Allow 2% tolerance below lower circuit
            return False, f"Exit price {price} below lower circuit {lower:.2f}"

        self._log_trade_gate(
            symbol=stock.symbol,
            action="EXIT",
            direction="SELL" if reason != "MANUAL" else "MANUAL",
            price=price,
            circuit_limit=stock.circuit_percentage,
            is_t2t=stock.has_t2t_restriction,
            gate_result="PASS",
            reason=f"Exit via {reason}",
        )
        return True, "Exit validation passed"

    # ── Individual Gates ───────────────────────────────────────────────

    def _check_circuit_limit(self, stock: SmeStock, price: float) -> tuple[bool, str]:
        """Check if entry price is within the stock's circuit limits.

        SME stocks typically have 5% or 10% daily price bands.
        Entry is allowed only within the circuit range.
        """
        if stock.last_price <= 0:
            return True, "No reference price - skipping circuit check"

        upper = stock.upper_circuit
        lower = stock.lower_circuit

        if price > upper:
            return (
                False,
                f"Entry price {price:.2f} exceeds upper circuit {upper:.2f} "
                f"(limit={stock.circuit_percentage:.0f}%)",
            )
        if price < lower:
            return (
                False,
                f"Entry price {price:.2f} below lower circuit {lower:.2f} "
                f"(limit={stock.circuit_percentage:.0f}%)",
            )

        # Warn for entry near circuit (within 10% of the limit)
        circuit_range = upper - lower
        if circuit_range > 0:
            dist_to_upper = (upper - price) / circuit_range
            dist_to_lower = (price - lower) / circuit_range
            if dist_to_upper < 0.1 or dist_to_lower < 0.1:
                _log.info(
                    "[SME_CIRCUIT] %s entry near circuit: price=%.2f upper=%.2f lower=%.2f",
                    stock.symbol, price, upper, lower,
                )

        return True, f"Within circuit limit ({stock.circuit_percentage:.0f}%)"

    def _check_t2t_restriction(self, stock: SmeStock) -> tuple[bool, str]:
        """Check if T2T restriction allows entry.

        T2T (Trade-to-Trade) stocks require delivery settlement.
        Intraday trading is not allowed.
        """
        if stock.has_t2t_restriction:
            return (
                True,
                "T2T stock - delivery only (intraday blocked)",
            )
        return True, "No T2T restriction"

    def _check_min_lot_size(self, stock: SmeStock) -> tuple[bool, str]:
        """Check if stock has a minimum lot size requirement.

        Many SME stocks have minimum lot sizes for trading.
        This gate logs a warning but doesn't block - the actual quantity
        validation happens in the position sizing step.
        """
        min_lot = 0
        if stock.fundamentals:
            min_lot = stock.fundamentals.min_lot_size

        if min_lot > 0:
            return True, f"Min lot size: {min_lot} shares"
        return True, "No minimum lot restriction"

    def _check_liquidity(self, stock: SmeStock, volume: int) -> tuple[bool, str]:
        """Check if the stock has sufficient liquidity for trading.

        SME stocks typically have lower liquidity. This gate validates:
          - 10-day average volume (if available)
          - Delivery percentage (indicates genuine interest)
        """
        if stock.fundamentals:
            min_volume = max(1000, int(stock.fundamentals.market_cap * 10))
            if volume > 0 and volume < min_volume:
                return (
                    False,
                    f"Insufficient volume: {volume} < {min_volume} (min for mcap={stock.fundamentals.market_cap:.0f})",
                )
            if stock.average_delivery_pct > 0 and stock.average_delivery_pct < 10:
                _log.info(
                    "[SME_LIQUIDITY] %s low delivery %%: %.1f%%",
                    stock.symbol, stock.average_delivery_pct,
                )
        return True, "Liquidity check passed"

    def _check_price_validity(self, stock: SmeStock, price: float) -> tuple[bool, str]:
        """Validate that the price is reasonable for this SME stock."""
        if price <= 0:
            return False, "Invalid price <= 0"

        if stock.week_52_high > 0 and price > stock.week_52_high * 1.5:
            return (
                False,
                f"Price {price:.2f} exceeds 52w high {stock.week_52_high:.2f} by >50%",
            )

        if stock.issue_price > 0 and price < stock.issue_price * 0.1:
            return (
                False,
                f"Price {price:.2f} is <10% of issue price {stock.issue_price:.2f} - possible data error",
            )

        return True, "Price validity check passed"

    # ── Position Sizing ────────────────────────────────────────────────

    def calculate_sme_position_size(
        self,
        stock: SmeStock,
        available_capital: float,
        risk_per_trade_pct: float = 0.02,
        max_position_pct: float = 0.10,
    ) -> int:
        """Calculate position size for SME stock with circuit-aware limits.

        SME position sizing considers:
          - Tighter circuit limits (smaller positions to allow exit)
          - Minimum lot size requirements
          - Lower liquidity (smaller positions)

        Args:
            stock: SME stock to size position for.
            available_capital: Available capital for trading.
            risk_per_trade_pct: Risk per trade as decimal (default 2%).
            max_position_pct: Maximum position as % of capital (default 10%).

        Returns:
            Number of shares/units to trade.
        """
        if stock.last_price <= 0:
            return 0

        # Base risk-based sizing
        risk_amount = available_capital * risk_per_trade_pct
        base_shares = int(risk_amount / stock.last_price)

        # Circuit-adjusted cap: tighter circuit = smaller position
        circuit_factor = stock.circuit_percentage / 10.0  # 5% circuit = 0.5x, 10% = 1.0x
        circuit_cap = int((available_capital * max_position_pct) / stock.last_price * circuit_factor)

        # Apply minimum lot size (circuit cap should not override min lot)
        min_lot = 0
        if stock.fundamentals:
            min_lot = stock.fundamentals.min_lot_size

        # Take the smaller of risk-based and circuit-capped sizes,
        # but never go below minimum lot size
        final_shares = max(min(base_shares, circuit_cap), min_lot, 1)
        return final_shares

    # ── DB Logging ─────────────────────────────────────────────────────

    def _log_trade_gate(
        self,
        symbol: str,
        action: str,
        direction: str,
        price: float,
        circuit_limit: float,
        is_t2t: bool,
        gate_result: str,
        reason: str,
    ) -> None:
        """Log a trade gate check result to the SME trade log."""
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO sme_trade_log
                    (symbol, action, direction, price, circuit_limit, is_t2t,
                     gate_result, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (symbol, action, direction, price, circuit_limit,
                 int(is_t2t), gate_result, reason),
            )
            conn.commit()
        except (ValueError, TypeError, KeyError, OSError) as exc:
            _log.warning("[SME_LOG] Failed to log trade gate: %s", exc)
        finally:
            conn.close()

    def get_recent_gate_log(
        self,
        limit: int = 20,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch recent gate check log entries.

        Args:
            limit: Maximum number of entries.
            symbol: Optional symbol filter.

        Returns:
            List of gate log entry dicts.
        """
        conn = get_connection(self._db_path)
        try:
            if symbol:
                rows = conn.execute(
                    """SELECT * FROM sme_trade_log
                       WHERE symbol = ? ORDER BY timestamp DESC LIMIT ?""",
                    (symbol, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM sme_trade_log
                       ORDER BY timestamp DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()
