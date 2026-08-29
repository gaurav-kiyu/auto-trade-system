"""Tests for core/enterprise_dashboard/routes/intelligence.py.

Verifies the intelligence route registration and its pure helper.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from core.enterprise_dashboard.routes.intelligence import (
    _compute_total_tests,
    register_intelligence_routes,
)


def test_compute_total_tests_returns_int():
    """_compute_total_tests must return a non-negative integer."""
    total = _compute_total_tests()
    assert isinstance(total, int)
    assert total >= 0


def test_register_intelligence_routes_runs():
    """Registering on a minimal app with mocked dashboard must not raise."""
    from fastapi import FastAPI

    app = FastAPI()
    dashboard = MagicMock()
    register_intelligence_routes(
        app, dashboard, lambda: None, lambda: None  # type: ignore[arg-type]
    )
    assert len(app.routes) > 0
