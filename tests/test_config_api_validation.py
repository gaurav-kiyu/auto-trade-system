"""Tests for Admin Config API Request Validation.

Validates:
1. Malformed payloads (strings, integers, lists) return 422 Unprocessable Entity.
2. Defensive validation in _validate_config_change, _preview_config_change,
   and _apply_config_change never raises AttributeError.
3. Valid dictionary payload is processed normally.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse
from fastapi.testclient import TestClient

from core.enterprise_dashboard.main import EnterpriseDashboard


class DummyDashboard:
    """Mock EnterpriseDashboard for testing config validation."""
    def __init__(self):
        self._cfg = {"EXECUTION_MODE": "PAPER", "BOT_TOKEN": "test"}

    def _validate_config_change(self, change):
        return EnterpriseDashboard._validate_config_change(self, change)

    def _preview_config_change(self, change):
        return EnterpriseDashboard._preview_config_change(self, change)

    def _apply_config_change(self, change, username):
        return EnterpriseDashboard._apply_config_change(self, change, username)


def test_internal_methods_reject_non_dict():
    dash = DummyDashboard()

    # 1. String payload must not raise AttributeError
    val_res = dash._validate_config_change("a string")
    assert val_res["valid"] is False
    assert "must be a JSON object" in val_res["errors"][0]["message"]

    prev_res = dash._preview_config_change("a string")
    assert "must be a JSON object" in prev_res["error"]

    apply_res = dash._apply_config_change("a string", "admin")
    assert apply_res["success"] is False
    assert "must be a JSON object" in apply_res["error"]

    # 2. List payload must not raise AttributeError
    val_res_list = dash._validate_config_change(["key1", "key2"])
    assert val_res_list["valid"] is False

    prev_res_list = dash._preview_config_change([1, 2, 3])
    assert "must be a JSON object" in prev_res_list["error"]

    apply_res_list = dash._apply_config_change([1, 2, 3], "admin")
    assert apply_res_list["success"] is False

    # 3. Integer payload
    assert dash._validate_config_change(12345)["valid"] is False
    assert "must be a JSON object" in dash._preview_config_change(12345)["error"]
    assert dash._apply_config_change(12345, "admin")["success"] is False


def test_config_api_routes_reject_string_payload():
    """Verify route handlers reject non-dict payloads with HTTP 422."""
    from fastapi import FastAPI
    from core.enterprise_dashboard.routes.admin import register_admin_routes

    app = FastAPI()

    class MockAuthDeps:
        def require_permission(self, perm):
            async def _dep():
                class MockUser:
                    username = "super_admin"
                return MockUser()
            return _dep

        def require_auth(self):
            async def _dep():
                return {"username": "super_admin"}
            return _dep

        def require_role(self, *roles: str):
            async def _dep():
                class MockUser:
                    username = "super_admin"
                    role = "super_admin"
                return MockUser()
            return _dep

    class MockDash:
        _auth_deps = MockAuthDeps()
        _cfg = {"EXECUTION_MODE": "PAPER"}

        def _validate_config_change(self, c):
            return DummyDashboard()._validate_config_change(c)

        def _preview_config_change(self, c):
            return DummyDashboard()._preview_config_change(c)

        def _apply_config_change(self, c, u):
            return DummyDashboard()._apply_config_change(c, u)

        def _load_defaults(self):
            return {}

        def _get_config_history(self):
            return []

        def _get_config_audit_log(self, limit=50):
            return []

    register_admin_routes(app, MockDash(), admin_only=None, operator_or_admin=None)
    client = TestClient(app)

    # POST /api/config/apply with raw string
    resp = client.post("/api/config/apply", json="invalid string payload")
    assert resp.status_code == 422
    data = resp.json()
    assert data["success"] is False
    assert "must be a JSON object" in data["error"]

    # POST /api/config/validate with raw string
    resp_val = client.post("/api/config/validate", json="invalid string payload")
    assert resp_val.status_code == 422
    assert resp_val.json()["valid"] is False

    # POST /api/config/preview with raw list
    resp_prev = client.post("/api/config/preview", json=[1, 2, 3])
    assert resp_prev.status_code == 422
    assert "must be a JSON object" in resp_prev.json()["error"]
