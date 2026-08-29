"""Tests for core/common_config_validate.py — re-export alias module."""

from __future__ import annotations

from core.common_config_validate import (
    BROKER_ALLOWED_DRIVERS_INDEX,
    BROKER_ALLOWED_DRIVERS_STOCK,
    append_broker_api_config_errors,
    append_common_risk_and_target_errors,
    append_execution_hybrid_warnings,
    append_normalized_execution_mode_errors,
    append_nse_session_clock_errors,
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
from core.shared_config_validate import (
    BROKER_ALLOWED_DRIVERS_INDEX as _ORIG_INDEX,
)
from core.shared_config_validate import (
    effective_broker_driver as _ORIG_DRIVER,
)


class TestCommonConfigValidate:
    """Verify re-exports match source module symbols."""

    def test_constants_reexported(self):
        assert BROKER_ALLOWED_DRIVERS_INDEX is _ORIG_INDEX

    def test_functions_reexported(self):
        assert effective_broker_driver is _ORIG_DRIVER
        assert callable(effective_broker_display_name)

    def test_append_functions_all_callable(self):
        funcs = [
            append_broker_api_config_errors,
            append_common_risk_and_target_errors,
            append_execution_hybrid_warnings,
            append_normalized_execution_mode_errors,
            append_nse_session_clock_errors,
            append_portfolio_reconcile_errors,
            append_scan_age_summary_errors,
            append_scan_cross_warnings,
            append_slot_and_trail_errors,
            append_vix_band_relation_errors,
            append_vix_modifier_errors,
            append_weekday_bias_errors,
        ]
        for fn in funcs:
            assert callable(fn), f"{fn.__name__} is not callable"

    def test_broker_driver_list_nonempty(self):
        assert isinstance(BROKER_ALLOWED_DRIVERS_INDEX, (list, tuple, frozenset))
        assert len(BROKER_ALLOWED_DRIVERS_INDEX) > 0
        assert isinstance(BROKER_ALLOWED_DRIVERS_STOCK, (list, tuple, frozenset))

    def test_effective_broker_display_name_returns_string(self):
        name = effective_broker_display_name({})
        assert isinstance(name, str)
