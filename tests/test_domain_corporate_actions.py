"""Tests for IPO / Corporate Actions domain models."""

from __future__ import annotations

from core.domains.corporate_actions import CorporateAction, CorporateActionType, IPOEvent, IssueType


class TestIPOEvent:
    """Test suite for IPOEvent."""

    def test_default_ipo(self):
        """IPO with defaults."""
        ipo = IPOEvent(symbol="ABCIPO")
        assert ipo.symbol == "ABCIPO"
        assert ipo.issue_type == IssueType.IPO
        assert ipo.status == "OPEN"

    def test_full_ipo(self):
        """IPO with all fields."""
        ipo = IPOEvent(
            symbol="ABCIPO",
            issue_type=IssueType.IPO,
            company_name="ABC Corporation Ltd",
            open_date="2026-08-01",
            close_date="2026-08-03",
            price_band_low=150.0,
            price_band_high=160.0,
            lot_size=50,
            total_issue_crores=500.0,
            fresh_issue_crores=400.0,
            ofs_crores=100.0,
            listing_date="2026-08-14",
            status="OPEN",
        )
        assert ipo.company_name == "ABC Corporation Ltd"
        assert ipo.price_band_low == 150.0
        assert ipo.total_issue_crores == 500.0

    def test_fpo(self):
        """FPO event creation."""
        fpo = IPOEvent(symbol="XYZFPO", issue_type=IssueType.FPO)
        assert fpo.issue_type == IssueType.FPO

    def test_ofs(self):
        """OFS event creation."""
        ofs = IPOEvent(symbol="PQR", issue_type=IssueType.OFS)
        assert ofs.issue_type == IssueType.OFS

    def test_qip(self):
        """QIP event creation."""
        qip = IPOEvent(symbol="MNO", issue_type=IssueType.QIP)
        assert qip.issue_type == IssueType.QIP

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        ipo = IPOEvent(symbol="TEST", company_name="Test Co", price_band_low=100, price_band_high=110)
        d = ipo.to_dict()
        assert d["symbol"] == "TEST"
        assert d["price_band"] == "100–110"

    def test_summary(self):
        """summary returns non-empty string."""
        ipo = IPOEvent(symbol="TEST", company_name="Test Co", issue_type=IssueType.IPO)
        s = ipo.summary()
        assert "Test Co" in s
        assert "IPO" in s


class TestCorporateAction:
    """Test suite for CorporateAction."""

    def test_default_dividend(self):
        """Corporate action with defaults."""
        ca = CorporateAction(symbol="HDFCBANK")
        assert ca.action_type == CorporateActionType.DIVIDEND

    def test_stock_split(self):
        """Stock split corporate action."""
        ca = CorporateAction(
            symbol="HDFCBANK",
            action_type=CorporateActionType.STOCK_SPLIT,
            ex_date="2026-09-01",
            details={"old_face_value": 10, "new_face_value": 1},
        )
        assert ca.action_type == CorporateActionType.STOCK_SPLIT
        assert ca.details["old_face_value"] == 10

    def test_bonus_issue(self):
        """Bonus issue corporate action."""
        ca = CorporateAction(
            symbol="RELIANCE",
            action_type=CorporateActionType.BONUS_ISSUE,
            details={"ratio": "1:1"},
        )
        assert ca.action_type == CorporateActionType.BONUS_ISSUE

    def test_to_dict(self):
        """to_dict returns serializable dict."""
        ca = CorporateAction(symbol="TCS", action_type=CorporateActionType.DIVIDEND, ex_date="2026-10-01")
        d = ca.to_dict()
        assert d["symbol"] == "TCS"
        assert d["ex_date"] == "2026-10-01"

    def test_summary(self):
        """summary returns non-empty string."""
        ca = CorporateAction(symbol="TCS", action_type=CorporateActionType.DIVIDEND, description="Dividend ₹50")
        s = ca.summary()
        assert "TCS" in s
        assert "DIVIDEND" in s
