"""Tests for core.domains.fixed_income - Fixed Income domain models.

Covers:
  - CouponSchedule validation
  - Bond validation, dirty price, current yield
  - GovernmentSecurity validation
  - CorporateBond validation
  - TBill validation
  - BondPosition validation
  - Edge cases
"""

from __future__ import annotations

from datetime import date

import pytest
from core.domains.fixed_income import (
    Bond,
    BondPosition,
    CorporateBond,
    GovernmentSecurity,
    SecurityType,
    TBill,
)
from core.domains.fixed_income.models import CouponSchedule


class TestCouponSchedule:
    def test_valid_schedule(self):
        cs = CouponSchedule(0.0725, 2)
        assert cs.coupon_per_period == 0.03625

    def test_negative_coupon_raises(self):
        with pytest.raises(ValueError, match="Coupon rate cannot be negative"):
            CouponSchedule(-0.05, 2)

    def test_invalid_frequency_raises(self):
        with pytest.raises(ValueError, match="Frequency must be 1, 2, 4, or 12"):
            CouponSchedule(0.07, 3)


class TestBond:
    def test_valid_bond(self):
        bond = Bond("IN002023Z012", "7.25% GS 2033", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, last_price=102.50)
        assert bond.symbol == "IN002023Z012"
        assert bond.dirty_price == 102.50  # No accrued interest

    def test_current_yield(self):
        bond = Bond("IN002023Z012", "Bond", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, last_price=105.0,
                    coupon=CouponSchedule(0.07, 2))
        cy = bond.current_yield
        assert cy > 0

    def test_current_yield_zero_when_no_coupon(self):
        bond = Bond("BOND001", "Bond", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, last_price=100)
        assert bond.current_yield == 0.0

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Last price cannot be negative"):
            Bond("X", "Bond", SecurityType.GOVERNMENT_SECURITY, last_price=-10)

    def test_dirty_price_with_accrued(self):
        bond = Bond("BOND001", "Bond", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, last_price=100, accrued_interest=2.50)
        assert bond.dirty_price == 102.50

    def test_years_to_maturity(self):
        bond = Bond("BOND001", "Bond", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, maturity_date=date(2036, 6, 15))
        assert bond.years_to_maturity > 0


class TestGovernmentSecurity:
    def test_valid_gsec(self):
        gsec = GovernmentSecurity("IN002023Z012", "7.25% GS 2033",
                                   SecurityType.GOVERNMENT_SECURITY)
        assert gsec.is_sdl is False

    def test_valid_sdl(self):
        sdl = GovernmentSecurity("IN012025Z001", "MP SDL 2035",
                                  SecurityType.STATE_DEVELOPMENT_LOAN,
                                  is_sdl=True, state_name="Madhya Pradesh")
        assert sdl.is_sdl is True

    def test_sdl_without_state_raises(self):
        with pytest.raises(ValueError, match="SDL must have a state_name"):
            GovernmentSecurity("SDL001", "SDL", SecurityType.STATE_DEVELOPMENT_LOAN,
                               is_sdl=True, state_name="")


class TestCorporateBond:
    def test_valid_secured_bond(self):
        bond = CorporateBond("CORP001", "Reliance 8% 2030",
                              SecurityType.CORPORATE_BOND,
                              issuer="Reliance Industries Ltd",
                              issue_type="secured")
        assert bond.issuer == "Reliance Industries Ltd"

    def test_invalid_issue_type_raises(self):
        with pytest.raises(ValueError, match="Issue type must be 'secured' or 'unsecured'"):
            CorporateBond("CB001", "Bond", SecurityType.CORPORATE_BOND, issue_type="hybrid")

    def test_convertible_must_have_price(self):
        with pytest.raises(ValueError, match="Convertible bonds must have a positive conversion price"):
            CorporateBond("CB001", "Bond", SecurityType.CORPORATE_BOND,
                         is_convertible=True, conversion_price=0)


class TestTBill:
    def test_valid_91_day(self):
        tbill = TBill("91D001", 91, face_value=100, discounted_price=97.50)
        assert tbill.days_to_maturity >= 0
        assert tbill.discount_amount == 2.50

    def test_valid_364_day(self):
        tbill = TBill("364D001", 364, face_value=100, discounted_price=92.00)
        assert tbill.annualized_yield > 0

    def test_invalid_tenor_raises(self):
        with pytest.raises(ValueError, match="T-Bill tenor must be 91, 182, or 364"):
            TBill("X", 180)

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="Discounted price cannot be negative"):
            TBill("X", 91, discounted_price=-10)


class TestBondPosition:
    def test_valid_position(self):
        bond = Bond("BOND001", "Bond", SecurityType.GOVERNMENT_SECURITY,
                    face_value=100, last_price=102.50)
        pos = BondPosition(bond, 100, 102.50, 103.50)
        assert pos.investment_value == 10250.0
        assert pos.market_value == 10350.0

    def test_negative_current_price_raises(self):
        bond = Bond("X", "Bond", SecurityType.GOVERNMENT_SECURITY)
        with pytest.raises(ValueError, match="Current price cannot be negative"):
            BondPosition(bond, 100, 100, -10)
