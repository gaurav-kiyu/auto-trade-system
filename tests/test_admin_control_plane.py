"""
AD-KIYU Admin Control Plane Certification - 22-endpoint test suite.

Tests all 22 routes for:
  - Auth enforcement (X-Admin-Token)
  - RBAC permission checking (X-Operator-Identity)
  - Graceful degradation when refs are None
  - Audit event recording
  - Each model endpoint's real API contract
"""
from __future__ import annotations

import threading

import pytest

pytest.importorskip("fastapi")
from core.control_plane import create_control_plane_app as create_admin_app
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """Clear shared mutable state between tests to prevent test pollution."""
    from core.control_plane.server import _AUDIT_EVENTS, _AUDIT_LOCK
    with _AUDIT_LOCK:
        _AUDIT_EVENTS.clear()
    import core.invariants.engine as inv_engine
    inv_engine._disabled_checks.clear()


@pytest.fixture
def app():
    return create_admin_app(
        cfg={"admin_control_plane_auth_token": "test-token"},
        mode_manager_ref=None,
        wal_ref=None,
        certifier_ref=None,
        invariant_engine_ref=None,
        role_manager_ref=None,
        audit_logger_ref=None,
        halt_event_ref=None,
        strategy_registry_ref=None,
        asset_registry_ref=None,
        feature_flags_ref=None,
        model_registry_ref=None,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def _auth(headers: dict | None = None) -> dict:
    h = {"X-Admin-Token": "test-token"}
    if headers:
        h.update(headers)
    return h


# ---------------------------------------------------------------------------
# Auth - all endpoints must enforce token
# ---------------------------------------------------------------------------


def test_root_no_auth(client):
    resp = client.get("/")
    assert resp.status_code == 200  # root is health, no auth


def test_mode_get_no_token(client):
    resp = client.get("/mode")
    assert resp.status_code == 401


def test_mode_post_no_token(client):
    resp = client.post("/mode/PAPER")
    assert resp.status_code == 401


def test_wal_no_token(client):
    resp = client.get("/wal")
    assert resp.status_code == 401


def test_cert_no_token(client):
    resp = client.get("/cert")
    assert resp.status_code == 401


def test_invariants_no_token(client):
    resp = client.get("/invariants")
    assert resp.status_code == 401


def test_invariant_toggle_no_token(client):
    resp = client.post("/invariants/dummy/toggle")
    assert resp.status_code == 401


def test_halt_no_token(client):
    resp = client.post("/control/halt")
    assert resp.status_code == 401


def test_resume_no_token(client):
    resp = client.post("/control/resume")
    assert resp.status_code == 401


def test_strategies_no_token(client):
    resp = client.get("/strategies")
    assert resp.status_code == 401


def test_assets_no_token(client):
    resp = client.get("/assets")
    assert resp.status_code == 401


def test_features_no_token(client):
    resp = client.get("/features")
    assert resp.status_code == 401


def test_models_no_token(client):
    resp = client.get("/models")
    assert resp.status_code == 401


def test_audit_no_token(client):
    resp = client.get("/audit")
    assert resp.status_code == 401


def test_roles_no_token(client):
    resp = client.get("/roles")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Graceful degradation - all refs are None
# ---------------------------------------------------------------------------


def test_root_health(client):
    resp = client.get("/", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert all(v is False for v in body["refs"].values())


def test_mode_get_unavailable(client):
    resp = client.get("/mode", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["mode"]


def test_mode_post_unavailable(client):
    resp = client.post("/mode/PAPER", headers=_auth())
    assert resp.status_code == 503
    assert "not wired" in resp.json()["detail"]


def test_wal_unavailable(client):
    resp = client.get("/wal", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["wal"]


def test_cert_unavailable(client):
    resp = client.get("/cert", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["cert"]


def test_invariants_unavailable(client):
    resp = client.get("/invariants", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["invariants"]


def test_halt_unavailable(client):
    resp = client.post("/control/halt", headers=_auth())
    assert resp.status_code == 503
    assert "not wired" in resp.json()["detail"]


def test_strategies_unavailable(client):
    resp = client.get("/strategies", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["strategies"]


def test_assets_unavailable(client):
    resp = client.get("/assets", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["assets"]


def test_features_unavailable(client):
    resp = client.get("/features", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["features"]


def test_models_unavailable(client):
    resp = client.get("/models", headers=_auth())
    assert resp.status_code == 200
    assert "unavailable" in resp.json()["models"]


# ---------------------------------------------------------------------------
# Auth - bad token
# ---------------------------------------------------------------------------


def test_bad_token(client):
    resp = client.get("/mode", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


def test_bad_token_mutation(client):
    resp = client.post("/control/halt", headers={"X-Admin-Token": "wrong"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# RBAC - no role_manager configured means no permission checks
# ---------------------------------------------------------------------------


def test_no_rbac_allows_mutation(client):
    """Without role_manager, mutation endpoints should still 503 (ref None) not 403."""
    resp = client.post("/control/halt", headers=_auth())
    assert resp.status_code == 503  # halt_event_ref is None, not 403


# ---------------------------------------------------------------------------
# Full wiring with real refs
# ---------------------------------------------------------------------------


@pytest.fixture
def wired_app():
    """Admin app with real (in-memory) refs for all endpoints."""
    from core.auth.role_manager import RoleManager
    from core.operating_mode import OperatingMode, OperatingModeManager

    halt_ev = threading.Event()
    role_mgr = RoleManager(default_role="observer")
    role_mgr.assign("alice", "admin")
    strategy_reg: dict[str, bool] = {"momentum": True, "mean_reversion": False}
    asset_reg: dict[str, bool] = {"NIFTY": True, "BANKNIFTY": True}
    feature_flags: dict[str, bool] = {"new_ml_model": False, "spread_strategy": True}
    mode_mgr = OperatingModeManager(initial_mode=OperatingMode.PAPER)

    import core.invariants.engine as inv_engine
    inv_engine._disabled_checks.clear()

    return create_admin_app(
        cfg={
            "admin_control_plane_auth_token": "test-token",
            "admin_default_role": "observer",
        },
        mode_manager_ref=mode_mgr,
        wal_ref=None,
        certifier_ref=None,
        invariant_engine_ref=inv_engine,
        role_manager_ref=role_mgr,
        audit_logger_ref=None,
        halt_event_ref=halt_ev,
        strategy_registry_ref=strategy_reg,
        asset_registry_ref=asset_reg,
        feature_flags_ref=feature_flags,
        model_registry_ref=None,
    )


@pytest.fixture
def wired_client(wired_app):
    return TestClient(wired_app)


def test_wired_mode_get(wired_client):
    resp = wired_client.get("/mode", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert "PAPER" in resp.json()["mode"]


def test_wired_mode_set(wired_client):
    resp = wired_client.post("/mode/SIGNAL_ONLY", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "applied"
    # Verify it stuck
    resp2 = wired_client.get("/mode", headers=_auth({"X-Operator-Identity": "alice"}))
    assert "SIGNAL_ONLY" in resp2.json()["mode"]


def test_wired_halt_and_resume(wired_client):
    resp = wired_client.post("/control/halt", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "halted"

    resp = wired_client.get("/control/status", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["halted"] is True

    resp = wired_client.post("/control/resume", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"

    resp = wired_client.get("/control/status", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["halted"] is False


def test_wired_strategy_toggle(wired_client):
    resp = wired_client.get("/strategies", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["strategies"]["momentum"] is True

    resp = wired_client.post("/strategies/momentum/toggle",
                              headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = wired_client.get("/strategies", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["strategies"]["momentum"] is False


def test_wired_asset_toggle(wired_client):
    resp = wired_client.post("/assets/BANKNIFTY/toggle",
                              headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False

    resp = wired_client.get("/assets", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["assets"]["BANKNIFTY"] is False


def test_wired_feature_toggle(wired_client):
    resp = wired_client.post("/features/new_ml_model",
                              headers=_auth({"X-Operator-Identity": "alice"}),
                              json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["enabled"] is True

    resp = wired_client.get("/features", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["features"]["new_ml_model"] is True


def test_wired_invariant_toggle(wired_client):
    """Toggle an invariant check on/off via the engine module."""
    resp = wired_client.post("/invariants/dummy_check/toggle",
                              headers=_auth({"X-Operator-Identity": "alice"}))
    # 200 even if check doesn't exist - toggle is idempotent
    assert resp.status_code == 200
    assert "enabled" in resp.json()


def test_wired_rbac_enforced(wired_client):
    """Observer should be blocked from halt_trading."""
    # 'bob' has no explicit role → defaults to 'observer' which lacks halt_trading
    resp = wired_client.post("/control/halt",
                              headers=_auth({"X-Operator-Identity": "bob"}))
    assert resp.status_code == 403


def test_wired_rbac_admin_allowed(wired_client):
    """Admin should be able to halt."""
    resp = wired_client.post("/control/halt",
                              headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200


def test_wired_role_assignment(wired_client):
    resp = wired_client.post("/roles/bob",
                              headers=_auth({"X-Operator-Identity": "alice"}),
                              json={"role": "operator"})
    assert resp.status_code == 200
    assert resp.json()["role"] == "operator"

    resp = wired_client.get("/roles", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.json()["roles"].get("bob") == "operator"


def test_wired_audit_log(wired_client):
    """Verify audit events accumulate in the ring buffer."""
    wired_client.post("/control/halt", headers=_auth({"X-Operator-Identity": "alice"}))
    wired_client.post("/control/resume", headers=_auth({"X-Operator-Identity": "alice"}))
    resp = wired_client.get("/audit", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 2
    events = body["events"]
    assert events[-1]["action"] == "resume"
    assert events[-1]["resource"] == "trading"


def test_wired_root_with_refs(wired_client):
    resp = wired_client.get("/", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    refs = resp.json()["refs"]
    assert refs["mode_manager"] is True
    assert refs["halt_event"] is True
    assert refs["strategy_registry"] is True
    assert refs["feature_flags"] is True


def test_wired_broker_summary(wired_client):
    resp = wired_client.get("/broker", headers=_auth({"X-Operator-Identity": "alice"}))
    assert resp.status_code == 200
    assert "operating_mode" in resp.json()


# ---------------------------------------------------------------------------
# Model registry fixture (real ModelRegistry with :memory: db)
# ---------------------------------------------------------------------------


@pytest.fixture
def model_app():
    import os
    import tempfile

    from core.ai.model_registry import ModelRegistry
    from core.auth.role_manager import RoleManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = tmp.name
    tmp.close()

    mr = ModelRegistry(db_path=db_path)
    mr.register("model-1", "1.0.0", "win_prob_lgbm",
                metrics={"accuracy": 0.85},
                metadata={"features": 14})
    mr.register("model-2", "2.0.0", "win_prob_lgbm",
                metrics={"accuracy": 0.87},
                metadata={"features": 14})

    role_mgr = RoleManager(default_role="admin")

    app = create_admin_app(
        cfg={"admin_control_plane_auth_token": "test-token"},
        model_registry_ref=mr,
        role_manager_ref=role_mgr,
    )

    yield app

    mr.close()
    os.unlink(db_path)


@pytest.fixture
def model_client(model_app):
    return TestClient(model_app)


def test_models_list(model_client):
    resp = model_client.get("/models", headers=_auth({"X-Operator-Identity": "admin"}))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["models"]) == 2
    assert body["models"][0]["name"] == "win_prob_lgbm"


def test_models_select(model_client):
    resp = model_client.post("/models/model-1/select",
                              headers=_auth({"X-Operator-Identity": "admin"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "selected"


# ---------------------------------------------------------------------------
# Config Reload
# ---------------------------------------------------------------------------


def test_config_reload_no_token(client):
    resp = client.post("/config/reload")
    assert resp.status_code == 401


def test_config_reload_unavailable(client):
    resp = client.post("/config/reload", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unavailable"


@pytest.fixture
def reload_client():
    _called = False

    def _reload_handler():
        nonlocal _called
        _called = True
        return {"status": "ok", "detail": "test reload", "keys": 42}

    from core.auth.role_manager import RoleManager
    rm = RoleManager(default_role="admin")
    rm.assign("observer", "observer")

    app = create_admin_app(
        cfg={"admin_control_plane_auth_token": "test-token"},
        config_reload_ref=_reload_handler,
        role_manager_ref=rm,
    )
    return TestClient(app)


def test_config_reload_ok(reload_client):
    resp = reload_client.post("/config/reload", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["result"]["keys"] == 42


def test_config_reload_audit_event(reload_client):
    from core.control_plane.server import _AUDIT_EVENTS
    _AUDIT_EVENTS.clear()
    resp = reload_client.post("/config/reload", headers=_auth())
    assert resp.status_code == 200
    events = list(_AUDIT_EVENTS)
    assert any(e.get("action") == "reload" and e.get("event_type") == "config_reload" for e in events)


def test_config_reload_requires_permission(reload_client):
    resp = reload_client.post("/config/reload",
                              headers=_auth({"X-Operator-Identity": "observer"}))
    assert resp.status_code == 403
