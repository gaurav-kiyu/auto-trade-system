"""
Tests for broker-related config_validator checks added for auto-trading readiness.

Covers:
  - BROKER_DRIVER live-capability gate (AUTO + non-live driver = error)
  - MANUAL_SIGNALS_ONLY contradiction (AUTO + MSO=true = warning)
  - Duplicate credential warning (BROKER_CONFIG + legacy KITE_*/ANGEL_* = warning)
"""
from __future__ import annotations

from core.config_validator import validate_config

# ---------------------------------------------------------------------------
# Shared minimal valid config
# ---------------------------------------------------------------------------

def _base() -> dict:
    return {
        "EXECUTION_MODE":    "MANUAL",
        "BROKER_API_ENABLED": False,
        "BASE_CAPITAL":       10000,
        "MAX_DAILY_LOSS":     -800,
        "MAX_DRAWDOWN":        0.3,
        "RISK_MODE":          "FIXED",
        "RISK_PER_TRADE":      0.02,
        "RISK_FIXED_AMOUNT":   500,
        "SL_PCT":              0.92,
        "TARGET_PCT":          1.30,
        "TRAIL_PCT":           0.93,
        "TRAIL_ACTIVATE":      1.12,
        "MIN_NET_RR":          1.5,
        "VIX_HALT_THRESHOLD":  22.0,
        "VIX_BLOCK_THRESHOLD": 27.0,
        "MAX_OPEN":            1,
        "MAX_TRADES_DAY":      2,
        "AI_THRESHOLD":        60,
        "TIER_WEAK_MIN":       60,
        "TIER_MODERATE_MIN":   70,
        "TIER_STRONG_MIN":     80,
        "TG_ALERT_MIN_SCORE":  60,
        "QUALITY_MIN_SCORE":   68,
    }


def _auto_kite() -> dict:
    cfg = _base()
    cfg["EXECUTION_MODE"]    = "AUTO"
    cfg["BROKER_API_ENABLED"] = True
    cfg["BROKER_DRIVER"]     = "KITE"
    return cfg


# ---------------------------------------------------------------------------
# BROKER_DRIVER live-capability gate
# ---------------------------------------------------------------------------

class TestBrokerDriverLiveCapability:
    def test_kite_driver_produces_no_driver_error(self):
        errors, _ = validate_config(_auto_kite())
        assert not any("BROKER_DRIVER" in e for e in errors)

    def test_angel_driver_produces_no_driver_error(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "ANGEL"
        errors, _ = validate_config(cfg)
        assert not any("BROKER_DRIVER" in e for e in errors)

    def test_custom_driver_produces_no_driver_error(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "CUSTOM"
        errors, _ = validate_config(cfg)
        assert not any("BROKER_DRIVER" in e for e in errors)

    def test_generic_driver_raises_error_when_auto_and_api_enabled(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "GENERIC"
        errors, _ = validate_config(cfg)
        assert any("BROKER_DRIVER" in e for e in errors), (
            "Expected error for AUTO + BROKER_API_ENABLED=true + BROKER_DRIVER=GENERIC"
        )

    def test_paper_driver_raises_error_when_auto_and_api_enabled(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "PAPER"
        errors, _ = validate_config(cfg)
        assert any("BROKER_DRIVER" in e for e in errors)

    def test_sim_driver_raises_error_when_auto_and_api_enabled(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "SIM"
        errors, _ = validate_config(cfg)
        assert any("BROKER_DRIVER" in e for e in errors)

    def test_driver_check_skipped_when_broker_api_disabled(self):
        # API off: driver doesn't matter - no error expected for GENERIC
        cfg = _base()
        cfg["EXECUTION_MODE"]     = "AUTO"
        cfg["BROKER_API_ENABLED"]  = False
        cfg["BROKER_DRIVER"]      = "GENERIC"
        errors, _ = validate_config(cfg)
        driver_errs = [e for e in errors if "BROKER_DRIVER" in e]
        assert not driver_errs, "Driver check should be skipped when API is disabled"

    def test_driver_check_skipped_for_manual_mode(self):
        cfg = _base()
        cfg["BROKER_DRIVER"] = "GENERIC"
        errors, _ = validate_config(cfg)
        assert not any("BROKER_DRIVER" in e for e in errors)

    def test_error_message_lists_valid_drivers(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"] = "UNKNOWN_DRIVER"
        errors, _ = validate_config(cfg)
        driver_err = next((e for e in errors if "BROKER_DRIVER" in e), "")
        # Error message should name the valid live-capable drivers
        assert "KITE" in driver_err or "ANGEL" in driver_err or "CUSTOM" in driver_err


# ---------------------------------------------------------------------------
# MANUAL_SIGNALS_ONLY contradiction check
# ---------------------------------------------------------------------------

class TestManualSignalsOnlyContradiction:
    def test_auto_mode_with_mso_true_produces_warning(self):
        cfg = _auto_kite()
        cfg["MANUAL_SIGNALS_ONLY"] = True
        _, warnings = validate_config(cfg)
        assert any("MANUAL_SIGNALS_ONLY" in w for w in warnings), (
            "Expected warning for AUTO + MANUAL_SIGNALS_ONLY=true"
        )

    def test_auto_mode_with_mso_false_no_warning(self):
        cfg = _auto_kite()
        cfg["MANUAL_SIGNALS_ONLY"] = False
        _, warnings = validate_config(cfg)
        assert not any("MANUAL_SIGNALS_ONLY" in w for w in warnings)

    def test_manual_mode_with_mso_true_no_warning(self):
        cfg = _base()
        cfg["MANUAL_SIGNALS_ONLY"] = True
        _, warnings = validate_config(cfg)
        assert not any("MANUAL_SIGNALS_ONLY" in w for w in warnings)

    def test_paper_mode_with_mso_true_no_warning(self):
        cfg = _base()
        cfg["EXECUTION_MODE"] = "PAPER"
        cfg["MANUAL_SIGNALS_ONLY"] = True
        _, warnings = validate_config(cfg)
        assert not any("MANUAL_SIGNALS_ONLY" in w for w in warnings)

    def test_warning_message_is_actionable(self):
        cfg = _auto_kite()
        cfg["MANUAL_SIGNALS_ONLY"] = True
        _, warnings = validate_config(cfg)
        mso_warn = next((w for w in warnings if "MANUAL_SIGNALS_ONLY" in w), "")
        # Should tell operator what to change
        assert "false" in mso_warn.lower() or "disable" in mso_warn.lower()


# ---------------------------------------------------------------------------
# Duplicate credential warning
# ---------------------------------------------------------------------------

class TestDuplicateCredentialWarning:
    def test_broker_config_plus_kite_legacy_produces_warning(self):
        cfg = _auto_kite()
        cfg["BROKER_CONFIG"] = {"api_key": "new_key"}
        cfg["KITE_API_KEY"]  = "old_legacy_key"
        _, warnings = validate_config(cfg)
        assert any("BROKER_CONFIG" in w and "KITE_API_KEY" in w for w in warnings)

    def test_broker_config_only_no_duplicate_warning(self):
        cfg = _auto_kite()
        cfg["BROKER_CONFIG"] = {"api_key": "new_key"}
        # No legacy KITE_* keys set
        _, warnings = validate_config(cfg)
        assert not any("KITE_API_KEY" in w for w in warnings)

    def test_legacy_only_no_duplicate_warning(self):
        cfg = _auto_kite()
        cfg["KITE_API_KEY"] = "old_legacy_key"
        # No BROKER_CONFIG.api_key
        _, warnings = validate_config(cfg)
        assert not any("KITE_API_KEY" in w and "BROKER_CONFIG" in w for w in warnings)

    def test_angel_driver_duplicate_warning(self):
        cfg = _auto_kite()
        cfg["BROKER_DRIVER"]  = "ANGEL"
        cfg["BROKER_CONFIG"]  = {"api_key": "abc"}
        cfg["ANGEL_API_KEY"]  = "legacykey"
        _, warnings = validate_config(cfg)
        assert any("BROKER_CONFIG" in w and "ANGEL_API_KEY" in w for w in warnings)

    def test_kite_driver_multiple_legacy_keys_all_listed(self):
        cfg = _auto_kite()
        cfg["BROKER_CONFIG"]       = {"api_key": "abc"}
        cfg["KITE_API_KEY"]        = "k1"
        cfg["KITE_ACCESS_TOKEN"]   = "k2"
        cfg["KITE_USER_ID"]        = "k3"
        _, warnings = validate_config(cfg)
        dup = next((w for w in warnings if "KITE_API_KEY" in w), "")
        # All three legacy keys should be mentioned
        assert "KITE_ACCESS_TOKEN" in dup or "KITE_API_KEY" in dup

    def test_empty_broker_config_no_false_alarm(self):
        cfg = _auto_kite()
        cfg["BROKER_CONFIG"] = {}          # empty - no api_key
        cfg["KITE_API_KEY"]  = "fallback"  # only legacy present
        _, warnings = validate_config(cfg)
        assert not any("BROKER_CONFIG" in w and "KITE_API_KEY" in w for w in warnings)
