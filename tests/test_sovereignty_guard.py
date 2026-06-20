"""Tests for core.sovereignty_guard — broker/AI access control."""

from __future__ import annotations

import pytest

from core.sovereignty_guard import SovereigntyGuard


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def blocked_cfg() -> dict:
    return {
        "SOVEREIGNTY_BROKER_BLOCK": True,
        "ai_reasoning_enabled": False,
        "EXECUTION_MODE": "MANUAL",
    }


@pytest.fixture
def auto_cfg() -> dict:
    return {
        "SOVEREIGNTY_BROKER_BLOCK": False,
        "ai_reasoning_enabled": False,
        "EXECUTION_MODE": "AUTO",
    }


@pytest.fixture
def ai_enabled_cfg() -> dict:
    return {
        "SOVEREIGNTY_BROKER_BLOCK": True,
        "ai_reasoning_enabled": True,
        "EXECUTION_MODE": "MANUAL",
    }


@pytest.fixture
def full_access_cfg() -> dict:
    return {
        "SOVEREIGNTY_BROKER_BLOCK": False,
        "ai_reasoning_enabled": True,
        "EXECUTION_MODE": "AUTO",
    }


# ── Construction tests ───────────────────────────────────────────────────────

class TestSovereigntyGuardConstruction:
    """Test guard initialization from config."""

    def test_blocked_by_default(self):
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True, "ai_reasoning_enabled": False, "EXECUTION_MODE": "MANUAL"})
        assert g.broker_block is True
        assert g.ai_enabled is False
        assert g.execution_mode == "MANUAL"

    def test_empty_config_defaults(self):
        """Empty config should use safe defaults (blocked)."""
        g = SovereigntyGuard({})
        assert g.broker_block is True  # defaults to blocked
        assert g.ai_enabled is False
        assert g.execution_mode == "MANUAL"

    def test_execution_mode_normalized(self):
        """EXECUTION_MODE should be uppercased."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": True, "EXECUTION_MODE": "auto"})
        assert g.execution_mode == "AUTO"


# ── Broker access tests ──────────────────────────────────────────────────────

class TestCanUseBroker:
    """Test broker access control."""

    def test_blocked_by_default(self, blocked_cfg: dict):
        """When broker_block=True, can_use_broker() should return False."""
        g = SovereigntyGuard(blocked_cfg)
        assert g.can_use_broker() is False

    def test_auto_mode_allows(self, auto_cfg: dict):
        """When broker_block=False and AUTO mode, can_use_broker() should return True."""
        g = SovereigntyGuard(auto_cfg)
        assert g.can_use_broker() is True

    def test_manual_mode_blocks_even_without_block(self):
        """MANUAL mode should block even if SOVEREIGNTY_BROKER_BLOCK is False."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": False, "EXECUTION_MODE": "MANUAL"})
        assert g.can_use_broker() is False

    def test_paper_mode_blocks(self):
        """PAPER mode should not allow broker access."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": False, "EXECUTION_MODE": "PAPER"})
        assert g.can_use_broker() is False

    def test_auto_mode_with_block(self):
        """Even in AUTO mode, broker_block=True should prevent access."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True, "ai_reasoning_enabled": False, "EXECUTION_MODE": "AUTO"})
        assert g.can_use_broker() is False


# ── AI access tests ──────────────────────────────────────────────────────────

class TestCanUseAi:
    """Test AI access control."""

    def test_ai_disabled_by_default(self):
        """When ai_reasoning_enabled=False, can_use_ai() should return False."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True, "ai_reasoning_enabled": False, "EXECUTION_MODE": "MANUAL"})
        assert g.can_use_ai() is False

    def test_ai_enabled(self, ai_enabled_cfg: dict):
        """When ai_reasoning_enabled=True, can_use_ai() should return True."""
        g = SovereigntyGuard(ai_enabled_cfg)
        assert g.can_use_ai() is True

    def test_ai_independent_of_broker(self):
        """AI access should be independent of broker access."""
        g1 = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True, "ai_reasoning_enabled": True, "EXECUTION_MODE": "MANUAL"})
        g2 = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": True, "EXECUTION_MODE": "MANUAL"})
        assert g1.can_use_ai() is True
        assert g2.can_use_ai() is True

    def test_ai_independent_of_execution_mode(self):
        """AI access should work regardless of EXECUTION_MODE."""
        for mode in ("MANUAL", "AUTO", "PAPER"):
            g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": True, "ai_reasoning_enabled": True, "EXECUTION_MODE": mode})
            assert g.can_use_ai() is True, f"AI should be enabled in {mode} mode"


# ── Audit tests ──────────────────────────────────────────────────────────────

class TestAuditSovereignty:
    """Test the audit_sovereignty method."""

    def test_audit_blocked(self, blocked_cfg: dict):
        """Audit should show BLOCKED/DISABLED for blocked config."""
        g = SovereigntyGuard(blocked_cfg)
        status = g.audit_sovereignty()
        assert "BLOCKED" in status
        assert "DISABLED" in status

    def test_audit_full_access(self, full_access_cfg: dict):
        """Audit should show ALLOWED/ENABLED for full access config."""
        g = SovereigntyGuard(full_access_cfg)
        status = g.audit_sovereignty()
        assert "ALLOWED" in status
        assert "ENABLED" in status

    def test_audit_mixed(self):
        """Audit should reflect mixed state correctly."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": False, "EXECUTION_MODE": "AUTO"})
        status = g.audit_sovereignty()
        assert "ALLOWED" in status  # Broker allowed (AUTO + no block)
        assert "DISABLED" in status  # AI disabled

    def test_audit_manual_blocks_broker(self):
        """Even without broker block, MANUAL mode should show broker blocked."""
        g = SovereigntyGuard({"SOVEREIGNTY_BROKER_BLOCK": False, "ai_reasoning_enabled": False, "EXECUTION_MODE": "MANUAL"})
        status = g.audit_sovereignty()
        # can_use_broker() returns False because EXECUTION_MODE is MANUAL
        assert "BLOCKED" in status
