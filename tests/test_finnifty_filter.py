"""Tests for core.finnifty_filter - FINNIFTY-specific entry filter."""

from __future__ import annotations

from core.finnifty_filter import FINNIFTYFilter, FINNIFTYFilterConfig, create_finnifty_filter


class TestFINNIFTYFilterConfig:
    """Tests for FINNIFTYFilterConfig dataclass."""

    def test_defaults(self) -> None:
        cfg = FINNIFTYFilterConfig()
        assert cfg.enabled is True
        assert cfg.min_score_offset == 5
        assert cfg.min_iv_rank == 25.0
        assert cfg.require_trending_regime is True


class TestFINNIFTYFilter:
    """Tests for FINNIFTYFilter - additional filters for FINNIFTY."""

    def setup_method(self) -> None:
        self.filter = FINNIFTYFilter(FINNIFTYFilterConfig())

    def test_disabled_filter_allows_all(self) -> None:
        f = FINNIFTYFilter(FINNIFTYFilterConfig(enabled=False))
        ok, reason = f.should_allow_entry("FINNIFTY", 50, 10.0, "CHOPPY")
        assert ok is True
        assert reason == ""

    def test_non_finnifty_index_allowed(self) -> None:
        ok, reason = self.filter.should_allow_entry("NIFTY", 50, 30.0, "CHOPPY")
        assert ok is True
        assert reason == ""

    def test_finnifty_below_min_score(self) -> None:
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 50, 30.0, "TRENDING")
        assert ok is False
        assert "below adjusted threshold" in reason

    def test_finnifty_above_min_score_allowed(self) -> None:
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 70, 30.0, "TRENDING")
        assert ok is True

    def test_finnifty_below_min_iv_rank(self) -> None:
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 70, 15.0, "TRENDING")
        assert ok is False
        assert "IV rank" in reason

    def test_finnifty_wrong_regime(self) -> None:
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 70, 30.0, "CHOPPY")
        assert ok is False
        assert "regime" in reason.lower()

    def test_finnifty_bullish_regime_allowed(self) -> None:
        """BULLISH regime should be accepted as trending-like."""
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 70, 30.0, "BULLISH")
        assert ok is True

    def test_finnifty_all_conditions_met(self) -> None:
        ok, reason = self.filter.should_allow_entry("FINNIFTY", 70, 30.0, "TRENDING")
        assert ok is True

    def test_custom_score_offset(self) -> None:
        f = FINNIFTYFilter(FINNIFTYFilterConfig(min_score_offset=10))
        ok, reason = f.should_allow_entry("FINNIFTY", 65, 30.0, "TRENDING")
        assert ok is False  # 65 < 60+10=70
        ok, reason = f.should_allow_entry("FINNIFTY", 70, 30.0, "TRENDING")
        assert ok is True  # 70 >= 70

    def test_no_regime_requirement(self) -> None:
        f = FINNIFTYFilter(FINNIFTYFilterConfig(require_trending_regime=False))
        ok, reason = f.should_allow_entry("FINNIFTY", 70, 30.0, "CHOPPY")
        assert ok is True

    def test_get_adjusted_threshold_enabled(self) -> None:
        assert self.filter.get_adjusted_threshold() == 65  # 60 + 5

    def test_get_adjusted_threshold_disabled(self) -> None:
        f = FINNIFTYFilter(FINNIFTYFilterConfig(enabled=False))
        assert f.get_adjusted_threshold() == 60  # base only


class TestCreateFinniftyFilter:
    """Tests for create_finnifty_filter factory function."""

    def test_default_config(self) -> None:
        f = create_finnifty_filter({})
        assert f.config.enabled is True
        assert f.config.min_score_offset == 5

    def test_custom_config(self) -> None:
        f = create_finnifty_filter({
            "FINNIFTY_SPECIFIC_ENABLED": False,
            "FINNIFTY_MIN_SCORE_OFFSET": 10,
            "FINNIFTY_MIN_IV_RANK": 30.0,
            "FINNIFTY_REGIME_REQUIRE_TRENDING": False,
        })
        assert f.config.enabled is False
        assert f.config.min_score_offset == 10
        assert f.config.min_iv_rank == 30.0
        assert f.config.require_trending_regime is False
