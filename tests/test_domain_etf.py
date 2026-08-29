"""Tests for ETF domain models."""

from __future__ import annotations

from core.domains.etf import ETF, ETFType


class TestETF:
    """Test suite for ETF domain model."""

    def test_default_creation(self):
        """ETF should create with defaults."""
        etf = ETF(symbol="NIFTYBEES")
        assert etf.symbol == "NIFTYBEES"
        assert etf.etf_type == ETFType.EQUITY
        assert etf.lot_size == 1

    def test_full_creation(self):
        """ETF with all fields."""
        etf = ETF(
            symbol="NIFTYBEES",
            name="Nippon India ETF Nifty 50 Bees",
            etf_type=ETFType.EQUITY,
            underlying_index="NIFTY 50",
            expense_ratio=0.05,
            aum_crores=25000.0,
            lot_size=10,
            isin="INF204KB17I5",
            amc="Nippon India Mutual Fund",
        )
        assert etf.name == "Nippon India ETF Nifty 50 Bees"
        assert etf.underlying_index == "NIFTY 50"
        assert etf.expense_ratio == 0.05

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        etf = ETF(symbol="GOLDBEES", etf_type=ETFType.GOLD)
        d = etf.to_dict()
        assert d["symbol"] == "GOLDBEES"
        assert d["etf_type"] == ETFType.GOLD

    def test_summary(self):
        """summary returns non-empty string."""
        etf = ETF(symbol="NIFTYBEES", name="Nifty Bees")
        s = etf.summary()
        assert "NIFTYBEES" in s
        assert "Nifty Bees" in s

    def test_lot_size_default(self):
        """Default lot size should be 1."""
        etf = ETF(symbol="TEST")
        assert etf.lot_size == 1

    def test_debt_etf_type(self):
        """Debt ETF type should work."""
        etf = ETF(symbol="BHARATBOND", etf_type=ETFType.DEBT)
        assert etf.etf_type == "DEBT"

    def test_liquid_etf_type(self):
        """Liquid ETF type should work."""
        etf = ETF(symbol="LIQUIDBEES", etf_type=ETFType.LIQUID)
        assert etf.etf_type == "LIQUID"

    def test_international_etf(self):
        """International ETF type should work."""
        etf = ETF(symbol="HANGENGBEES", etf_type=ETFType.INTERNATIONAL)
        assert etf.etf_type == "INTERNATIONAL"
