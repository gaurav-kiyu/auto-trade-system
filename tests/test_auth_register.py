"""Tests for the /api/auth/register endpoint with rate limiting."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from core.auth.dependencies import AuthDependencies
from core.auth.handler import AuthHandler
from core.auth.routes import _register_rate_limiter, create_auth_router
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def auth_db():
    """Create a temporary auth database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def auth_handler(auth_db):
    """Create an AuthHandler instance with temp DB."""
    handler = AuthHandler(db_path=auth_db, token_ttl=3600)
    return handler


@pytest.fixture
def app(auth_handler):
    """Create a FastAPI app with register route."""
    app = FastAPI()
    auth_deps = AuthDependencies(auth_handler)
    router = create_auth_router(auth_handler, auth_deps)
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create a TestClient and reset the rate limiter."""
    # Reset all rate limit keys before each test
    _register_rate_limiter.reset("register:testclient")
    _register_rate_limiter.reset("register:127.0.0.1")
    return TestClient(app)


class TestRegisterEndpoint:
    """Tests for POST /api/auth/register."""

    def test_register_success(self, client):
        """Test successful registration creates a viewer user."""
        resp = client.post(
            "/api/auth/register",
            json={"username": "newuser", "password": "TestPass123!"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_register_duplicate_username(self, client):
        """Test registering with an existing username fails."""
        client.post(
            "/api/auth/register",
            json={"username": "dupuser", "password": "TestPass123!"},
        )
        resp = client.post(
            "/api/auth/register",
            json={"username": "dupuser", "password": "TestPass456!"},
        )
        assert resp.status_code == 400
        assert "already exists" in resp.json()["detail"].lower()

    def test_register_short_password(self, client):
        """Test registration with a short password fails."""
        resp = client.post(
            "/api/auth/register",
            json={"username": "shortpw", "password": "Ab1"},
        )
        assert resp.status_code == 400
        assert "password" in resp.json()["detail"].lower()

    def test_register_missing_fields(self, client):
        """Test registration with missing username/password fails."""
        resp = client.post(
            "/api/auth/register",
            json={"username": "", "password": ""},
        )
        assert resp.status_code == 400

    def test_register_no_username(self, client):
        """Test registration without username fails."""
        resp = client.post(
            "/api/auth/register",
            json={"password": "TestPass123!"},
        )
        assert resp.status_code == 422 or resp.status_code == 400

    def test_register_creates_viewer_role(self, client, auth_handler):
        """Test registered users get viewer role."""
        client.post(
            "/api/auth/register",
            json={"username": "vieweronly", "password": "TestPass123!"},
        )
        users = auth_handler.list_users()
        viewer = next((u for u in users if u["username"] == "vieweronly"), None)
        assert viewer is not None
        assert viewer["role"] == "viewer"

    def test_register_with_display_name(self, client, auth_handler):
        """Test registration with optional display name."""
        client.post(
            "/api/auth/register",
            json={
                "username": "displayuser",
                "password": "TestPass123!",
                "display_name": "Display User",
            },
        )
        users = auth_handler.list_users()
        user = next((u for u in users if u["username"] == "displayuser"), None)
        assert user is not None
        assert user["display_name"] == "Display User"

    def test_register_rate_limiting(self, client):
        """Test rate limiting blocks excessive registrations."""
        # Successfully register 5 times from same IP
        for i in range(5):
            resp = client.post(
                "/api/auth/register",
                headers={"X-Forwarded-For": "10.0.0.1"},
                json={"username": f"ratelimit{i}", "password": "TestPass123!"},
            )
            assert resp.status_code == 200, f"Registration {i} failed: {resp.text}"

        # 6th attempt should be rate limited
        resp = client.post(
            "/api/auth/register",
            headers={"X-Forwarded-For": "10.0.0.1"},
            json={"username": "ratelimited", "password": "TestPass123!"},
        )
        assert resp.status_code == 429, f"Expected 429, got {resp.status_code}: {resp.text}"

    def test_register_response_format(self, client):
        """Test registration response has expected fields."""
        resp = client.post(
            "/api/auth/register",
            json={"username": "formattest", "password": "TestPass123!"},
        )
        data = resp.json()
        assert "success" in data
        assert data["success"] is True

    def test_register_creates_audit_log(self, client, auth_handler):
        """Test registration is recorded in audit log."""
        client.post(
            "/api/auth/register",
            json={"username": "audituser", "password": "TestPass123!"},
        )
        log = auth_handler.get_audit_log(limit=10)
        entries = [e for e in log if e["username"] == "audituser"]
        assert len(entries) >= 1

    def test_register_different_ip_not_affected(self, client):
        """Test rate limit is per-IP, different IPs can still register."""
        # Exhaust rate limit for one IP
        for i in range(5):
            client.post(
                "/api/auth/register",
                headers={"X-Forwarded-For": "10.0.0.2"},
                json={"username": f"batch1_user{i}", "password": "TestPass123!"},
            )
        # 6th from same IP should be blocked
        resp = client.post(
            "/api/auth/register",
            headers={"X-Forwarded-For": "10.0.0.2"},
            json={"username": "blocked_user", "password": "TestPass123!"},
        )
        assert resp.status_code == 429
        # Different IP should still succeed
        resp2 = client.post(
            "/api/auth/register",
            headers={"X-Forwarded-For": "10.0.0.3"},
            json={"username": "different_ip_user", "password": "TestPass123!"},
        )
        assert resp2.status_code == 200

    def test_register_very_long_username(self, client):
        """Test registration with very long username."""
        long_name = "a" * 100
        resp = client.post(
            "/api/auth/register",
            json={"username": long_name, "password": "TestPass123!"},
        )
        assert resp.status_code == 200 or resp.status_code == 400
