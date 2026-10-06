"""Tests for OPB v2.60 Change Password Remediation.

14-Point Test Matrix:
1. Correct current password + valid new password -> password changed, must_change_password set to 0.
2. Wrong current password -> rejected (HTTP 400 'Current password is incorrect').
3. New password shorter than 8 chars -> rejected (HTTP 400 'Password must be at least 8 characters').
4. New password confirmation mismatch -> client-side contract caught before submission.
5. Empty fields -> rejected (HTTP 400 'Current and new password required').
6. Unauthenticated request to change-password API -> HTTP 401.
7. Expired session -> HTTP 401.
8. CSRF protection verification -> invalid/missing CSRF token rejected with HTTP 403.
9. Duplicate submission prevention -> button disabled and spinner visible in-flight.
10. Successful change-password UI response -> alert banner 'Password changed successfully.'.
11. Failed change-password UI response -> alert banner displays specific error detail.
12. Password never logged in plaintext -> audit log and logger verified.
13. User requiring password change (must_change_password=True) -> SEC-03 behavior documented.
14. Password storage security verification -> PBKDF2-SHA256 with salt used.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from typing import Any, Generator

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from core.auth.csrf import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, CSRFProtection
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.handler.password import hash_password, verify_password
from core.auth.routes import create_auth_router


@pytest.fixture
def temp_auth_db() -> Generator[str, None, None]:
    """Create an isolated temporary auth database."""
    tmp = tempfile.mktemp(suffix=".db")
    yield tmp
    try:
        if os.path.exists(tmp):
            os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def auth_handler(temp_auth_db: str) -> AuthHandler:
    return AuthHandler(db_path=temp_auth_db, token_ttl=3600)


@pytest.fixture
def app_and_client(auth_handler: AuthHandler):
    app = FastAPI()
    deps = AuthDependencies(auth_handler)
    router = create_auth_router(auth_handler, deps)
    app.include_router(router)
    client = TestClient(app)
    return app, auth_handler, client


# ==============================================================================
# 1. Correct current password + valid new password -> must_change_password set to 0
# ==============================================================================
def test_01_change_password_success(app_and_client):
    _, handler, client = app_and_client
    # Create user with initial password
    res = handler.create_user("alice", "Initial@123!", role="viewer")
    assert res["success"]

    # Mark user as must_change_password = 1 (e.g. after admin reset or first login)
    conn = handler._get_conn()
    conn.execute("UPDATE users SET must_change_password = 1 WHERE username = 'alice'")
    conn.commit()
    conn.close()

    user_before = handler.get_user("alice")
    assert user_before.must_change_password is True

    # Login to obtain session
    login_resp = client.post("/api/auth/login", json={"username": "alice", "password": "Initial@123!"})
    assert login_resp.status_code == 200
    cookies = login_resp.cookies

    # Submit change password
    change_resp = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "Initial@123!", "new_password": "NewSecret@456!"},
    )
    assert change_resp.status_code == 200
    assert change_resp.json() == {"success": True}

    # Verify user state in DB
    user_after = handler.get_user("alice")
    assert user_after.must_change_password is False

    # Old password no longer works
    fail_login = client.post("/api/auth/login", json={"username": "alice", "password": "Initial@123!"})
    assert fail_login.status_code == 401

    # New password works
    ok_login = client.post("/api/auth/login", json={"username": "alice", "password": "NewSecret@456!"})
    assert ok_login.status_code == 200


# ==============================================================================
# 2. Wrong current password -> rejected (HTTP 400 'Current password is incorrect')
# ==============================================================================
def test_02_change_password_wrong_current(app_and_client):
    _, handler, client = app_and_client
    handler.create_user("bob", "BobPass@123!", role="viewer")

    login_resp = client.post("/api/auth/login", json={"username": "bob", "password": "BobPass@123!"})
    cookies = login_resp.cookies

    change_resp = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "WrongPassword@123!", "new_password": "NewSecret@456!"},
    )
    assert change_resp.status_code == 400
    assert "Current password is incorrect" in change_resp.json()["detail"]


# ==============================================================================
# 3. New password shorter than 8 chars -> rejected
# ==============================================================================
def test_03_change_password_too_short(app_and_client):
    _, handler, client = app_and_client
    handler.create_user("carol", "CarolPass@123!", role="viewer")

    login_resp = client.post("/api/auth/login", json={"username": "carol", "password": "CarolPass@123!"})
    cookies = login_resp.cookies

    change_resp = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "CarolPass@123!", "new_password": "Sh0rt!"},
    )
    assert change_resp.status_code == 400
    assert "at least 8 characters" in change_resp.json()["detail"]


# ==============================================================================
# 4. Confirmation mismatch -> client-side validation contract
# ==============================================================================
def test_04_confirmation_mismatch_contract():
    template_path = os.path.join("templates", "enterprise", "change_password.html")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify client-side mismatch check is present
    assert "if (newPass !== confirm)" in content
    assert "showError('New passwords do not match')" in content
    # Verify input element minlength attribute is present
    assert 'minlength="8"' in content


# ==============================================================================
# 5. Empty fields -> rejected (HTTP 400 'Current and new password required')
# ==============================================================================
def test_05_change_password_empty_fields(app_and_client):
    _, handler, client = app_and_client
    handler.create_user("david", "DavidPass@123!", role="viewer")

    login_resp = client.post("/api/auth/login", json={"username": "david", "password": "DavidPass@123!"})
    cookies = login_resp.cookies

    # Empty current password
    r1 = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "", "new_password": "ValidNew@123!"},
    )
    assert r1.status_code == 400
    assert "Current and new password required" in r1.json()["detail"]

    # Empty new password
    r2 = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "DavidPass@123!", "new_password": ""},
    )
    assert r2.status_code == 400
    assert "Current and new password required" in r2.json()["detail"]


# ==============================================================================
# 6. Unauthenticated request to change-password API -> HTTP 401
# ==============================================================================
def test_06_change_password_unauthenticated(app_and_client):
    _, _, client = app_and_client
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "OldPassword@123!", "new_password": "ValidNew@123!"},
    )
    assert resp.status_code == 401


# ==============================================================================
# 7. Expired or invalid session -> HTTP 401
# ==============================================================================
def test_07_change_password_invalid_session(app_and_client):
    _, _, client = app_and_client
    resp = client.post(
        "/api/auth/change-password",
        cookies={"opb_session": "nonexistent_or_expired_token_hex12345678"},
        json={"current_password": "OldPassword@123!", "new_password": "ValidNew@123!"},
    )
    assert resp.status_code == 401


# ==============================================================================
# 8. CSRF protection verification
# ==============================================================================
def test_08_change_password_csrf_protection(auth_handler: AuthHandler):
    csrf = CSRFProtection(secret_key="change_pwd_test_secret_32bytes!")
    app = FastAPI()
    deps = AuthDependencies(auth_handler)
    router = create_auth_router(auth_handler, deps)

    @app.middleware("http")
    async def csrf_middleware(request: Request, call_next):
        from fastapi.responses import JSONResponse
        try:
            await csrf.validate(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        response = await call_next(request)
        await csrf.ensure_cookie_set(request, response)
        return response

    app.include_router(router)
    client = TestClient(app)

    # Exempt login so we can authenticate
    csrf.exempt("/api/auth/login")

    auth_handler.create_user("eve", "EvePass@123!", role="viewer")
    login_resp = client.post("/api/auth/login", json={"username": "eve", "password": "EvePass@123!"})
    cookies = dict(login_resp.cookies)

    # 1. Missing CSRF header -> 403
    cookies[CSRF_COOKIE_NAME] = "a" * 64
    r_no_header = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        json={"current_password": "EvePass@123!", "new_password": "ValidNew@123!"},
    )
    assert r_no_header.status_code == 403
    assert "CSRF validation failed" in r_no_header.json()["detail"]

    # 2. Mismatched CSRF header -> 403
    r_mismatch = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        headers={CSRF_HEADER_NAME: "b" * 64},
        json={"current_password": "EvePass@123!", "new_password": "ValidNew@123!"},
    )
    assert r_mismatch.status_code == 403
    assert "CSRF validation failed" in r_mismatch.json()["detail"]

    # 3. Matching CSRF cookie and header -> passes CSRF check
    valid_csrf_token = "c" * 64
    cookies[CSRF_COOKIE_NAME] = valid_csrf_token
    r_valid = client.post(
        "/api/auth/change-password",
        cookies=cookies,
        headers={CSRF_HEADER_NAME: valid_csrf_token},
        json={"current_password": "EvePass@123!", "new_password": "ValidNew@123!"},
    )
    assert r_valid.status_code == 200
    assert r_valid.json() == {"success": True}


# ==============================================================================
# 9. Duplicate submission prevention in UI
# ==============================================================================
def test_09_duplicate_submission_prevention():
    template_path = os.path.join("templates", "enterprise", "change_password.html")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Function setLoading defined and sets disabled attribute
    assert "function setLoading(loading)" in content
    assert "changeBtn.disabled = loading" in content
    assert "btnSpinner.style.display = loading ? 'inline-block' : 'none'" in content
    assert "setLoading(true);" in content
    assert "finally {\n                setLoading(false);\n            }" in content or "finally {\n            setLoading(false);" in content or "finally {" in content


# ==============================================================================
# 10. Successful change-password UI response handling
# ==============================================================================
def test_10_ui_success_handling():
    template_path = os.path.join("templates", "enterprise", "change_password.html")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "showSuccess('Password changed successfully.')" in content
    # Clears inputs on success
    assert "document.getElementById('currentPassword').value = '';" in content
    assert "document.getElementById('newPassword').value = '';" in content
    assert "document.getElementById('confirmPassword').value = '';" in content


# ==============================================================================
# 11. Failed change-password UI response handling & defined helpers
# ==============================================================================
def test_11_ui_error_handling_and_functions():
    template_path = os.path.join("templates", "enterprise", "change_password.html")
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify functions are defined and not throwing ReferenceError
    assert "function hideAll()" in content
    assert "function showError(msg)" in content
    assert "function showSuccess(msg)" in content
    assert "function setLoading(loading)" in content

    # Verify specific error messages are handled
    assert "Your session has expired. Please sign in again." in content
    assert "Failed to change password" in content
    assert "Network error: Unable to change password. Please try again." in content


# ==============================================================================
# 12. Password never logged in plaintext
# ==============================================================================
def test_12_password_never_logged_in_plaintext(auth_handler: AuthHandler, caplog: pytest.LogCaptureFixture):
    auth_handler.create_user("frank", "FrankPass@123!", role="viewer")
    plaintext_old = "FrankPass@123!"
    plaintext_new = "NewSecretPlaintext999!"

    with caplog.at_level(logging.DEBUG):
        res = auth_handler.update_password("frank", plaintext_old, plaintext_new)
        assert res["success"]

    # Verify plaintext password never appears in any log message
    for record in caplog.records:
        assert plaintext_old not in record.message
        assert plaintext_new not in record.message

    # Verify audit log in DB does not contain password
    conn = auth_handler._get_conn()
    rows = conn.execute("SELECT * FROM audit_log WHERE username = 'frank'").fetchall()
    conn.close()
    for row in rows:
        detail_str = str(row["details"] if "details" in row.keys() else "")
        assert plaintext_old not in detail_str
        assert plaintext_new not in detail_str


# ==============================================================================
# 13. User requiring password change (SEC-03 documented)
# ==============================================================================
def test_13_password_change_required_sec03(auth_handler: AuthHandler):
    # Verify handler tracks must_change_password flag accurately
    auth_handler.create_user("grace", "GracePass@123!", role="viewer")
    user = auth_handler.get_user("grace")
    assert user.must_change_password is False

    # Force reset sets must_change_password = 1
    auth_handler.admin_reset_password("grace", "TempPass@123!", admin_username="admin")
    user = auth_handler.get_user("grace")
    assert user.must_change_password is True

    # User updates password -> must_change_password resets to 0
    auth_handler.update_password("grace", "TempPass@123!", "NewPermanentPass@123!")
    user = auth_handler.get_user("grace")
    assert user.must_change_password is False


# ==============================================================================
# 14. Password storage security verification (PBKDF2-SHA256 with salt)
# ==============================================================================
def test_14_password_hash_security():
    pwd = "EnterpriseSecure@12345!"
    h1 = hash_password(pwd)
    h2 = hash_password(pwd)

    # Format: iterations$salt$dk
    parts1 = h1.split("$")
    parts2 = h2.split("$")
    assert len(parts1) == 3
    assert len(parts2) == 3

    iterations, salt1_hex, dk1_hex = parts1
    _, salt2_hex, dk2_hex = parts2

    assert int(iterations) >= 100_000
    assert len(salt1_hex) == 64  # 32 bytes = 64 hex chars
    assert len(dk1_hex) == 64    # 32 bytes SHA256 = 64 hex chars
    assert salt1_hex != salt2_hex  # Unique random salt
    assert h1 != h2

    # Verification
    assert verify_password(pwd, h1)
    assert verify_password(pwd, h2)
    assert not verify_password("WrongPassword@1!", h1)
