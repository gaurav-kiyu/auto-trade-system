"""Enterprise Web Dashboard - premium FastAPI + Jinja2 + Tailwind CSS UI.

This is the package entry point for the enterprise_dashboard package.
Sub-modules:
  - models.py: Notification, NotificationManager, DashboardNotifier
  - utils.py: error response, freezing helpers, provider tracking
  - main.py: EnterpriseDashboard class and create_enterprise_dashboard factory

Usage:
    from core.enterprise_dashboard import EnterpriseDashboard
    from core.enterprise_dashboard.models import Notification

Note: Lazy imports avoid circular import when running via
python -m core.enterprise_dashboard.main.
"""

from __future__ import annotations

import importlib
from typing import Any


def __getattr__(name: str) -> Any:
    """Lazy import from submodules to avoid circular imports with main.py.

    This module-level __getattr__ (PEP 562) defers imports until the symbol
    is actually accessed, breaking the circular chain that occurs when
    __init__.py eagerly imports from main.py while main.py is still being
    loaded during ``python -m core.enterprise_dashboard.main``.
    """
    _lazy_map = {
        "EnterpriseDashboard": "core.enterprise_dashboard.main",
        "create_enterprise_dashboard": "core.enterprise_dashboard.main",
        "DashboardNotifier": "core.enterprise_dashboard.models",
        "Notification": "core.enterprise_dashboard.models",
        "NotificationManager": "core.enterprise_dashboard.models",
        "_DEFAULT_HOST": "core.enterprise_dashboard.utils",
        "_DEFAULT_PORT": "core.enterprise_dashboard.utils",
        # Provider-request tracking helpers (used by /api/system/data-providers/health)
        "_LOCK": "core.enterprise_dashboard.utils",
        "_PROVIDER_REQUESTS": "core.enterprise_dashboard.utils",
        "_get_provider_error_info": "core.enterprise_dashboard.utils",
        "_record_provider_request": "core.enterprise_dashboard.utils",
    }
    if name in _lazy_map:
        try:
            mod = importlib.import_module(_lazy_map[name])
            return getattr(mod, name)
        except ImportError:
            if name == "EnterpriseDashboard":
                class DummyEnterpriseDashboard:
                    def __init__(self, *args: Any, **kwargs: Any) -> None: pass
                    def run(self, *args: Any, **kwargs: Any) -> None: pass
                return DummyEnterpriseDashboard
            elif name == "create_enterprise_dashboard":
                def create_dummy_dashboard(*args: Any, **kwargs: Any) -> Any:
                    return None
                return create_dummy_dashboard
            raise

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "_DEFAULT_HOST",
    "_DEFAULT_PORT",
    "DashboardNotifier",
    "EnterpriseDashboard",
    "Notification",
    "NotificationManager",
    "create_enterprise_dashboard",
]
