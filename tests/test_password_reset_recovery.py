"""Unit tests for Self-Service Password Recovery & Emergency Reset."""

import pytest
from core.auth.handler import AuthHandler


@pytest.fixture
def auth_handler(tmp_path):
    db_path = str(tmp_path / "auth_test.db")
    handler = AuthHandler(db_path=db_path)
    res = handler.create_user("trader1", "Trader@Pass1!", role="viewer", display_name="Test Trader")
    assert res["success"] is True, res.get("error")
    return handler


def test_password_reset_token_flow(auth_handler):
    # 1. Request reset token
    token = auth_handler.create_password_reset_token("trader1")
    assert token is not None
    assert len(token) > 10

    # 2. Reset password using token
    reset_res = auth_handler.reset_password_with_token(token, "New@StrongPass2026!")
    assert reset_res["success"] is True

    # 3. Old token should be invalidated upon use
    username = auth_handler.verify_password_reset_token(token)
    assert username is None

    # 4. Authenticate with new password
    auth_user = auth_handler.authenticate("trader1", "New@StrongPass2026!")
    assert auth_user is not None
    assert auth_user.username == "trader1"


def test_emergency_master_reset_flow(auth_handler, monkeypatch):
    # Regression: the recovery key used to be one of three literal strings
    # hardcoded in the handler, one of which was shown in plaintext on the
    # public /forgot-password page. It's now read from
    # OPBUYING_EMERGENCY_MASTER_RECOVERY_KEY, disabled (fail-closed) if unset.
    monkeypatch.setenv("OPBUYING_EMERGENCY_MASTER_RECOVERY_KEY", "test-only-recovery-key")

    res = auth_handler.emergency_master_reset_password(
        "trader1",
        "test-only-recovery-key",
        "Master@Reset999!"
    )
    assert res["success"] is True

    # Authenticate with new password
    auth_user = auth_handler.authenticate("trader1", "Master@Reset999!")
    assert auth_user is not None
    assert auth_user.username == "trader1"


def test_emergency_master_reset_disabled_when_key_unset(auth_handler, monkeypatch):
    monkeypatch.delenv("OPBUYING_EMERGENCY_MASTER_RECOVERY_KEY", raising=False)
    res = auth_handler.emergency_master_reset_password(
        "trader1", "anything", "Master@Reset999!",
    )
    assert res["success"] is False


def test_emergency_master_reset_rejects_old_hardcoded_keys(auth_handler, monkeypatch):
    """The 3 formerly-hardcoded keys must no longer work, even if an operator
    hasn't configured a real one - they were never meant to be permanent."""
    monkeypatch.setenv("OPBUYING_EMERGENCY_MASTER_RECOVERY_KEY", "a-real-secret-not-a-default")
    for old_key in ("GAURAV_CAPITAL_SUPER_ADMIN_KEY", "OPB_MASTER_RECOVERY_2026", "ADMIN_OPB_INSTITUTIONAL"):
        res = auth_handler.emergency_master_reset_password("trader1", old_key, "Master@Reset999!")
        assert res["success"] is False


def test_invalid_reset_token(auth_handler):
    res = auth_handler.verify_password_reset_token("non-existent-token-xyz")
    assert res is None
