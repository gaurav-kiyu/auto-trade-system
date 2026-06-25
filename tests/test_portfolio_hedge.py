"""Tests for core.portfolio_hedge - portfolio-level delta hedging."""

from __future__ import annotations


from core.portfolio_hedge import PortfolioHedgeManager


class TestPortfolioHedgeManager:
    """Tests for PortfolioHedgeManager - volatility and delta hedging."""

    def setup_method(self) -> None:
        self.manager = PortfolioHedgeManager({})

    # ── Net Delta Calculation ───────────────────────────────────────────

    def test_calculate_net_delta_empty(self) -> None:
        assert self.manager.calculate_net_delta({}) == 0.0

    def test_calculate_net_delta_long(self) -> None:
        positions = {
            "NIFTY": {"signal": "CALL", "qty": 2},
            "BANKNIFTY": {"signal": "CALL", "qty": 1},
        }
        assert self.manager.calculate_net_delta(positions) == 3.0

    def test_calculate_net_delta_short(self) -> None:
        positions = {
            "NIFTY": {"signal": "PUT", "qty": 2},
            "BANKNIFTY": {"signal": "PUT", "qty": 1},
        }
        assert self.manager.calculate_net_delta(positions) == -3.0

    def test_calculate_net_delta_mixed(self) -> None:
        positions = {
            "NIFTY": {"signal": "CALL", "qty": 5},
            "BANKNIFTY": {"signal": "PUT", "qty": 3},
        }
        assert self.manager.calculate_net_delta(positions) == 2.0

    # ── Hedge Requirement ───────────────────────────────────────────────

    def test_no_positions_returns_none(self) -> None:
        result = self.manager.check_hedge_requirement({}, 15.0, 14.0)
        assert result is None

    def test_no_vix_spike_returns_none(self) -> None:
        positions = {"NIFTY": {"signal": "CALL", "qty": 2}}
        result = self.manager.check_hedge_requirement(positions, 15.0, 14.9)
        assert result is None

    def test_vix_spike_triggers_hedge(self) -> None:
        """VIX spike > 15% should trigger hedge."""
        positions = {"NIFTY": {"signal": "CALL", "qty": 2}}
        result = self.manager.check_hedge_requirement(positions, 17.5, 15.0)
        assert result is not None
        assert result.should_hedge is True
        assert result.direction == "PUT"  # Hedging long delta
        assert result.symbol == "NIFTY"

    def test_hedge_qty_is_30_percent_of_delta(self) -> None:
        """Hedge should cover 30% of net delta."""
        positions = {"NIFTY": {"signal": "CALL", "qty": 10}}
        result = self.manager.check_hedge_requirement(positions, 18.0, 15.0)
        assert result is not None
        assert result.qty == 3  # 30% of 10

    def test_net_short_gets_call_hedge(self) -> None:
        """Net short delta should hedge with CALLs."""
        positions = {"NIFTY": {"signal": "PUT", "qty": 5}}
        result = self.manager.check_hedge_requirement(positions, 18.0, 15.0)
        assert result is not None
        assert result.direction == "CALL"

    def test_small_vix_spike_no_hedge(self) -> None:
        """Small VIX change below threshold should not hedge."""
        positions = {"NIFTY": {"signal": "CALL", "qty": 2}}
        result = self.manager.check_hedge_requirement(positions, 15.2, 15.0)
        assert result is None

    def test_custom_hedge_threshold(self) -> None:
        """Custom config threshold should override default."""
        mgr = PortfolioHedgeManager({"hedge_vix_spike_pct": 0.05})
        positions = {"NIFTY": {"signal": "CALL", "qty": 2}}
        # 5% spike should trigger with custom 5% threshold
        result = mgr.check_hedge_requirement(positions, 15.75, 15.0)
        assert result is not None
        assert result.should_hedge is True

    def test_custom_max_hedge_ratio(self) -> None:
        """Custom hedge ratio should affect calculation."""
        mgr = PortfolioHedgeManager({"max_hedge_ratio": 0.5})
        assert mgr.max_hedge_ratio == 0.5

    def test_zero_prev_vix_uses_fallback(self) -> None:
        """When prev_vix is 0, vix_change should not cause division error."""
        positions = {"NIFTY": {"signal": "CALL", "qty": 2}}
        result = self.manager.check_hedge_requirement(positions, 15.0, 0.0)
        assert result is None  # vix_change = 0, no spike detected
