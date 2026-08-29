"""Tests for core/enterprise_dashboard/routes/capacity.py.

Verifies capacity route registration is importable and callable.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from core.enterprise_dashboard.routes.capacity import register_capacity_routes


def test_register_capacity_routes_exists():
    """The capacity route registration function must exist."""
    assert callable(register_capacity_routes)


def test_register_capacity_routes_runs():
    """Registering on a minimal app with mocked dashboard must not raise."""
    from fastapi import FastAPI

    app = FastAPI()
    dashboard = MagicMock()
    admin_only = lambda: None  # noqa: E731
    operator_or_admin = lambda: None  # noqa: E731
    register_capacity_routes(app, dashboard, admin_only, operator_or_admin)
    assert len(app.routes) > 0
