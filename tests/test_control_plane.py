"""Tests for index_app.domains.admin.control_plane wiring module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from index_app.domains.admin.control_plane import init_admin_control_plane


class TestInitAdminControlPlane:
    """Tests for init_admin_control_plane function."""

    def test_disabled_returns_none(self) -> None:
        """When disabled, returns None and does not wire anything."""
        result = init_admin_control_plane(cfg={"admin_control_plane_enabled": False})
        assert result is None

    def test_disabled_default_config(self) -> None:
        """When not configured, defaults to disabled and returns None."""
        result = init_admin_control_plane(cfg={})
        assert result is None

    def test_enabled_with_all_deps(self) -> None:
        """When enabled, wires all dependencies and starts the thread."""
        mock_thread = MagicMock()
        mock_thread.name = "admin-cp-1"

        with (
            patch("core.operating_mode.OperatingModeManager") as mock_mode_mgr,
            patch("core.wal.journal.WriteAheadJournal") as mock_wal,
            patch("core.execution.idempotency.certifier.IdempotencyCertifier") as mock_cert,
            patch("core.auth.role_manager.RoleManager") as mock_role_mgr,
            patch("core.control_plane.maybe_start_control_plane", return_value=mock_thread) as mock_start,
        ):
            cfg = {
                "admin_control_plane_enabled": True,
                "admin_default_role": "admin",
                "admin_strategies": {"strat_a": True},
                "admin_assets": {"EQUITY": True},
                "admin_feature_flags": {"live_trading": True},
            }
            result = init_admin_control_plane(
                cfg=cfg,
                reload_config_handler_fn=lambda: {"status": "ok"},
                notify_fn=lambda msg: None,
            )

            assert result is mock_thread
            mock_start.assert_called_once()
            call_kwargs = mock_start.call_args[1]
            assert call_kwargs["role_manager"] is mock_role_mgr.return_value
            assert call_kwargs["mode_manager"] is mock_mode_mgr.return_value
            assert call_kwargs["wal"] is mock_wal.return_value
            assert call_kwargs["certifier"] is mock_cert.return_value
            assert call_kwargs["config_reload"] is not None

    def test_enabled_audit_logger_unavailable(self) -> None:
        """Gracefully handles missing audit_logger."""
        mock_thread = MagicMock()

        with (
            patch("core.control_plane.maybe_start_control_plane", return_value=mock_thread),
            patch("core.operating_mode.OperatingModeManager"),
            patch("core.wal.journal.WriteAheadJournal"),
            patch("core.execution.idempotency.certifier.IdempotencyCertifier"),
            patch("core.auth.role_manager.RoleManager"),
            patch("infrastructure.security.audit_logger.get_audit_logger", side_effect=ImportError("no module")),
        ):
            result = init_admin_control_plane(cfg={"admin_control_plane_enabled": True})
            assert result is mock_thread

    def test_enabled_model_registry_unavailable(self) -> None:
        """Gracefully handles missing model_registry."""
        mock_thread = MagicMock()

        with (
            patch("core.control_plane.maybe_start_control_plane", return_value=mock_thread),
            patch("core.operating_mode.OperatingModeManager"),
            patch("core.wal.journal.WriteAheadJournal"),
            patch("core.execution.idempotency.certifier.IdempotencyCertifier"),
            patch("core.auth.role_manager.RoleManager"),
            patch("infrastructure.security.audit_logger.get_audit_logger"),
            patch("core.ai.model_registry.ModelRegistry", side_effect=ImportError("no module")),
        ):
            result = init_admin_control_plane(cfg={"admin_control_plane_enabled": True})
            assert result is mock_thread

    def test_enabled_strips_unknown_config(self) -> None:
        """Unknown config keys are safely ignored."""
        mock_thread = MagicMock()

        with (
            patch("core.control_plane.maybe_start_control_plane", return_value=mock_thread),
            patch("core.operating_mode.OperatingModeManager"),
            patch("core.wal.journal.WriteAheadJournal"),
            patch("core.execution.idempotency.certifier.IdempotencyCertifier"),
            patch("core.auth.role_manager.RoleManager"),
            patch("infrastructure.security.audit_logger.get_audit_logger"),
        ):
            # Config with unknown keys should not crash
            result = init_admin_control_plane(cfg={
                "admin_control_plane_enabled": True,
                "unknown_key_xyz": "should_not_crash",
            })
            assert result is mock_thread

    def test_no_callbacks_no_crash(self) -> None:
        """When callbacks are None, still works."""
        mock_thread = MagicMock()

        with (
            patch("core.control_plane.maybe_start_control_plane", return_value=mock_thread),
            patch("core.operating_mode.OperatingModeManager"),
            patch("core.wal.journal.WriteAheadJournal"),
            patch("core.execution.idempotency.certifier.IdempotencyCertifier"),
            patch("core.auth.role_manager.RoleManager"),
            patch("infrastructure.security.audit_logger.get_audit_logger"),
        ):
            result = init_admin_control_plane(cfg={"admin_control_plane_enabled": True})
            assert result is mock_thread
