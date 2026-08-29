"""Tests for core/self_service_provisioning.py and dashboard provisioning routes.

Covers:
  - Blueprint catalog (5 blueprints, environments, artifact existence)
  - Provisioning workflow (request → approve → provisioned, reject path)
  - Persistence round-trip
  - Route registration (importable + callable on a minimal FastAPI app)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from core.self_service_provisioning import (
    SelfServiceProvisioner,
    get_provisioner,
    reset_provisioner,
)


@pytest.fixture(autouse=True)
def _clean_state(tmp_path):
    """Use a temp storage file and reset the singleton per test."""
    reset_provisioner()
    yield tmp_path
    reset_provisioner()


def _new_provisioner(tmp_path) -> SelfServiceProvisioner:
    return SelfServiceProvisioner(str(tmp_path / "provisioning_requests.json"))


# ── Blueprint catalog ────────────────────────────────────────────────────────


def test_blueprint_catalog_has_expected_entries(tmp_path):
    prov = _new_provisioner(tmp_path)
    blueprints = prov.list_blueprints()
    names = {b.name for b in blueprints}
    assert names == {"main_app", "monitoring_stack", "realestate_app", "postgres_db", "dev_env"}
    assert len(blueprints) == 5


def test_blueprint_environments(tmp_path):
    prov = _new_provisioner(tmp_path)
    assert {b.environment for b in prov.list_blueprints()} >= {
        "production", "monitoring", "dev"
    }


def test_list_blueprints_filter_by_environment(tmp_path):
    prov = _new_provisioner(tmp_path)
    only_dev = prov.list_blueprints(environment="dev")
    assert len(only_dev) == 1
    assert only_dev[0].name == "dev_env"


def test_get_blueprint_unknown_returns_none(tmp_path):
    prov = _new_provisioner(tmp_path)
    assert prov.get_blueprint("does_not_exist") is None


def test_blueprint_artifacts_exist_known(tmp_path):
    prov = _new_provisioner(tmp_path)
    status = prov.blueprint_artifacts_exist("main_app")
    assert "Dockerfile" in status
    assert "docker-compose.yml" in status


def test_blueprint_artifacts_exist_unknown(tmp_path):
    prov = _new_provisioner(tmp_path)
    assert prov.blueprint_artifacts_exist("nope") == {}


# ── Provisioning workflow ────────────────────────────────────────────────────


def test_request_provisioning_creates_pending(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("monitoring_stack", actor="dev@example.com")
    assert req is not None
    assert req.status == "PENDING"
    assert req.blueprint == "monitoring_stack"
    assert req.actor == "dev@example.com"


def test_request_provisioning_unknown_blueprint_returns_none(tmp_path):
    prov = _new_provisioner(tmp_path)
    assert prov.request_provisioning("bogus") is None


def test_full_workflow_approve_provision(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("main_app", actor="dev")
    rid = req.request_id

    approved = prov.approve_provisioning(rid, approver="admin", note="ok")
    assert approved.status == "APPROVED"

    done = prov.mark_provisioned(rid, note="deployed")
    assert done.status == "PROVISIONED"
    assert done.note == "deployed"


def test_reject_workflow(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("postgres_db")
    rid = req.request_id
    rejected = prov.reject_provisioning(rid, reason="no budget")
    assert rejected.status == "REJECTED"
    assert rejected.note == "no budget"


def test_approve_non_pending_is_noop(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("dev_env")
    prov.reject_provisioning(req.request_id)
    # Re-approving a REJECTED request must not change state
    again = prov.approve_provisioning(req.request_id)
    assert again.status == "REJECTED"


def test_workflow_transition_guards(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("main_app")
    rid = req.request_id
    # Cannot mark provisioned before approval
    assert prov.mark_provisioned(rid).status == "PENDING"
    prov.approve_provisioning(rid)
    assert prov.mark_provisioned(rid).status == "PROVISIONED"


# ── Queries ──────────────────────────────────────────────────────────────────


def test_list_requests_filters(tmp_path):
    prov = _new_provisioner(tmp_path)
    r1 = prov.request_provisioning("main_app", actor="a")
    prov.request_provisioning("monitoring_stack", actor="b")
    prov.approve_provisioning(r1.request_id)

    assert len(prov.list_requests()) == 2
    assert len(prov.list_requests(status="PENDING")) == 1
    assert len(prov.list_requests(status="APPROVED")) == 1
    assert len(prov.list_requests(environment="monitoring")) == 1


def test_get_request_and_stats(tmp_path):
    prov = _new_provisioner(tmp_path)
    req = prov.request_provisioning("main_app")
    assert prov.get_request(req.request_id).request_id == req.request_id
    stats = prov.get_stats()
    assert stats["blueprints"] == 5
    assert stats["pending"] == 1
    assert stats["environments"] == ["dev", "monitoring", "production"]


# ── Persistence ──────────────────────────────────────────────────────────────


def test_persistence_round_trip(tmp_path):
    path = tmp_path / "provisioning_requests.json"
    prov = SelfServiceProvisioner(str(path))
    req = prov.request_provisioning("main_app", actor="persist-test")
    prov.approve_provisioning(req.request_id)

    prov2 = SelfServiceProvisioner(str(path))
    loaded = prov2.get_request(req.request_id)
    assert loaded is not None
    assert loaded.status == "APPROVED"
    assert loaded.actor == "persist-test"


def test_corrupt_storage_file_tolerated(tmp_path):
    path = tmp_path / "provisioning_requests.json"
    path.write_text("{ not valid json", encoding="utf-8")
    prov = SelfServiceProvisioner(str(path))  # must not raise
    assert prov.get_stats()["requests"] == 0


# ── Route registration ───────────────────────────────────────────────────────


def test_register_provisioning_routes_exists():
    pytest.importorskip("fastapi")
    from core.enterprise_dashboard.routes.provisioning import register_provisioning_routes
    assert callable(register_provisioning_routes)


def test_register_provisioning_routes_runs():
    pytest.importorskip("fastapi")
    from core.enterprise_dashboard.routes.provisioning import register_provisioning_routes
    from fastapi import FastAPI

    app = FastAPI()
    dashboard = MagicMock()
    admin_only = lambda: None  # noqa: E731
    operator_or_admin = lambda: None  # noqa: E731
    register_provisioning_routes(app, dashboard, admin_only, operator_or_admin)
    assert len(app.routes) > 0
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/platform/provisioning/blueprints" in paths
    assert "/api/platform/provisioning/report" in paths


# ── CLI smoke (get_stats path) ───────────────────────────────────────────────


def test_singleton_get_provisioner():
    a = get_provisioner()
    b = get_provisioner()
    assert a is b
