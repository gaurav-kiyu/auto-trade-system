"""
Tests for ConfigValidator — startup safety configuration validation.

Covers:
- ConfigIssue and ConfigValidationResult dataclasses
- Execution mode validation
- Data provider priority and enabled validation
- Numeric range validation (number_between)
- Broker name/driver warnings
- Audit log file validation
- Edge cases (empty config, None values, type mismatches)
"""

from __future__ import annotations

import warnings

import pytest
from core.config_engine import ConfigIssue, ConfigValidationResult, ConfigValidator

# ── ConfigIssue Dataclass ──────────────────────────────────────────────────


class TestConfigIssue:
    def test_creation(self):
        issue = ConfigIssue(level="error", key="TEST_KEY", message="must be a number")
        assert issue.level == "error"
        assert issue.key == "TEST_KEY"
        assert issue.message == "must be a number"

    def test_frozen(self):
        issue = ConfigIssue(level="error", key="K", message="msg")
        with pytest.raises(AttributeError):
            issue.key = "OTHER"  # type: ignore[misc]

    def test_warning_level(self):
        issue = ConfigIssue(level="warning", key="BROKER_NAME", message="empty")
        assert issue.level == "warning"


# ── ConfigValidationResult Dataclass ──────────────────────────────────────


class TestConfigValidationResult:
    def test_ok_when_no_errors(self):
        result = ConfigValidationResult(errors=[], warnings=[])
        assert result.ok is True

    def test_not_ok_with_errors(self):
        result = ConfigValidationResult(
            errors=[ConfigIssue("error", "K", "msg")],
            warnings=[],
        )
        assert result.ok is False

    def test_warnings_dont_affect_ok(self):
        result = ConfigValidationResult(
            errors=[],
            warnings=[ConfigIssue("warning", "K", "warn")],
        )
        assert result.ok is True


# ── ConfigValidator — Execution Mode ──────────────────────────────────────


class TestExecutionMode:
    @pytest.fixture
    def base_cfg(self) -> dict:
        return {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
            "LATENCY_BUDGET_MS": 500,
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.10,
            "AUDIT_RETENTION_DAYS": 30,
            "RETENTION_REPORTS_MAX_FILES": 10,
            "RETENTION_LOGS_MAX_FILES": 10,
            "RETENTION_BACKUPS_MAX_FILES": 10,
            "AUDIT_LOG_ENABLED": False,
        }

    def test_valid_modes(self, base_cfg: dict):
        for mode in ("MANUAL", "PAPER", "AUTO", "SIGNALS"):
            cfg = {**base_cfg, "EXECUTION_MODE": mode}
            result = ConfigValidator(cfg).validate()
            assert result.ok, f"Mode {mode} should be valid"

    def test_lowercase_mode(self, base_cfg: dict):
        """Lowercase modes are accepted (uppercased in validator)."""
        cfg = {**base_cfg, "EXECUTION_MODE": "paper"}
        result = ConfigValidator(cfg).validate()
        assert result.ok

    def test_invalid_mode(self, base_cfg: dict):
        cfg = {**base_cfg, "EXECUTION_MODE": "INVALID"}
        result = ConfigValidator(cfg).validate()
        assert not result.ok
        assert any(e.key == "EXECUTION_MODE" for e in result.errors)

    def test_missing_mode_defaults_to_manual(self, base_cfg: dict):
        """Missing EXECUTION_MODE defaults to MANUAL in validator."""
        result = ConfigValidator(base_cfg).validate()
        assert not any(e.key == "EXECUTION_MODE" for e in result.errors)

    def test_none_mode(self, base_cfg: dict):
        cfg = {**base_cfg, "EXECUTION_MODE": None}
        result = ConfigValidator(cfg).validate()
        assert result.ok  # None defaults to "MANUAL"


# ── ConfigValidator — Data Provider ───────────────────────────────────────


class TestDataProvider:
    def test_valid_provider_config(self):
        cfg = {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE", "NSE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True, "NSE": False},
            "LATENCY_BUDGET_MS": 500,
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.10,
            "AUDIT_RETENTION_DAYS": 30,
            "RETENTION_REPORTS_MAX_FILES": 10,
            "RETENTION_LOGS_MAX_FILES": 10,
            "RETENTION_BACKUPS_MAX_FILES": 10,
            "AUDIT_LOG_ENABLED": False,
        }
        result = ConfigValidator(cfg).validate()
        assert result.ok

    def test_empty_priority_list(self):
        """Empty priority list → error."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": [],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not result.ok
        assert any(e.key == "DATA_PROVIDER_PRIORITY" for e in result.errors)

    def test_no_providers_enabled(self):
        """No enabled provider → error."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE", "NSE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": False, "NSE": False},
        }
        result = ConfigValidator(cfg).validate()
        assert not result.ok
        assert any(e.key == "DATA_PROVIDER_ENABLED" for e in result.errors)

    def test_enabled_not_dict(self):
        """DATA_PROVIDER_ENABLED not a dict → error."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": "not_a_dict",
        }
        result = ConfigValidator(cfg).validate()
        assert not result.ok
        assert any(e.key == "DATA_PROVIDER_ENABLED" for e in result.errors)

    def test_empty_provider_name(self):
        """Empty provider name in priority list → error."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE", ""],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True, "": False},
        }
        result = ConfigValidator(cfg).validate()
        assert not result.ok
        assert any("item" in e.message.lower() for e in result.errors)

    def test_numeric_provider_name(self):
        """Numeric provider name → error."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": [123],
            "DATA_PROVIDER_ENABLED": {"123": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not result.ok


# ── ConfigValidator — Numeric Range Validation ────────────────────────────


class TestNumericRange:
    def test_valid_numeric_values(self):
        cfg = {
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
            "LATENCY_BUDGET_MS": 500,
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.10,
            "AUDIT_RETENTION_DAYS": 90,
            "RETENTION_REPORTS_MAX_FILES": 50,
            "RETENTION_LOGS_MAX_FILES": 50,
            "RETENTION_BACKUPS_MAX_FILES": 50,
            "AUDIT_LOG_ENABLED": False,
        }
        result = ConfigValidator(cfg).validate()
        assert result.ok

    def test_latency_budget_too_low(self):
        result = ConfigValidator({
            "LATENCY_BUDGET_MS": 50,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }).validate()
        assert any(e.key == "LATENCY_BUDGET_MS" for e in result.errors)

    def test_latency_budget_too_high(self):
        result = ConfigValidator({
            "LATENCY_BUDGET_MS": 20000,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }).validate()
        assert any(e.key == "LATENCY_BUDGET_MS" for e in result.errors)

    def test_risk_pct_at_lower_bound_excluded(self):
        """PORTFOLIO_MAX_SL_RISK_PCT must be > 0.05 (inclusive_low=False)."""
        result = ConfigValidator({
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.05,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }).validate()
        assert any(e.key == "PORTFOLIO_MAX_SL_RISK_PCT" for e in result.errors)

    def test_risk_pct_at_upper_bound_included(self):
        """PORTFOLIO_MAX_SL_RISK_PCT ≤ 1.0 is OK (inclusive_high=True)."""
        result = ConfigValidator({
            "PORTFOLIO_MAX_SL_RISK_PCT": 1.0,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }).validate()
        assert not any(e.key == "PORTFOLIO_MAX_SL_RISK_PCT" for e in result.errors)


# ── ConfigValidator — Broker Warnings ─────────────────────────────────────


class TestBrokerWarnings:
    def test_empty_broker_name_warns(self):
        result = ConfigValidator({
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }).validate()
        assert any(w.key == "BROKER_NAME" for w in result.warnings)

    def test_generic_driver_auto_mode_warns(self):
        """GENERIC driver + AUTO mode + API enabled → warning."""
        cfg = {
            "EXECUTION_MODE": "AUTO",
            "BROKER_DRIVER": "GENERIC",
            "BROKER_API_ENABLED": True,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert any(w.key == "BROKER_DRIVER" for w in result.warnings)

    def test_generic_driver_manual_mode_no_warn(self):
        """GENERIC driver + MANUAL mode → no warning."""
        cfg = {
            "EXECUTION_MODE": "MANUAL",
            "BROKER_DRIVER": "GENERIC",
            "BROKER_API_ENABLED": True,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not any(w.key == "BROKER_DRIVER" for w in result.warnings)

    def test_custom_factory_suppresses_warning(self):
        """Custom factory + GENERIC driver + AUTO → no warning."""
        cfg = {
            "EXECUTION_MODE": "AUTO",
            "BROKER_DRIVER": "GENERIC",
            "BROKER_API_ENABLED": True,
            "BROKER_CUSTOM_FACTORY": "my_adapter.create",
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not any(w.key == "BROKER_DRIVER" for w in result.warnings)


# ── ConfigValidator — Audit Log ──────────────────────────────────────────


class TestAuditLog:
    def test_audit_log_enabled_no_file_error(self):
        """Audit log enabled but no file path → error."""
        cfg = {
            "AUDIT_LOG_ENABLED": True,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert any(e.key == "AUDIT_LOG_FILE" for e in result.errors)

    def test_audit_log_enabled_with_file_ok(self):
        """Audit log enabled with file path → OK."""
        cfg = {
            "AUDIT_LOG_ENABLED": True,
            "AUDIT_LOG_FILE": "logs/audit.log",
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not any(e.key == "AUDIT_LOG_FILE" for e in result.errors)

    def test_audit_log_disabled_no_error(self):
        """Audit log disabled → no error even without file."""
        cfg = {
            "AUDIT_LOG_ENABLED": False,
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert not any(e.key == "AUDIT_LOG_FILE" for e in result.errors)


# ── ConfigValidator — Edge Cases ─────────────────────────────────────────


class TestEdgeCases:
    def test_empty_config_returns_errors(self):
        """Empty config produces validation errors."""
        result = ConfigValidator({}).validate()
        assert len(result.errors) > 0

    def test_none_values_handled(self):
        """None values don't crash validator."""
        cfg = {
            "DATA_PROVIDER_PRIORITY": None,
            "DATA_PROVIDER_ENABLED": None,
        }
        result = ConfigValidator(cfg).validate()
        assert len(result.errors) > 0

    def test_wrong_types_handled(self):
        """Wrong types don't crash validator."""
        cfg = {
            "LATENCY_BUDGET_MS": "not_a_number",
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
        }
        result = ConfigValidator(cfg).validate()
        assert any(e.key == "LATENCY_BUDGET_MS" for e in result.errors)

    def test_minimal_valid_config(self):
        """Minimal config that should pass all checks."""
        cfg = {
            "EXECUTION_MODE": "MANUAL",
            "DATA_PROVIDER_PRIORITY": ["YFINANCE"],
            "DATA_PROVIDER_ENABLED": {"YFINANCE": True},
            "LATENCY_BUDGET_MS": 500,
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.10,
            "AUDIT_RETENTION_DAYS": 30,
            "RETENTION_REPORTS_MAX_FILES": 10,
            "RETENTION_LOGS_MAX_FILES": 10,
            "RETENTION_BACKUPS_MAX_FILES": 10,
            "AUDIT_LOG_ENABLED": False,
        }
        result = ConfigValidator(cfg).validate()
        assert result.ok

    def test_multiple_errors_collected(self):
        """Multiple issues produce multiple errors."""
        cfg = {
            "EXECUTION_MODE": "INVALID",
            "DATA_PROVIDER_PRIORITY": [],
            "DATA_PROVIDER_ENABLED": {},
            "LATENCY_BUDGET_MS": "bad",
        }
        result = ConfigValidator(cfg).validate()
        assert len(result.errors) >= 3


# ── Deprecation Warning ────────────────────────────────────────────────────


class TestDeprecation:
    def test_import_emits_deprecation(self):
        """Importing config_engine emits a DeprecationWarning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib

            import core.config_engine
            importlib.reload(core.config_engine)
            deprecations = [x for x in w if issubclass(x.category, DeprecationWarning)]
            assert any("config_engine is DEPRECATED" in str(x.message) for x in deprecations)
