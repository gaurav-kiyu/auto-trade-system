"""Backward-compatible alias module for shared config validation helpers."""

from core.shared_config_validate import (
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

__all__ = [
    "BROKER_ALLOWED_DRIVERS_INDEX",
    "BROKER_ALLOWED_DRIVERS_STOCK",
    "append_broker_api_config_errors",
    "append_common_risk_and_target_errors",
    "append_execution_hybrid_warnings",
    "append_normalized_execution_mode_errors",
    "append_nse_session_clock_errors",
    "append_portfolio_reconcile_errors",
    "append_scan_age_summary_errors",
    "append_scan_cross_warnings",
    "append_slot_and_trail_errors",
    "append_vix_band_relation_errors",
    "append_vix_modifier_errors",
    "append_weekday_bias_errors",
    "effective_broker_display_name",
    "effective_broker_driver",
]
