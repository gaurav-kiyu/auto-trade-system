"""Unit tests for core.common_config_validate."""

from __future__ import annotations

from core.common_config_validate import (
    BROKER_ALLOWED_DRIVERS_INDEX,
    append_broker_api_config_errors,
    append_nse_session_clock_errors,
    append_common_risk_and_target_errors,
    append_execution_hybrid_warnings,
    append_normalized_execution_mode_errors,
    append_portfolio_reconcile_errors,
    append_scan_age_summary_errors,
    append_scan_cross_warnings,
    append_slot_and_trail_errors,
    append_vix_band_relation_errors,
    append_vix_modifier_errors,
    append_weekday_bias_errors,
    effective_broker_display_name,
    effective_broker_driver,
)


def test_weekday_bias_bad_day():
    errors: list[str] = []
    append_weekday_bias_errors(errors, {"WEEKDAY_BIAS": {"Saturday": 1.0}})
    assert any("unknown day" in e for e in errors)


def test_vix_modifiers_out_of_range():
    errors: list[str] = []
    append_vix_modifier_errors(errors, {"VIX_RISING_THRESHOLD_BONUS": 99})
    assert any("VIX_RISING" in e for e in errors)


def test_nse_session_clock_inverted_cash_window():
    errors: list[str] = []
    append_nse_session_clock_errors(
        errors,
        {
            "NSE_CASH_SESSION_START_HOUR": 15,
            "NSE_CASH_SESSION_START_MINUTE": 30,
            "NSE_CASH_SESSION_END_HOUR": 9,
            "NSE_CASH_SESSION_END_MINUTE": 15,
        },
    )
    assert any("NSE cash session" in e for e in errors)


def test_nse_continuous_before_cash_open():
    errors: list[str] = []
    append_nse_session_clock_errors(
        errors,
        {
            "NSE_CASH_SESSION_START_HOUR": 9,
            "NSE_CASH_SESSION_START_MINUTE": 15,
            "NSE_CASH_SESSION_END_HOUR": 15,
            "NSE_CASH_SESSION_END_MINUTE": 20,
            "NSE_CONTINUOUS_TRADE_START_HOUR": 9,
            "NSE_CONTINUOUS_TRADE_START_MINUTE": 10,
        },
    )
    assert any("CONTINUOUS_TRADE_START" in e for e in errors)


def test_portfolio_reconcile():
    errors: list[str] = []
    append_portfolio_reconcile_errors(errors, {"PORTFOLIO_MAX_SL_RISK_PCT": 0.01})
    assert any("PORTFOLIO_MAX_SL_RISK" in e for e in errors)


def test_common_risk_missing_fixed():
    errors: list[str] = []
    append_common_risk_and_target_errors(
        errors,
        risk_mode="FIXED",
        risk_fixed_amount=0,
        brokerage_per_trade=10,
        min_net_rr=1.5,
        daily_target=100,
        sl_warn_pct=0.5,
        min_trade_duration_mins=5,
        sl_pct=0.9,
        target_pct=1.1,
    )
    assert "RISK_FIXED_AMOUNT>0" in errors


def test_vix_band_order():
    errors: list[str] = []
    append_vix_band_relation_errors(
        errors,
        vix_block_threshold=20.0,
        vix_halt_threshold=25.0,
        vix_size_med_threshold=40.0,
        vix_size_high_threshold=35.0,
    )
    assert len(errors) == 2


def test_slot_errors():
    errors: list[str] = []
    append_slot_and_trail_errors(
        errors,
        max_open=0,
        max_trades_day=1,
        max_drawdown=0.5,
        trail_activate=1.2,
        partial_exit_mult=1.1,
    )
    assert "MAX_OPEN>=1" in errors


def test_scan_cross_warning():
    warnings: list[str] = []
    append_scan_cross_warnings(
        warnings,
        scan_interval=120,
        signal_max_age=60,
        max_position_age=300,
        summary_interval=400,
    )
    assert len(warnings) == 2


def test_execution_mode_coerces_unknown_to_manual_no_error():
    """normalize_execution_mode maps unknown strings to MANUAL, so validate stays non-fatal."""
    errors: list[str] = []
    append_normalized_execution_mode_errors(errors, "not-a-mode")
    assert not errors


def test_effective_broker_driver_respects_backend_fallback():
    assert effective_broker_driver({}, default_backend="GENERIC") == "GENERIC"
    assert effective_broker_driver({"BROKER_BACKEND": "KITE"}, default_backend="GENERIC") == "KITE"
    assert effective_broker_driver({"BROKER_DRIVER": "ANGEL", "BROKER_BACKEND": "KITE"}, default_backend="GENERIC") == "ANGEL"


def test_effective_broker_display_name():
    assert effective_broker_display_name({"BROKER_NAME": "  X  "}, default_backend="GENERIC") == "X"
    assert effective_broker_display_name({"BROKER_DRIVER": "KITE"}, default_backend="GENERIC") == "Kite"


def test_append_broker_api_config_errors_custom_without_factory():
    errors: list[str] = []
    append_broker_api_config_errors(
        errors,
        {"BROKER_DRIVER": "CUSTOM", "BROKER_API_ENABLED": True},
        broker_api_enabled=True,
        default_backend="GENERIC",
        allowed_drivers_without_factory=BROKER_ALLOWED_DRIVERS_INDEX,
    )
    assert any("BROKER_CUSTOM_FACTORY" in e for e in errors)


def test_append_execution_hybrid_warnings_auto():
    w: list[str] = []
    append_execution_hybrid_warnings(w, {"EXECUTION_MODE": "AUTO"}, broker_api_enabled=False)
    assert any("AUTO" in x for x in w)
