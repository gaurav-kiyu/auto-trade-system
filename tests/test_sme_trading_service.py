"""Tests for core.services.sme_trading_service - SME trading service with circuit-limit-aware gates.

Covers:
  - Circuit limit entry validation (5%, 10%, near-circuit warnings)
  - T2T restriction detection
  - Exit validation (within circuit, near-circuit tolerance)
  - Position sizing with circuit-adjusted caps
  - Liquidity guard
  - Price validity checks
  - Min lot size handling
  - Error handling for edge cases
"""

from __future__ import annotations

import os
import tempfile

import pytest

from core.domains.equity import Sector
from core.domains.sme import (
    SmePlatform,
    SmeStock,
    SmeStockFundamentals,
    SmeTradingRestriction,
)
from core.services.sme_trading_service import SmeTradingService


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def service():
    """Create SmeTradingService with a temporary DB for test isolation."""
    tmp = tempfile.mktemp(suffix="_sme_test.db")
    svc = SmeTradingService(db_path=tmp)
    yield svc
    try:
        os.remove(tmp)
    except (OSError, PermissionError):
        pass


def _make_sme_stock(
    symbol: str = "XYZLTD",
    price: float = 100.0,
    circuit_limit: float = 5.0,
    platform: SmePlatform = SmePlatform.NSE_EMERGE,
    restrictions: list | None = None,
    min_lot: int = 0,
    week_52_high: float = 150.0,
    week_52_low: float = 50.0,
    issue_price: float = 0.0,
) -> SmeStock:
    """Helper to create an SmeStock with optional fundamentals."""
    stock = SmeStock(
        symbol=symbol,
        name=f"{symbol} Ltd",
        sector=Sector.INFORMATION_TECHNOLOGY,
        platform=platform,
        last_price=price,
        week_52_high=week_52_high,
        week_52_low=week_52_low,
        issue_price=issue_price,
        restrictions=restrictions or [],
    )
    stock.fundamentals = SmeStockFundamentals(
        market_cap=100.0,
        circuit_limit_pct=circuit_limit,
        min_lot_size=min_lot,
        promoter_holding=45.0,
    )
    return stock


# ── Circuit Limit Gate Tests ────────────────────────────────────────────────

class TestCircuitLimitGate:
    def test_within_circuit_5pct(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_entry(stock, price=102.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()

    def test_exceeds_upper_circuit_5pct(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_entry(stock, price=106.0)
        assert allowed is False
        assert "exceeds upper circuit" in reason.lower()

    def test_below_lower_circuit_5pct(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_entry(stock, price=94.0)
        assert allowed is False
        assert "below lower circuit" in reason.lower()

    def test_10pct_circuit_limit(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=10.0)
        allowed, reason = service.validate_entry(stock, price=108.0)
        assert allowed is True
        allowed2, _ = service.validate_entry(stock, price=112.0)
        assert allowed2 is False

    def test_no_reference_price_skips_circuit_check(self, service):
        """When last_price is 0, circuit check should pass."""
        stock = _make_sme_stock(price=0.0)
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True

    def test_at_upper_circuit_boundary(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_entry(stock, price=105.0)
        assert allowed is True

    def test_at_lower_circuit_boundary(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_entry(stock, price=95.0)
        assert allowed is True


class TestT2TRestrictionGate:
    def test_t2t_stock_allowed_delivery(self, service):
        stock = _make_sme_stock(
            restrictions=[SmeTradingRestriction.TRADE_TO_TRADE],
        )
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()

    def test_non_t2t_stock(self, service):
        stock = _make_sme_stock()  # No T2T restriction
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()

    def test_multiple_restrictions_including_t2t(self, service):
        stock = _make_sme_stock(
            restrictions=[
                SmeTradingRestriction.TRADE_TO_TRADE,
                SmeTradingRestriction.FIXED_PRICE_BAND,
            ],
        )
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()


class TestMinLotSizeGate:
    def test_min_lot_warning(self, service):
        stock = _make_sme_stock(min_lot=300)
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()

    def test_no_min_lot(self, service):
        stock = _make_sme_stock()  # No min lot
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True
        assert "all sme gates passed" in reason.lower()


class TestLiquidityGate:
    def test_sufficient_volume(self, service):
        stock = _make_sme_stock(price=100.0)
        stock.fundamentals = SmeStockFundamentals(market_cap=100.0, circuit_limit_pct=5.0)
        allowed, reason = service.validate_entry(stock, price=100.0, volume=100000)
        assert allowed is True

    def test_insufficient_volume(self, service):
        stock = _make_sme_stock(price=100.0)
        stock.fundamentals = SmeStockFundamentals(market_cap=100.0, circuit_limit_pct=5.0)
        allowed, reason = service.validate_entry(stock, price=100.0, volume=10)
        assert allowed is False
        assert "insufficient volume" in reason.lower()

    def test_zero_volume_skips_liquidity_check(self, service):
        stock = _make_sme_stock(price=100.0)
        stock.fundamentals = SmeStockFundamentals(market_cap=100.0, circuit_limit_pct=5.0)
        allowed, reason = service.validate_entry(stock, price=100.0, volume=0)
        assert allowed is True

    def test_no_fundamentals_skips_liquidity_check(self, service):
        stock = _make_sme_stock(price=100.0)
        stock.fundamentals = None
        allowed, reason = service.validate_entry(stock, price=100.0, volume=0)
        assert allowed is True


class TestPriceValidityGate:
    def test_valid_price(self, service):
        stock = _make_sme_stock(price=100.0, week_52_high=150.0, week_52_low=50.0)
        allowed, reason = service.validate_entry(stock, price=100.0)
        assert allowed is True

    def test_price_exceeds_52w_high(self, service):
        stock = _make_sme_stock(price=100.0, week_52_high=150.0)
        allowed, reason = service.validate_entry(stock, price=250.0)
        assert allowed is False

    def test_price_below_issue_price_threshold(self, service):
        stock = _make_sme_stock(price=100.0, issue_price=1000.0)
        allowed, reason = service.validate_entry(stock, price=50.0)
        assert allowed is False

    def test_zero_price_rejected(self, service):
        stock = _make_sme_stock(price=100.0)
        allowed, reason = service.validate_entry(stock, price=0.0)
        assert allowed is False
        assert "invalid price" in reason.lower()


class TestExitValidation:
    def test_exit_within_circuit(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_exit(stock, price=102.0)
        assert allowed is True
        assert "exit validation passed" in reason.lower()

    def test_exit_above_upper_circuit(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_exit(stock, price=108.0)
        assert allowed is False
        assert "exceeds upper circuit" in reason.lower()

    def test_exit_below_lower_circuit(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_exit(stock, price=92.0)
        assert allowed is False
        assert "below lower circuit" in reason.lower()

    def test_exit_near_circuit_with_tolerance(self, service):
        """Exit should allow 2% tolerance above circuit."""
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_exit(stock, price=106.5)
        assert allowed is True  # 106.5 / 105.0 = ~1.4% above circuit, within 2% tolerance

    def test_exit_past_tolerance(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        allowed, reason = service.validate_exit(stock, price=108.0)
        assert allowed is False  # 108 / 105 = 2.8% above circuit, beyond 2% tolerance

    def test_exit_with_zero_reference_price(self, service):
        stock = _make_sme_stock(price=0.0)
        allowed, reason = service.validate_exit(stock, price=100.0)
        assert allowed is True  # Falls back to percentage-based check


class TestPositionSizing:
    def test_basic_position_size(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        size = service.calculate_sme_position_size(
            stock, available_capital=100000.0, risk_per_trade_pct=0.02,
        )
        assert size > 0
        assert size <= 100  # 100K * 2% / 100 = 20 shares max

    def test_tighter_circuit_reduces_size(self, service):
        stock_5pct = _make_sme_stock(price=100.0, circuit_limit=5.0)
        stock_10pct = _make_sme_stock(price=100.0, circuit_limit=10.0)

        size_5 = service.calculate_sme_position_size(
            stock_5pct, available_capital=100000.0,
        )
        size_10 = service.calculate_sme_position_size(
            stock_10pct, available_capital=100000.0,
        )
        # 5% circuit should give smaller position than 10% circuit
        assert size_5 <= size_10

    def test_min_lot_rounding(self, service):
        stock = _make_sme_stock(price=100.0, min_lot=300)
        size = service.calculate_sme_position_size(
            stock, available_capital=100000.0, risk_per_trade_pct=0.02,
        )
        assert size >= 300  # Should respect minimum lot size

    def test_zero_price_returns_zero(self, service):
        stock = _make_sme_stock(price=0.0)
        size = service.calculate_sme_position_size(stock, 100000.0)
        assert size == 0


class TestGateLogging:
    def test_entry_logged_to_db(self, service):
        stock = _make_sme_stock(price=100.0)
        service.validate_entry(stock, price=101.0, direction="BUY")
        logs = service.get_recent_gate_log(limit=5)
        assert len(logs) >= 1
        assert logs[0]["symbol"] == "XYZLTD"
        assert logs[0]["action"] == "ENTRY"
        assert logs[0]["gate_result"] == "PASS"

    def test_blocked_entry_logged(self, service):
        stock = _make_sme_stock(price=100.0, circuit_limit=5.0)
        service.validate_entry(stock, price=200.0)
        logs = service.get_recent_gate_log(limit=5)
        # Should have at least the BLOCKED entry
        blocked = [l for l in logs if l["gate_result"] == "BLOCKED"]
        assert len(blocked) >= 1

    def test_log_filter_by_symbol(self, service):
        stock_a = _make_sme_stock("STOCKA", price=100.0)
        stock_b = _make_sme_stock("STOCKB", price=100.0)
        service.validate_entry(stock_a, price=101.0)
        service.validate_entry(stock_b, price=101.0)
        logs_a = service.get_recent_gate_log(symbol="STOCKA")
        assert all(l["symbol"] == "STOCKA" for l in logs_a)

    def test_log_limit(self, service):
        stock = _make_sme_stock(price=100.0)
        for i in range(5):
            service.validate_entry(stock, price=100.0 + i)
        logs = service.get_recent_gate_log(limit=3)
        assert len(logs) == 3


class TestFullEntryPipeline:
    def test_all_gates_pass(self, service):
        stock = _make_sme_stock(
            price=100.0, circuit_limit=5.0,
            week_52_high=150.0, week_52_low=50.0,
        )
        allowed, reason = service.validate_entry(
            stock, price=101.0, volume=50000, direction="BUY",
        )
        assert allowed is True

    def test_multiple_gates_block(self, service):
        """Price exceeds circuit AND 52w high — should show both failures."""
        stock = _make_sme_stock(
            price=100.0, circuit_limit=5.0,
            week_52_high=120.0,
        )
        allowed, reason = service.validate_entry(
            stock, price=200.0, volume=10,
        )
        assert allowed is False
        # Should contain at least two failure reasons
        assert "; " in reason

    def test_bse_sme_platform(self, service):
        stock = _make_sme_stock(
            price=100.0, circuit_limit=5.0, platform=SmePlatform.BSE_SME,
        )
        allowed, reason = service.validate_entry(stock, price=101.0)
        assert allowed is True
