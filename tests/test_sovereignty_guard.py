"""Tests for core/sovereignty_guard.py — broker/AI dependency control."""

from __future__ import annotations

from core.sovereignty_guard import SovereigntyGuard


class TestInit:
    def test_default_block_broker(self) -> None:
        g = SovereigntyGuard({})
        assert g.broker_block is True

    def test_default_ai_disabled(self) -> None:
        g = SovereigntyGuard({})
        assert g.ai_enabled is False

    def test_default_execution_mode(self) -> None:
        g = SovereigntyGuard({})
        assert g.execution_mode == "MANUAL"

    def test_custom_config(self) -> None:
        g = SovereigntyGuard({
            "SOVEREIGNTY_BROKER_BLOCK": False,
            "ai_reasoning_enabled": True,
            "EXECUTION_MODE": "AUTO",
        })
        assert g.broker_block is False
        assert g.ai_enabled is True
        assert g.execution_mode == "AUTO"


class TestCanUseBroker:
    def test_blocked_returns_false(self) -> None:
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True})
        assert g.can_use_broker() is False

    def test_not_blocked_manual_mode_returns_false(self) -> None:
        g = SovereigntyGuard({
            "SOVEREIGNTY_BROKER_BLOCK": False,
            "EXECUTION_MODE": "MANUAL",
        })
        assert g.can_use_broker() is False

    def test_not_blocked_auto_mode_returns_true(self) -> None:
        g = SovereigntyGuard({
            "SOVEREIGNTY_BROKER_BLOCK": False,
            "EXECUTION_MODE": "AUTO",
        })
        assert g.can_use_broker() is True

    def test_not_blocked_paper_mode_returns_false(self) -> None:
        g = SovereigntyGuard({
            "SOVEREIGNTY_BROKER_BLOCK": False,
            "EXECUTION_MODE": "PAPER",
        })
        assert g.can_use_broker() is False


class TestCanUseAi:
    def test_disabled_returns_false(self) -> None:
        g = SovereigntyGuard({"ai_reasoning_enabled": False})
        assert g.can_use_ai() is False

    def test_enabled_returns_true(self) -> None:
        g = SovereigntyGuard({"ai_reasoning_enabled": True})
        assert g.can_use_ai() is True

    def test_default_disabled(self) -> None:
        g = SovereigntyGuard({})
        assert g.can_use_ai() is False


class TestAuditSovereignty:
    def test_returns_status_string(self) -> None:
        g = SovereigntyGuard({})
        status = g.audit_sovereignty()
        assert "Sovereignty Guard" in status
        assert "BLOCKED" in status or "ALLOWED" in status
        assert "DISABLED" in status or "ENABLED" in status

    def test_blocked_state_in_status(self) -> None:
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True})
        status = g.audit_sovereignty()
        assert "BLOCKED" in status

    def test_allowed_state_in_status(self) -> None:
        g = SovereigntyGuard({
            "SOVEREIGNTY_BROKER_BLOCK": False,
            "EXECUTION_MODE": "AUTO",
            "ai_reasoning_enabled": True,
        })
        status = g.audit_sovereignty()
        assert "ALLOWED" in status
        assert "ENABLED" in status
