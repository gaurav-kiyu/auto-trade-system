"""Startup integration tests — verify all real estate modules wire correctly into FastAPI.

Tests:
  - startup_realestate_system() returns expected keys for all modules
  - All service instances are created
  - All routers are included (via app.routes count)
  - Disabled config skips initialization
  - Fail-soft pattern handles missing dependencies
  - Each module can be independently accessed
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from unittest.mock import MagicMock

import pytest


def _route_paths(routes: Iterable[Any]) -> list[str]:
    """Collect route paths across Starlette versions.

    Starlette >= 1.5 wraps ``include_router`` targets in a ``_IncludedRouter``
    proxy that exposes no ``.path`` attribute; the real ``APIRoute`` objects
    live under ``original_router.routes``. Walk proxies so route assertions
    work on both 1.3.x (local dev) and 1.5.x (CI).
    """
    paths: list[str] = []
    for route in routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.append(path)
            continue
        original = getattr(route, "original_router", None)
        if original is not None:
            paths.extend(_route_paths(getattr(original, "routes", [])))
    return paths


class TestStartupRealEstateSystem:
    """Test the main startup function with a mock FastAPI app."""

    @pytest.fixture
    def mock_app(self):
        """Create a mock FastAPI app that tracks included routers."""
        from fastapi import FastAPI
        app = FastAPI()
        return app

    def test_startup_returns_all_expected_keys(self, mock_app):
        """The startup function should return results for all major modules."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        assert results is not None
        assert "services" in results
        assert results["services"]["status"] == "ok"

    def test_startup_creates_services(self, mock_app):
        """Services should be created with correct count."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        assert len(instances) > 0

    def test_startup_wires_api_routes(self, mock_app):
        """API routes should be wired into the FastAPI app."""
        from realestate.startup import startup_realestate_system
        initial_route_count = len(mock_app.routes)
        startup_realestate_system(app=mock_app)
        # Routes should have been added
        assert len(mock_app.routes) > initial_route_count

    def test_startup_disabled_by_config(self, mock_app):
        """When REAL_ESTATE_ENABLED is False, startup should skip."""
        from realestate.startup import REAL_ESTATE_STARTUP_KEY, startup_realestate_system
        results = startup_realestate_system(cfg={"REAL_ESTATE_ENABLED": False}, app=mock_app)
        assert results[REAL_ESTATE_STARTUP_KEY]["status"] == "skipped"

    def test_startup_returns_dict(self, mock_app):
        """Startup should always return a dict, even on error."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        assert isinstance(results, dict)

    def test_startup_without_app(self):
        """Startup should work without a FastAPI app (no route wiring)."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system()
        assert results is not None
        assert "services" in results

    def test_startup_has_service_instances_key(self, mock_app):
        """The result should contain _service_instances with property_service."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        assert "property_service" in instances
        assert hasattr(instances["property_service"], "create_property")

    def test_startup_with_container(self, mock_app):
        """Startup should accept a DI container without errors."""
        from realestate.startup import startup_realestate_system
        mock_container = MagicMock()
        results = startup_realestate_system(app=mock_app, container=mock_container)
        assert results is not None

    def test_all_module_statuses_are_not_error(self, mock_app):
        """No module should report 'error' status (skipped is OK)."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        errors = {k: v for k, v in results.items() if isinstance(v, dict) and v.get("status") == "error"}
        assert len(errors) == 0, f"Modules with error status: {errors}"


class TestServicesIntegrity:
    """Test that services created by startup are properly initialized."""

    def test_property_service_has_listings(self, mock_app):
        """Property service should be initialized and able to list properties."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        ps = instances.get("property_service")
        assert ps is not None
        properties = ps.list_all()
        assert isinstance(properties, list)

    def test_search_service_exists(self, mock_app):
        """Search service should be available."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        ss = instances.get("search_service")
        assert ss is not None

    def test_notification_engine_wired(self, mock_app):
        """Notification engine should be available."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        ne = instances.get("notification_engine")
        assert ne is not None

    def test_saved_properties_wired(self, mock_app):
        """Saved properties service should be available."""
        from realestate.startup import startup_realestate_system
        results = startup_realestate_system(app=mock_app)
        instances = results.get("_service_instances", {})
        sp = instances.get("saved_properties")
        assert sp is not None


class TestRouterRegistration:
    """Test that routers are correctly registered with the FastAPI app."""

    def test_realestate_routes_exist(self, mock_app):
        """After startup, routes should contain real estate paths."""
        from realestate.startup import startup_realestate_system
        startup_realestate_system(app=mock_app)
        route_paths = _route_paths(mock_app.routes)
        re_routes = [p for p in route_paths if "/api/realestate" in p or "/realestate" in p]
        assert len(re_routes) > 0

    def test_auth_routes_registered(self, mock_app):
        """Auth routes should be registered."""
        from realestate.startup import startup_realestate_system
        startup_realestate_system(app=mock_app)
        paths = _route_paths(mock_app.routes)
        auth_paths = [p for p in paths if "/auth" in p or "login" in p]
        assert len(auth_paths) > 0

    def test_property_api_routes(self, mock_app):
        """Property CRUD routes should be registered."""
        from realestate.startup import startup_realestate_system
        startup_realestate_system(app=mock_app)
        paths = _route_paths(mock_app.routes)
        prop_routes = [p for p in paths if "properties" in p.lower()]
        assert len(prop_routes) > 0

    def test_routes_handle_requests(self, mock_app):
        """FastAPI should accept requests to registered routes."""
        from realestate.startup import startup_realestate_system
        startup_realestate_system(app=mock_app)
        from fastapi.testclient import TestClient
        client = TestClient(mock_app)
        response = client.get("/api/realestate/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "service" in data

    def test_routes_work_without_auth(self, mock_app):
        """Unauthenticated routes should work without auth headers."""
        from realestate.startup import startup_realestate_system
        startup_realestate_system(app=mock_app)
        from fastapi.testclient import TestClient
        client = TestClient(mock_app)
        # Health endpoint should work without auth
        response = client.get("/api/realestate/health")
        assert response.status_code == 200


@pytest.fixture
def mock_app():
    from fastapi import FastAPI
    return FastAPI()
