"""Tests for REIT/InvIT domain models."""

from __future__ import annotations

from core.domains.reit import REITInvIT, TrustType


class TestREITInvIT:
    """Test suite for REIT/InvIT domain model."""

    def test_default_reit(self):
        """REIT with defaults."""
        r = REITInvIT(symbol="EMBASSY")
        assert r.symbol == "EMBASSY"
        assert r.trust_type == TrustType.REIT

    def test_full_reit(self):
        """REIT with all fields."""
        r = REITInvIT(
            symbol="EMBASSY",
            name="Embassy Office Parks REIT",
            trust_type=TrustType.REIT,
            sector="Office",
            lot_size=100,
            aum_crores=48000.0,
            distribution_yield=0.065,
            listing_date="2019-04-01",
            isin="INE041005011",
        )
        assert r.name == "Embassy Office Parks REIT"
        assert r.distribution_yield == 0.065
        assert r.lot_size == 100

    def test_invit(self):
        """InvIT creation."""
        r = REITInvIT(
            symbol="IRBINVIT",
            name="IRB Infrastructure Trust",
            trust_type=TrustType.INVIT,
            sector="Roads",
            lot_size=100,
        )
        assert r.trust_type == TrustType.INVIT
        assert r.sector == "Roads"

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        r = REITInvIT(symbol="EMBASSY", trust_type=TrustType.REIT)
        d = r.to_dict()
        assert d["symbol"] == "EMBASSY"
        assert d["trust_type"] == TrustType.REIT

    def test_summary(self):
        """summary returns non-empty string."""
        r = REITInvIT(symbol="EMBASSY", name="Embassy REIT", trust_type=TrustType.REIT)
        s = r.summary()
        assert "EMBASSY" in s
        assert "Embassy REIT" in s
        assert "REIT" in s

    def test_default_lot_size(self):
        """Default lot size should be 1."""
        r = REITInvIT(symbol="TEST")
        assert r.lot_size == 1

    def test_high_yield(self):
        """High distribution yield should be stored correctly."""
        r = REITInvIT(symbol="HIGHYIELD", distribution_yield=0.12)
        assert r.distribution_yield == 0.12

    def test_brookfield_reit(self):
        """Brookfield India REIT test."""
        r = REITInvIT(
            symbol="BIRET",
            name="Brookfield India Real Estate Trust",
            trust_type=TrustType.REIT,
            sector="Office",
        )
        assert r.symbol == "BIRET"
        assert r.trust_type == "REIT"
