"""OPB v2.61 — G1 Authentication Security Hardening Tests.

Verifies:
1. Valid forgot-password request returns 200 generic message.
2. Token generation occurs internally.
3. No token in JSON response.
4. No token in response body.
5. No token in response headers.
6. No token in redirects/HTML.
7. No token in normal production logs.
8. Secure delivery works (email delivery attempted when configured).
9. Safe test/dev fallback works when environment is non-production.
10. Production environment cannot activate fallback.
11. Valid token accepted via verify-reset-token.
12. Invalid token rejected.
13. Expired token rejected.
14. Used token rejected (single-use invariant).
15. Password reset succeeds with valid token.
16. Token invalidated upon password reset.
17. Password hashing preserved (new password authenticates, old password fails).
18. Enumeration protection preserved (nonexistent user returns identical 200 payload).
"""

from __future__ import annotations

import logging
import time
from typing import Any
from unittest.mock import patch

import pytest
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import _test_reset_tokens, create_auth_router, get_test_reset_token
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def auth_setup(tmp_path: Any) -> tuple[TestClient, AuthHandler]:
    db_path = str(tmp_path / "auth_security_test.db")
    handler = AuthHandler(db_path=db_path)
    # Create test users: one with email, one without email
    handler.create_user(
        "alice_trader",
        "Alice@Secure2026!",
        role="viewer",
        display_name="Alice Trader",
        metadata={"email": "alice@example.com"},
    )
    handler.create_user(
        "bob_trader",
        "Bob@Secure2026!",
        role="operator",
        display_name="Bob Trader",
    )

    app = FastAPI()
    deps = AuthDependencies(handler)
    router = create_auth_router(handler, deps)
    app.include_router(router)
    client = TestClient(app)
    return client, handler


def test_01_valid_forgot_password_request(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert "password reset instructions have been dispatched" in data["message"].lower()


def test_02_token_generation_internally(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    # Token must have been generated and recorded in test sink
    token = get_test_reset_token("alice_trader")
    assert token is not None
    assert len(token) >= 20


def test_03_no_token_in_json_response(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    data = res.json()
    assert "token" not in data
    assert "reset_url" not in data
    assert "token_hash" not in data


def test_04_no_token_in_response_body(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None
    assert token not in res.text


def test_05_no_token_in_headers(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None
    for header_name, header_val in res.headers.items():
        assert token not in header_name
        assert token not in header_val


def test_06_no_token_in_redirects_or_html(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"}, follow_redirects=False)
    assert res.status_code == 200  # No 301/302 redirects containing token query parameter
    assert "location" not in res.headers


def test_07_no_token_in_normal_logs(auth_setup: tuple[TestClient, AuthHandler], caplog: pytest.LogCaptureFixture) -> None:
    client, _ = auth_setup
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None
    for record in caplog.records:
        assert token not in record.getMessage()


def test_08_secure_delivery_works(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    sent_emails: list[dict[str, Any]] = []

    def mock_send(to: list[str], subject: str, html: str, plain: str) -> bool:
        sent_emails.append({"to": to, "subject": subject, "html": html, "plain": plain})
        return True

    with patch("core.auth.registration_notifications._send", side_effect=mock_send):
        res = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
        assert res.status_code == 200

    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == ["alice@example.com"]
    assert "Password Reset" in sent_emails[0]["subject"]
    token = get_test_reset_token("alice_trader")
    assert token is not None
    assert token in sent_emails[0]["html"]


def test_09_safe_fallback_works_in_test_env(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    _test_reset_tokens.clear()
    client.post("/api/auth/forgot-password", json={"username": "bob_trader"})
    token = get_test_reset_token("bob_trader")
    assert token is not None


def test_10_production_cannot_activate_fallback(
    auth_setup: tuple[TestClient, AuthHandler], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = auth_setup
    _test_reset_tokens.clear()
    monkeypatch.setenv("OPBUYING_ENVIRONMENT", "PRODUCTION")

    # In production, neither is the sink populated nor does get_test_reset_token return it
    client.post("/api/auth/forgot-password", json={"username": "bob_trader"})
    token = get_test_reset_token("bob_trader")
    assert token is None


def test_11_valid_token_accepted(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    res = client.post("/api/auth/verify-reset-token", json={"token": token})
    assert res.status_code == 200
    assert res.json()["valid"] is True
    assert res.json()["username"] == "alice_trader"


def test_12_invalid_token_rejected(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    res = client.post("/api/auth/verify-reset-token", json={"token": "completely-bogus-token-12345"})
    assert res.status_code == 400
    assert "Invalid or expired token" in res.json()["detail"]


def test_13_expired_token_rejected(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, handler = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    # Simulate token expiration in DB by backdating expires_ts
    conn = handler._get_conn()
    conn.execute("UPDATE password_reset_tokens SET expires_ts = ?", (time.time() - 100,))
    conn.commit()
    conn.close()

    res = client.post("/api/auth/verify-reset-token", json={"token": token})
    assert res.status_code == 400


def test_14_used_token_rejected(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    # First reset with token
    res1 = client.post("/api/auth/reset-password", json={"token": token, "new_password": "New@StrongPass2026!"})
    assert res1.status_code == 200
    assert res1.json()["success"] is True

    # Re-use attempt with the same token must fail
    res2 = client.post("/api/auth/reset-password", json={"token": token, "new_password": "Another@StrongPass2026!"})
    assert res2.status_code == 400


def test_15_password_reset_succeeds(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, handler = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    res = client.post("/api/auth/reset-password", json={"token": token, "new_password": "New@StrongPass2026!"})
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Authenticate with new password succeeds
    user = handler.authenticate("alice_trader", "New@StrongPass2026!")
    assert user is not None
    assert user.username == "alice_trader"


def test_16_token_invalidated_after_reset(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    client.post("/api/auth/reset-password", json={"token": token, "new_password": "New@StrongPass2026!"})

    # Verify endpoint must reject token after reset
    res = client.post("/api/auth/verify-reset-token", json={"token": token})
    assert res.status_code == 400


def test_17_password_hashing_preserved(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, handler = auth_setup
    client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    token = get_test_reset_token("alice_trader")
    assert token is not None

    client.post("/api/auth/reset-password", json={"token": token, "new_password": "New@StrongPass2026!"})

    # Old password no longer authenticates
    old_user = handler.authenticate("alice_trader", "Alice@Secure2026!")
    assert old_user is None

    # New password authenticates
    new_user = handler.authenticate("alice_trader", "New@StrongPass2026!")
    assert new_user is not None


def test_18_enumeration_protection_preserved(auth_setup: tuple[TestClient, AuthHandler]) -> None:
    client, _ = auth_setup
    # Request for existing user
    res_existing = client.post("/api/auth/forgot-password", json={"username": "alice_trader"})
    # Request for non-existing user
    res_nonexistent = client.post("/api/auth/forgot-password", json={"username": "non_existent_user_999"})

    assert res_existing.status_code == 200
    assert res_nonexistent.status_code == 200
    assert res_existing.json() == res_nonexistent.json()
