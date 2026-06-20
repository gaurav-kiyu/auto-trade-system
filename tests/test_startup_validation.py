"""
Tests for core/startup_validation.py - Startup Validation.

Covers:
  - Module constants (AUTHORITATIVE_RISK_MODULE, DEPRECATED_RISK_MODULES)
  - validate_risk_engine (deprecated modules loaded, authoritative import success/failure)
  - validate_dependencies (all present, some missing)
  - run_startup_validation (all pass, some fail)
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


from core.startup_validation import (
    AUTHORITATIVE_RISK_CLASS,
    AUTHORITATIVE_RISK_MODULE,
    DEPRECATED_RISK_MODULES,
    run_startup_validation,
    validate_dependencies,
    validate_risk_engine,
)


# ═══════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════


class TestConstants:
    def test_authoritative_risk_module(self):
        assert AUTHORITATIVE_RISK_MODULE == "core.services.risk_service"
        assert AUTHORITATIVE_RISK_CLASS == "RiskService"

    def test_deprecated_modules(self):
        assert "core.risk_engine" in DEPRECATED_RISK_MODULES
        assert "core.predictive_risk" in DEPRECATED_RISK_MODULES
        assert "core.trading_risk" in DEPRECATED_RISK_MODULES
        assert len(DEPRECATED_RISK_MODULES) >= 3


# ═══════════════════════════════════════════════════════════════════════
#  validate_risk_engine
# ═══════════════════════════════════════════════════════════════════════


class TestValidateRiskEngine:
    def test_no_deprecated_modules_returns_success(self):
        """When no deprecated modules are loaded, validation passes."""
        with patch.dict(sys.modules, clear=False):
            # Ensure no deprecated modules are in sys.modules
            for mod in DEPRECATED_RISK_MODULES:
                if mod in sys.modules:
                    del sys.modules[mod]
            with patch.object(sys, 'modules', {
                k: v for k, v in sys.modules.items()
                if k not in DEPRECATED_RISK_MODULES
            }):
                passed, msg = validate_risk_engine()
                assert passed is True
                assert "RiskService" in msg

    def test_deprecated_modules_loaded_still_passes_with_warning(self):
        """Deprecated modules warn but don't block."""
        with patch.dict(sys.modules, {
            "core.risk_engine": MagicMock(),
            "core.services.risk_service": MagicMock(),
        }):
            passed, msg = validate_risk_engine()
            assert passed is True  # Warning only, not blocking

    def test_authoritative_import_failure_returns_false(self):
        """When risk_service module can't be imported, validation fails."""
        original_import = __builtins__["__import__"]
        def failing_import(name, *args, **kwargs):
            if name == AUTHORITATIVE_RISK_MODULE:
                raise ImportError(f"No module named {name}")
            return original_import(name, *args, **kwargs)

        with patch.dict("sys.modules", {}):
            with patch("builtins.__import__", side_effect=failing_import):
                passed, msg = validate_risk_engine()
                assert passed is False
                assert "Cannot import" in msg


# ═══════════════════════════════════════════════════════════════════════
#  validate_dependencies
# ═══════════════════════════════════════════════════════════════════════


class TestValidateDependencies:
    def test_all_dependencies_available(self):
        """When all required modules can be imported, validation passes."""
        passed, msg = validate_dependencies()
        assert passed is True
        assert "All required dependencies available" in msg

    def test_missing_dependency_returns_false(self):
        """When a required module can't be imported, validation fails."""
        original_import = __builtins__["__import__"]
        def failing_import(name, *args, **kwargs):
            if name == "core.system_mode":
                raise ImportError(f"No module named {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=failing_import):
            passed, msg = validate_dependencies()
            assert passed is False
            assert "Missing required modules" in msg


# ═══════════════════════════════════════════════════════════════════════
#  run_startup_validation
# ═══════════════════════════════════════════════════════════════════════


class TestRunStartupValidation:
    def test_all_checks_pass(self):
        """When all validations pass, returns True."""
        with patch("core.startup_validation.validate_risk_engine", return_value=(True, "OK")), \
             patch("core.startup_validation.validate_dependencies", return_value=(True, "OK")):
            result = run_startup_validation()
            assert result is True

    def test_some_checks_fail(self):
        """When any validation fails, returns False (fail_fast=False)."""
        with patch("core.startup_validation.validate_risk_engine", return_value=(False, "FAIL")), \
             patch("core.startup_validation.validate_dependencies", return_value=(True, "OK")):
            result = run_startup_validation(fail_fast=False)
            assert result is False

    def test_calls_validators_in_order(self):
        """Validators should be called in the defined order."""
        call_order = []
        def validator1(*args, **kwargs):
            call_order.append("validate_risk_engine")
            return (True, "OK")
        def validator2(*args, **kwargs):
            call_order.append("validate_dependencies")
            return (True, "OK")

        with patch("core.startup_validation.validate_risk_engine", side_effect=validator1), \
             patch("core.startup_validation.validate_dependencies", side_effect=validator2):
            run_startup_validation()
            assert call_order == ["validate_risk_engine", "validate_dependencies"]
