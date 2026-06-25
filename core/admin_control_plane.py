"""
AD-KIYU Admin Control Plane - DEPRECATED backward-compat shim.

This module is deprecated. Use ``core.control_plane`` package instead.

New code should import directly:
    from core.control_plane.server import create_control_plane_app, maybe_start_control_plane
    from core.control_plane.admin_auth import AdminAuth
    from core.control_plane.rbac import ControlRBAC

This shim re-exports all symbols from ``core.control_plane`` for backward
compatibility. It will be removed in a future release.
"""
from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "core.admin_control_plane is DEPRECATED. "
    "Use core.control_plane package instead.",
    DeprecationWarning,
    stacklevel=2,
)

import logging
import threading
from typing import Any

# Re-export everything from the new control_plane package
from core.control_plane import (
    create_control_plane_app,
    maybe_start_control_plane,
)

# ── Backward-compat re-exports ───────────────────────────────────────────────

_log = logging.getLogger(__name__)


def create_admin_app(**kwargs: Any) -> Any:
    """Backward-compat: delegates to create_control_plane_app."""
    _log.debug("create_admin_app called (deprecated) - delegating to create_control_plane_app")
    return create_control_plane_app(**kwargs)


def start_admin_control_plane(
    cfg: dict[str, Any],
    mode_manager: Any = None,
    wal: Any = None,
    certifier: Any = None,
    invariant_engine: Any = None,
    role_manager: Any = None,
    audit_logger: Any = None,
    halt_event: Any = None,
    strategy_registry: Any = None,
    asset_registry: Any = None,
    feature_flags: Any = None,
    model_registry: Any = None,
    config_reload: Any = None,
) -> threading.Thread | None:
    """Backward-compat: delegates to maybe_start_control_plane."""
    _log.debug("start_admin_control_plane called (deprecated) - delegating to maybe_start_control_plane")
    cfg_dict = dict(cfg) if cfg else {}
    return maybe_start_control_plane(
        cfg=cfg_dict,
        mode_manager=mode_manager,
        wal=wal,
        certifier=certifier,
        invariant_engine=invariant_engine,
        role_manager=role_manager,
        audit_logger=audit_logger,
        halt_event=halt_event,
        strategy_registry=strategy_registry,
        asset_registry=asset_registry,
        feature_flags=feature_flags,
        model_registry=model_registry,
        config_reload=config_reload,
    )


# Re-export shared state from the new package


__all__ = [
    "create_admin_app",
    "start_admin_control_plane",
]

