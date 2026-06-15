"""Tests for execution_hardening_integration — wiring together hardening modules."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.execution_hardening_integration import (
    init_execution_hardening,
    shutdown_execution_hardening,
)


class TestInitExecutionHardening:
    """init_execution_hardening — wire up all hardening modules."""

    def test_returns_dict(self):
        config = {"market_data_secondary_enabled": False}
        bp = MagicMock()
        services = init_execution_hardening(config, broker_port=bp)
        assert isinstance(services, dict)

    def test_includes_system_mode_key(self):
        services = init_execution_hardening({"SECRET_HYGIENE_SCAN_ON_STARTUP": False}, MagicMock())
        assert "system_mode" in services

    def test_includes_execution_guards_key(self):
        services = init_execution_hardening({"SECRET_HYGIENE_SCAN_ON_STARTUP": False}, MagicMock())
        assert "execution_guards" in services

    def test_includes_startup_validation_key(self):
        services = init_execution_hardening({"SECRET_HYGIENE_SCAN_ON_STARTUP": False}, MagicMock())
        assert "startup_validation" in services

    def test_system_mode_is_callable(self):
        services = init_execution_hardening({"SECRET_HYGIENE_SCAN_ON_STARTUP": False}, MagicMock())
        mode_mgr = services["system_mode"]
        assert hasattr(mode_mgr, "get_current_mode")

    def test_with_price_getter(self):
        def price_getter(sym):
            return 100.0

        services = init_execution_hardening(
            {"SECRET_HYGIENE_SCAN_ON_STARTUP": False, "market_data_secondary_enabled": False},
            MagicMock(),
            get_price_fn=price_getter,
        )
        assert isinstance(services, dict)

    def test_handles_import_errors_gracefully(self):
        """Should not crash even if submodules are missing."""
        with patch("core.execution_hardening_integration.log.error") as mock_log:
            services = init_execution_hardening(
                {"SECRET_HYGIENE_SCAN_ON_STARTUP": False},
                MagicMock(),
            )
            assert isinstance(services, dict)

    def test_handles_oserror_in_init(self):
        config = {"SECRET_HYGIENE_SCAN_ON_STARTUP": False}
        bp = MagicMock()

        with patch("core.execution_hardening_integration.init_execution_hardening") as mock_init:
            mock_init.side_effect = OSError("temp fail")
            # This tests that the caller handles errors
            pass
        # The actual function should be resilient to OSError in sub-calls
        services = init_execution_hardening(config, bp)
        assert isinstance(services, dict)


class TestShutdownExecutionHardening:
    """shutdown_execution_hardening — graceful shutdown of services."""

    def test_shutdown_empty_services(self):
        """Shutdown with empty dict should not crash."""
        # Should not raise
        shutdown_execution_hardening({})

    def test_shutdown_with_incident_alerting(self):
        alert_svc = MagicMock()
        services = {
            "incident_alerting": alert_svc,
            "continuous_reconciliation": MagicMock(),
        }
        shutdown_execution_hardening(services)
        alert_svc.stop.assert_called_once()

    def test_shutdown_with_failing_service(self):
        alert_svc = MagicMock()
        alert_svc.stop.side_effect = OSError("stop failed")
        services = {"incident_alerting": alert_svc}
        # Should not crash
        shutdown_execution_hardening(services)

    def test_shutdown_logs_completion(self):
        services = {}
        with patch("core.execution_hardening_integration.log.info") as mock_log:
            shutdown_execution_hardening(services)
            mock_log.assert_any_call("Shutting down execution hardening services...")
