"""Admin Control Plane Wiring — dependency creation and thread startup.

Extracted from ``index_trader.py`` ``_init_admin_control_plane()`` (DEBT-008).
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable


__all__ = [
    "init_admin_control_plane",
]

_log = logging.getLogger(__name__)


def init_admin_control_plane(
    cfg: dict[str, Any],
    reload_config_handler_fn: Callable[[], dict] | None = None,
    notify_fn: Callable | None = None,
) -> threading.Thread | None:
    """Wire and start the admin control plane with live references.

    Creates all necessary dependencies if the admin plane is enabled in config.
    Returns the thread handle, or None if disabled.

    Args:
        cfg: Effective configuration dict.
        reload_config_handler_fn: Callback for config reload requests.
        notify_fn: Optional notification function for warnings.

    Returns:
        The control plane thread, or None if disabled.
    """
    enabled = cfg.get("admin_control_plane_enabled", False)
    if not enabled:
        _log.info("Admin control plane disabled - skipping wiring")
        return None

    from core.auth.role_manager import RoleManager
    from core.control_plane import maybe_start_control_plane
    from core.execution.idempotency.certifier import IdempotencyCertifier
    from core.operating_mode import OperatingModeManager
    from core.safety_state import _HARD_HALT
    from core.wal.journal import WriteAheadJournal

    mode_mgr = OperatingModeManager()
    wal = WriteAheadJournal(db_path=cfg.get("wal_journal_db_path", "data/wal_journal.db"))
    certifier = IdempotencyCertifier(
        db_path=cfg.get("idempotency_db_path", "execution_state.db"),
        slot_seconds=int(cfg.get("idempotency_slot_seconds", 300)),
    )
    role_mgr = RoleManager(default_role=cfg.get("admin_default_role", "observer"))
    role_mgr.load_from_config(dict(cfg))

    # Audit logger singleton
    try:
        from infrastructure.security.audit_logger import get_audit_logger

        audit_logger = get_audit_logger()
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        _log.warning("AuditLogger unavailable — admin audit trail degraded")
        audit_logger = None

    # Model registry (lazy, best-effort)
    try:
        from core.ai.model_registry import ModelRegistry

        model_registry = ModelRegistry(
            db_path=cfg.get("model_registry_db_path", "data/model_registry.db")
        )
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, OSError):
        _log.warning("ModelRegistry unavailable — admin model endpoints degraded")
        model_registry = None

    # Simple in-memory registries for strategy/asset/feature toggles
    strategy_registry: dict[str, bool] = {}
    asset_registry: dict[str, bool] = {}
    feature_flags: dict[str, bool] = {}

    # Pre-populate from config if present
    for s in (cfg.get("admin_strategies") or {}):
        strategy_registry[s] = True
    for a in (cfg.get("admin_assets") or {}):
        asset_registry[a] = True
    for f, v in (cfg.get("admin_feature_flags") or {}).items():
        feature_flags[f] = bool(v)

    # Wire invariants module as the engine reference
    import core.invariants.engine as invariant_engine_module

    thread = maybe_start_control_plane(
        cfg=dict(cfg),
        mode_manager=mode_mgr,
        wal=wal,
        certifier=certifier,
        invariant_engine=invariant_engine_module,
        role_manager=role_mgr,
        audit_logger=audit_logger,
        halt_event=_HARD_HALT,
        strategy_registry=strategy_registry,
        asset_registry=asset_registry,
        feature_flags=feature_flags,
        model_registry=model_registry,
        config_reload=reload_config_handler_fn,
    )
    if thread is not None:
        _log.info("Admin control plane started (thread=%s)", thread.name)
    else:
        _log.info("Admin control plane: maybe_start_control_plane returned None")
    return thread
