"""
AD-KIYU Safe Admin Control Plane.

Provides a FastAPI-based admin server on dedicated port (default 7080)
for safe runtime control of the trading system with full RBAC and audit logging.

Endpoints:
    POST /control/strategy/{name}/{action}  - enable/disable per strategy
    POST /control/asset_class/{class}/{action} - enable/disable per asset class
    POST /control/kill                       - emergency kill
    POST /control/capital/{amount}           - set capital allocation
    POST /control/risk_limit/{name}/{value}  - hot-set risk limits
    POST /control/ai_model/{name}/{action}   - select/rollback AI model
    POST /control/feature_flag/{name}/{value} - toggle feature flags
    GET  /control/state                      - full system state
    GET  /control/audit                      - control action history

Architecture:
    - AdminAuth (JWT tokens from config)
    - RBAC via core.auth.role_manager.RoleManager
    - All mutations: validate() + audit_log() + version() + reversible()
    - Dedicated port (7080), separate from web dashboard (8765)
"""

from core.control_plane.server import (
    ControlPlaneServer,
    create_control_plane_app,
    maybe_start_control_plane,
)

__all__ = [
    "create_control_plane_app",
    "maybe_start_control_plane",
    "ControlPlaneServer",
]
