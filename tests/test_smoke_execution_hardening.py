"""
Quick Smoke Test - Verify Execution Hardening Core Functions

Run: python -m pytest tests/test_smoke_execution_hardening.py -v
"""
import pytest
import threading
import time
from datetime import datetime, timedelta


class TestSystemModeSmoke:
    """Smoke test for system mode manager."""
    
    def test_mode_transitions(self):
        from core.system_mode import SystemModeManager, SystemMode
        
        sm = SystemModeManager()
        sm._broker_failure_threshold = 1  # Override for test
        assert sm.get_current_mode() == SystemMode.NORMAL
        
        # Test transitions
        sm.set_broker_down("test")
        assert sm.get_current_mode() == SystemMode.BROKER_DOWN
        
        sm.set_normal()
        assert sm.get_current_mode() == SystemMode.NORMAL
        
        # Test can_trade
        allowed, reason = sm.can_enter_new_trade()
        assert allowed is True
        
    def test_safe_mode_blocks_trading(self):
        from core.system_mode import SystemModeManager, SystemMode
        
        sm = SystemModeManager()
        sm.set_safe_mode("test halt")
        
        allowed, reason = sm.can_enter_new_trade()
        assert allowed is False
        assert "SAFE_MODE" in reason


class TestExecutionGuardsSmoke:
    """Smoke test for execution guards."""
    
    def test_price_sanitizer(self):
        from core.execution_guards import ExecutionGuards
        
        guards = ExecutionGuards()
        
        # Valid price passes
        result = guards.check_all_guards("NIFTY", "CALL", 100.0, 101.0, None, 1)
        assert result[0] is True
        
    def test_slippage_guard(self):
        from core.execution_guards import ExecutionGuards
        
        # Low slippage should pass
        guards = ExecutionGuards({"SLIPPAGE_GUARD_THRESHOLD_PCT": 5.0})
        result = guards.check_all_guards("NIFTY", "CALL", 100.0, 103.0, None, 1)
        assert result[0] is True
        
    def test_trade_frequency(self):
        from core.execution_guards import ExecutionGuards
        
        guards = ExecutionGuards({"MAX_TRADES_PER_DAY": 3})
        
        # First few trades should pass
        for i in range(3):
            result = guards.check_all_guards("NIFTY", "CALL", 100.0, 100.0, None, 1)
            if i < 3:
                assert result[0] is True
        
    def test_consecutive_loss_breaker(self):
        from core.execution_guards import ExecutionGuards
        
        guards = ExecutionGuards({"MAX_CONSECUTIVE_LOSSES": 2})
        
        # Record losses
        guards.record_loss()
        guards.record_loss()
        
        # Should now block
        result = guards.check_all_guards("NIFTY", "CALL", 100.0, 100.0, None, 1)
        assert result[0] is False
        assert "consecutive" in result[1].lower()


class TestAuditJournalSmoke:
    """Smoke test for audit journal."""
    
    def test_log_event(self):
        from core.audit_journal import AuditJournal, AuditEventType, AuditSeverity
        
        journal = AuditJournal(log_dir="/tmp", filename_prefix="test_audit")
        
        event_id = journal.log_event(
            AuditEventType.ORDER_SUBMITTED,
            AuditSeverity.INFO,
            "Test order"
        )
        assert event_id is not None


class TestIncidentAlertingSmoke:
    """Smoke test for incident alerting."""
    
    def test_queue_incident(self):
        from core.incident_alerting import IncidentAlerting, IncidentType, IncidentSeverity
        
        ia = IncidentAlerting()
        ia.report_incident(
            IncidentType.BROKER_DISCONNECT,
            IncidentSeverity.CRITICAL,
            "Test disconnect"
        )
        
        assert ia.get_queue_size() == 1


class TestMarketDataFallbackSmoke:
    """Smoke test for market data fallback."""
    
    def test_price_retrieval(self):
        from core.market_data_fallback import DualSourceMarketData
        
        primary = lambda s: 100.0
        md = DualSourceMarketData(primary, None, {})
        
        price, source = md.get_price("NIFTY")
        assert price == 100.0
        assert source == "primary"


class TestExposureLimitsSmoke:
    """Smoke test for exposure limits."""
    
    def test_limit_check(self):
        from core.exposure_limits import ExposureConcentrationLimiter
        
        el = ExposureConcentrationLimiter({"max_exposure_per_symbol_pct": 30})
        
        # Add position
        el.update_position("NIFTY", "20260530", "CALL", "long", 20000)
        
        # Check would exceed
        result = el.check_limits("NIFTY", "20260530", "CALL", "long", 15000, 100000)
        assert result.allowed is False


class TestSecretHygieneSmoke:
    """Smoke test for secret hygiene."""
    
    def test_detect_secrets(self):
        from core.secret_hygiene import SecretHygieneChecker
        
        checker = SecretHygieneChecker()
        
        config = {"KITE_API_KEY": "real_key_12345", "MAX_DAILY_LOSS": -5000}
        result = checker.check_config(config)
        
        assert result.passed is False
        assert len(result.secrets_found) > 0
        
    def test_sanitize(self):
        from core.secret_hygiene import SecretHygieneChecker
        
        checker = SecretHygieneChecker()
        
        data = {"KITE_API_KEY": "secret123", "score": 75}
        sanitized = checker.sanitize_for_logging(data)
        
        assert sanitized["KITE_API_KEY"] == "[REDACTED]"
        assert sanitized["score"] == 75


class TestStartupValidationSmoke:
    """Smoke test for startup validation."""
    
    def test_validation_passes(self):
        from core.startup_validation import run_startup_validation
        
        result = run_startup_validation()
        assert result is True


class TestContinuousReconciliationSmoke:
    """Smoke test for continuous reconciliation (no actual broker needed)."""
    
    def test_import(self):
        from core.execution.continuous_reconciliation import ContinuousReconciliation
        assert ContinuousReconciliation is not None


class TestIntegrationSmoke:
    """Smoke test for integration module."""
    
    def test_integration_import(self):
        from core.execution_hardening_integration import init_execution_hardening
        assert init_execution_hardening is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])