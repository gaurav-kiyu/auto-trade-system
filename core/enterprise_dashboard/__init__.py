"""
Enterprise Web Dashboard - premium FastAPI + Jinja2 + Tailwind CSS UI.

This is the package entry point for the enterprise_dashboard package.
Sub-modules:
  - models.py: Notification, NotificationManager, DashboardNotifier
  - utils.py: error response, freezing helpers, provider tracking
  - main.py: EnterpriseDashboard class and create_enterprise_dashboard factory

Usage:
    from core.enterprise_dashboard import EnterpriseDashboard
    from core.enterprise_dashboard.models import Notification
"""
from __future__ import annotations

from core.enterprise_dashboard.main import EnterpriseDashboard, create_enterprise_dashboard
from core.enterprise_dashboard.models import DashboardNotifier, Notification, NotificationManager
from core.enterprise_dashboard.utils import (
    _DEFAULT_HOST,
    _DEFAULT_PORT,
    _error_response,
    _freeze,
    _get_provider_error_info,
    _record_provider_request,
)

__all__ = [
    "DashboardNotifier",
    "EnterpriseDashboard",
    "Notification",
    "NotificationManager",
    "create_enterprise_dashboard",
    "_DEFAULT_HOST",
    "_DEFAULT_PORT",
]
