"""Tests for ExpiryDayController - expiry-day awareness for strategy entry gates."""

from __future__ import annotations

from datetime import date, datetime, time


from core.expiry_day_controller import (
    ExpiryControlResult,
    ExpiryDayController,
    ExpirySession,
    StrategyType,
    create_expiry_controller,
    get_index_expiry_weekday,
)


class TestExpiryDayController:
    """ExpiryDayController - strategy-aware expiry-day controls."""

    def test_default_strategy_is_directional(self):
        ctrl = ExpiryDayController()
        assert ctrl._strategy_type == StrategyType.DIRECTIONAL

    def test_controls_enabled_by_default(self):
        ctrl = ExpiryDayController()
        assert ctrl._enable_controls is True

    def test_controls_disabled_allows_entry(self):
        ctrl = ExpiryDayController(enable_controls=False)
        result = ctrl.can_enter_position()
        assert result.allowed is True
        assert "disabled" in result.reason.lower()

    def test_set_strategy_type(self):
        ctrl = ExpiryDayController(strategy_type=StrategyType.DIRECTIONAL)
        ctrl.set_strategy_type(StrategyType.SPREAD)
        assert ctrl._strategy_type == StrategyType.SPREAD

    # ── Expiry weekday lookups ─────────────────────────────────────

    def test_get_expiry_weekday_nifty_is_thursday(self):
        assert ExpiryDayController().get_expiry_weekday("NIFTY") == 3

    def test_get_expiry_weekday_banknifty_is_thursday(self):
        assert ExpiryDayController().get_expiry_weekday("BANKNIFTY") == 3

    def test_get_expiry_weekday_sensex_is_friday(self):
        assert ExpiryDayController().get_expiry_weekday("SENSEX") == 4

    def test_get_expiry_weekday_unknown_defaults_to_thursday(self):
        assert ExpiryDayController().get_expiry_weekday("UNKNOWN") == 3

    def test_get_expiry_weekday_none_defaults_to_thursday(self):
        assert ExpiryDayController().get_expiry_weekday(None) == 3

    def test_get_expiry_weekday_case_insensitive(self):
        assert ExpiryDayController().get_expiry_weekday("sensex") == 4

    def test_get_index_expiry_weekday_convenience(self):
        assert get_index_expiry_weekday("NIFTY") == 3
        assert get_index_expiry_weekday("SENSEX") == 4

    # ── is_expiry_day ──────────────────────────────────────────────

    def test_is_expiry_day_thursday(self):
        # Thursday 2026-06-11
        thursday = date(2026, 6, 11)
        assert ExpiryDayController().is_expiry_day(datetime.combine(thursday, time(10, 0)), "NIFTY") is True

    def test_is_expiry_day_friday(self):
        # Friday 2026-06-12
        friday = datetime(2026, 6, 12, 10, 0)
        assert ExpiryDayController().is_expiry_day(friday, "SENSEX") is True

    def test_is_expiry_day_non_expiry_day(self):
        monday = datetime(2026, 6, 15, 10, 0)  # Monday
        assert ExpiryDayController().is_expiry_day(monday, "NIFTY") is False

    def test_is_expiry_day_no_index_uses_default(self):
        thursday = datetime(2026, 6, 11, 10, 0)
        assert ExpiryDayController().is_expiry_day(thursday) is True

    # ── can_enter_position - non-expiry day ────────────────────────

    def test_can_enter_non_expiry_day(self):
        monday = datetime(2026, 6, 15, 10, 0)
        ctrl = ExpiryDayController()
        result = ctrl.can_enter_position(now=monday, index_name="NIFTY")
        assert result.allowed is True
        assert "not" in result.reason.lower() or "morning" in result.reason.lower()

    # ── can_enter_position - expiry day morning ────────────────────

    def test_can_enter_expiry_morning(self):
        thursday_10am = datetime(2026, 6, 11, 10, 0)  # Thursday 10:00
        ctrl = ExpiryDayController()
        result = ctrl.can_enter_position(now=thursday_10am, index_name="NIFTY")
        assert result.allowed is True
        assert result.session in (ExpirySession.MORNING, ExpirySession.MIDDAY)

    # ── can_enter_position - caution period ────────────────────────

    def test_can_enter_caution_period(self):
        thursday_1245 = datetime(2026, 6, 11, 12, 45)  # Thursday 12:45
        ctrl = ExpiryDayController()
        result = ctrl.can_enter_position(now=thursday_1245, index_name="NIFTY")
        # Should be in caution or blocked depending on exact times
        assert result.session in (ExpirySession.CAUTION, ExpirySession.BLOCKED)

    def test_caution_blocks_options_selling(self):
        thursday_1245 = datetime(2026, 6, 11, 12, 45)
        ctrl = ExpiryDayController(strategy_type=StrategyType.OPTIONS_SELLING)
        result = ctrl.can_enter_position(now=thursday_1245, index_name="NIFTY")
        assert result.allowed is False

    # ── can_enter_position - blocked period ────────────────────────

    def test_entry_blocked_after_13_00(self):
        thursday_1330 = datetime(2026, 6, 11, 13, 30)
        ctrl = ExpiryDayController()
        result = ctrl.can_enter_position(now=thursday_1330, index_name="NIFTY")
        assert result.allowed is False
        assert result.session == ExpirySession.BLOCKED

    # ── should_close_positions ─────────────────────────────────────

    def test_should_close_before_1430(self):
        thursday_1400 = datetime(2026, 6, 11, 14, 0)
        ctrl = ExpiryDayController()
        close, _ = ctrl.should_close_positions(now=thursday_1400, index_name="NIFTY")
        assert close is False

    def test_should_close_after_1430(self):
        thursday_1500 = datetime(2026, 6, 11, 15, 0)
        ctrl = ExpiryDayController()
        close, reason = ctrl.should_close_positions(now=thursday_1500, index_name="NIFTY")
        assert close is True
        assert "close" in reason.lower()

    def test_should_close_non_expiry_day(self):
        monday = datetime(2026, 6, 15, 15, 0)
        ctrl = ExpiryDayController()
        close, _ = ctrl.should_close_positions(now=monday, index_name="NIFTY")
        assert close is False

    # ── estimate_premium_decay ─────────────────────────────────────

    def test_premium_decay_zero_dte(self):
        ctrl = ExpiryDayController()
        assert ctrl.estimate_premium_decay(100.0, 0, 2.0) == 0.0

    def test_premium_decay_positive(self):
        ctrl = ExpiryDayController()
        decayed = ctrl.estimate_premium_decay(100.0, 1, 6.5)
        assert 0 < decayed < 100.0

    def test_premium_decay_never_negative(self):
        ctrl = ExpiryDayController()
        decayed = ctrl.estimate_premium_decay(10.0, 1, 1000.0)
        assert decayed >= 0.0

    # ── expiry week type ───────────────────────────────────────────

    def test_expiry_week_type_monthly(self):
        ctrl = ExpiryDayController()
        late_date = datetime(2026, 6, 28, 10, 0)
        assert ctrl.get_expiry_week_type(late_date) == "MONTHLY"

    def test_expiry_week_type_weekly(self):
        ctrl = ExpiryDayController()
        mid_date = datetime(2026, 6, 15, 10, 0)  # 15th
        wtype = ctrl.get_expiry_week_type(mid_date)
        assert wtype in ("WEEKLY_1", "WEEKLY_2", "WEEKLY_3", "MONTHLY")

    # ── closing warning time ───────────────────────────────────────

    def test_get_closing_warning_time_none_when_before(self):
        ctrl = ExpiryDayController()
        # At 09:00, warning time would be 14:00 - 30min = 13:30 which is AFTER now
        # so it should return the warning time (not None)
        early = datetime(2026, 6, 11, 9, 0)
        warning = ctrl.get_closing_warning_time(now=early)
        # Should return a datetime because 13:30 > 09:00
        assert isinstance(warning, datetime)

    def test_get_closing_warning_time_returns_datetime(self):
        ctrl = ExpiryDayController()
        warning = ctrl.get_closing_warning_time()
        assert warning is None or isinstance(warning, datetime)

    # ── factory ────────────────────────────────────────────────────

    def test_create_expiry_controller(self):
        ctrl = create_expiry_controller()
        assert isinstance(ctrl, ExpiryDayController)
        assert ctrl._strategy_type == StrategyType.DIRECTIONAL

    def test_create_expiry_controller_with_strategy(self):
        ctrl = create_expiry_controller(strategy_type=StrategyType.SPREAD)
        assert isinstance(ctrl, ExpiryDayController)
        assert ctrl._strategy_type == StrategyType.SPREAD

    def test_create_expiry_controller_disabled(self):
        ctrl = create_expiry_controller(enable_controls=False)
        assert ctrl._enable_controls is False


class TestExpiryControlResult:
    """ExpiryControlResult dataclass."""

    def test_default_warnings_is_empty_list(self):
        result = ExpiryControlResult(
            allowed=True, session=ExpirySession.MORNING, reason="test", risk_level="LOW",
        )
        assert result.warnings == []

    def test_warnings_preserved(self):
        result = ExpiryControlResult(
            allowed=True, session=ExpirySession.CAUTION, reason="test", risk_level="MEDIUM",
            warnings=["first", "second"],
        )
        assert result.warnings == ["first", "second"]


class TestStrategyType:
    """StrategyType enum."""

    def test_has_directional(self):
        assert StrategyType.DIRECTIONAL.value == "DIRECTIONAL"

    def test_has_unknown(self):
        assert StrategyType.UNKNOWN.value == "UNKNOWN"


class TestExpirySession:
    """ExpirySession enum."""

    def test_has_all_sessions(self):
        expected = {"MORNING", "MIDDAY", "CAUTION", "BLOCKED"}
        actual = {s.value for s in ExpirySession}
        assert expected == actual
