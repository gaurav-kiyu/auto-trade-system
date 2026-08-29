"""Tests for core/enterprise_dashboard/routes/intelligence_incidents.py."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from core.enterprise_dashboard.routes.intelligence_incidents import (
    register_incident_routes,
)


def test_register_incident_routes_exists():
    assert callable(register_incident_routes)


def test_register_incident_routes_runs():
    from fastapi import FastAPI

    app = FastAPI()
    dashboard = MagicMock()
    register_incident_routes(app, dashboard, lambda: None, lambda: None)  # type: ignore[arg-type]
    assert len(app.routes) > 0
