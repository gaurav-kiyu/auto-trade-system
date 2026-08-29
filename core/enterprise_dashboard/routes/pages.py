"""HTML page route registration for the Enterprise Dashboard.

Handles: /, /login, /register, /admin/users, /admin/config,
/admin/kill-switch, /change-password, and SPA redirect pages.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

_log = logging.getLogger(__name__)


def _resolve_session_user(request: Request, dashboard):  # type: ignore[no-untyped-def]
    """Resolve the logged-in user from the opb_session cookie, or None.

    Extracted from ~23 near-identical inline copies of this same lookup
    across the page handlers below.
    """
    session_token = request.cookies.get("opb_session", "")
    if not session_token:
        return None
    token = dashboard._auth.verify_session(session_token)
    if not token:
        return None
    return dashboard._auth.get_user_by_id(token.user_id)






def _page_context(user, nonce: str, current_page: str) -> dict:
    """Shared authenticated-page context, including effective RBAC flags."""
    from core.auth.permissions import Permission, Role, get_role_permissions, is_super_admin_identity
    from core.auth.user_signal_permissions import UserPermissionManager
    user_dict = user.to_dict() if hasattr(user, "to_dict") else dict(user or {})
    username = str(user_dict.get("username", ""))
    role = str(user_dict.get("role", "viewer")).lower()
    effective = UserPermissionManager.get_instance().get_effective_permissions(username, base_role=role)
    if not effective:
        effective = {p.value for p in get_role_permissions(role)}
    return {
        "user": user_dict, "nonce": nonce, "current_page": current_page,
        "is_admin": role in (Role.ADMIN.value, Role.SUPER_ADMIN.value),
        "is_super_admin": is_super_admin_identity(username, role),
        "can_view_state": Permission.VIEW_STATE.value in effective,
        "can_halt_trading": Permission.HALT_TRADING.value in effective,
        "can_modify_risk": Permission.MODIFY_RISK_LIMITS.value in effective,
        "can_toggle_strategies": Permission.TOGGLE_STRATEGIES.value in effective,
        "can_deploy_models": Permission.DEPLOY_MODELS.value in effective,
        "can_modify_code": Permission.MODIFY_CODE.value in effective,
        "can_view_logs": Permission.VIEW_LOGS.value in effective,
        "can_manage_brokers": Permission.ADD_BROKERS.value in effective,
        "can_modify_config": Permission.MODIFY_CONFIG.value in effective,
        "can_manage_users": Permission.MANAGE_USERS.value in effective,
        "can_manage_permissions": Permission.MANAGE_PERMISSIONS.value in effective,
    }


def _require_permission_page(request: Request, dashboard, permission: str, *, admin_only: bool = False):
    """Authenticate a page and enforce the same effective per-user RBAC used by APIs."""
    user = _resolve_session_user(request, dashboard)
    if user is None:
        return None, RedirectResponse(url="/login")
    role = str(user.role or "viewer").lower()
    from core.auth.permissions import is_super_admin_identity
    if is_super_admin_identity(user.username, role):
        allowed = True
    elif admin_only and role not in ("admin", "super_admin"):
        allowed = False
    else:
        from core.auth.user_signal_permissions import UserPermissionManager
        allowed = UserPermissionManager.get_instance().user_has_permission(user.username, permission, base_role=role)
    if not allowed:
        nonce = getattr(request.state, "nonce", "")
        return None, dashboard._templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"code": 403, "message": f"Permission required: {permission}", "nonce": nonce},
            status_code=403,
        )
    return user, None


def register_page_routes(app, dashboard, _require_admin_page, _require_operator_or_admin_page=None):  # type: ignore[no-untyped-def]
    """Register all HTML page routes on the FastAPI app.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        _require_admin_page: Callable (request) -> (user, error_response)
            used to check admin auth for admin-only HTML pages.
        _require_operator_or_admin_page: Callable (request) -> (user, error_response)
            used to check operator/admin auth for privileged pages.

    """
    if _require_operator_or_admin_page is None:
        _require_operator_or_admin_page = _require_admin_page

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context=_page_context(user, nonce, "dashboard"),
        )

    @app.get("/profile", response_class=HTMLResponse)
    async def profile_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="profile.html",
            context=_page_context(user, nonce, "profile"),
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"nonce": nonce},
        )

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"nonce": nonce},
        )

    @app.get("/admin/users", response_class=HTMLResponse)
    async def admin_users_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "manage_permissions", admin_only=True)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_users.html",
            context=_page_context(user, nonce, "admin_users"),
        )

    @app.get("/admin/config", response_class=HTMLResponse)
    async def admin_config_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "modify_config", admin_only=True)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_config.html",
            context=_page_context(user, nonce, "admin_config"),
        )

    @app.get("/admin/signals", response_class=HTMLResponse)
    async def admin_signals_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        role = str(user.role or "viewer").lower()
        from core.auth.permissions import is_super_admin_identity
        from core.auth.user_signal_permissions import UserPermissionManager
        allowed = is_super_admin_identity(user.username, role) or any(
            UserPermissionManager.get_instance().user_has_permission(user.username, perm, base_role=role)
            for perm in ("modify_config", "view_logs")
        )
        if not allowed:
            return dashboard._templates.TemplateResponse(
                request=request, name="error.html",
                context={"code": 403, "message": "Permission required: modify_config or view_logs", "nonce": nonce},
                status_code=403,
            )
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_signals.html",
            context=_page_context(user, nonce, "admin_signals"),
        )

    @app.get("/my-signals", response_class=HTMLResponse)
    async def my_signals_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="user_signals.html",
            context=_page_context(user, nonce, "my_signals"),
        )

    @app.get("/sector-radar", response_class=HTMLResponse)
    async def sector_radar_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        return dashboard._templates.TemplateResponse(
            request=request,
            name="sector_radar.html",
            context=_page_context(user, nonce, "sector_radar"),
        )

    @app.get("/trade-copier", response_class=HTMLResponse)
    async def trade_copier_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_admin_page(request)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="trade_copier.html",
            context=_page_context(user, nonce, "trade_copier"),
        )

    @app.get("/margin-radar", response_class=HTMLResponse)
    async def margin_radar_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        return dashboard._templates.TemplateResponse(
            request=request,
            name="margin_radar.html",
            context=_page_context(user, nonce, "margin_radar"),
        )

    @app.get("/strategy-sandbox", response_class=HTMLResponse)
    async def strategy_sandbox_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        return dashboard._templates.TemplateResponse(
            request=request,
            name="strategy_sandbox.html",
            context=_page_context(user, nonce, "strategy_sandbox"),
        )

    @app.get("/fii-dii-radar", response_class=HTMLResponse)
    async def fii_dii_radar_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        return dashboard._templates.TemplateResponse(
            request=request,
            name="fii_dii_radar.html",
            context=_page_context(user, nonce, "fii_dii_radar"),
        )

    @app.get("/expiry-harvester", response_class=HTMLResponse)
    async def expiry_harvester_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        return dashboard._templates.TemplateResponse(
            request=request,
            name="expiry_harvester.html",
            context=_page_context(user, nonce, "expiry_harvester"),
        )

    @app.get("/pricing-plans", response_class=HTMLResponse)
    async def pricing_plans_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "modify_config", admin_only=True)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="pricing_plans.html",
            context=_page_context(user, nonce, "pricing_plans"),
        )

    @app.get("/admin/kill-switch", response_class=HTMLResponse)
    async def kill_switch_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "halt_trading", admin_only=True)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="kill_switch.html",
            context=_page_context(user, nonce, "kill_switch"),
        )

    @app.get("/forgot-password", response_class=HTMLResponse)
    async def forgot_password_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="forgot_password.html",
            context={"nonce": nonce, "current_page": "forgot_password"},
        )

    @app.get("/reset-password", response_class=HTMLResponse)
    async def reset_password_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        token = request.query_params.get("token", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="reset_password.html",
            context={"nonce": nonce, "token": token, "current_page": "reset_password"},
        )

    @app.get("/change-password", response_class=HTMLResponse)
    async def change_password_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={"nonce": nonce, "current_page": "change_password"},
        )

    @app.get("/reports", response_class=HTMLResponse)
    async def reports_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="reports.html",
            context=_page_context(user, nonce, "reports"),
        )

    @app.get("/performance", response_class=HTMLResponse)
    async def performance_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="performance.html",
            context=_page_context(user, nonce, "performance"),
        )

    @app.get("/options-chain", response_class=HTMLResponse)
    async def options_chain_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="options_chain.html",
            context=_page_context(user, nonce, "options_chain"),
        )

    @app.get("/whats-new", response_class=HTMLResponse)
    async def whats_new_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_logs")
        if err:
            return err
        from core.enterprise_dashboard.routes.whats_new import get_latest_changelog_entry
        entry = get_latest_changelog_entry()
        return dashboard._templates.TemplateResponse(
            request=request,
            name="whats_new.html",
            context={**_page_context(user, nonce, "whats_new"), "entry": entry},
        )

    @app.get("/payoff-calculator", response_class=HTMLResponse)
    async def payoff_calculator_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="payoff_calculator.html",
            context=_page_context(user, nonce, "payoff_calculator"),
        )

    @app.get("/trade-journal", response_class=HTMLResponse)
    async def trade_journal_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="trade_journal.html",
            context=_page_context(user, nonce, "trade_journal"),
        )

    @app.get("/live-pnl", response_class=HTMLResponse)
    async def live_pnl_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="live_pnl.html",
            context=_page_context(user, nonce, "live_pnl"),
        )

    @app.get("/system-health", response_class=HTMLResponse)
    async def system_health_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="system_health.html",
            context=_page_context(user, nonce, "system_health"),
        )

    @app.get("/event-store", response_class=HTMLResponse)
    async def event_store_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_logs")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="event_store.html",
            context=_page_context(user, nonce, "event_store"),
        )

    @app.get("/ab-tester", response_class=HTMLResponse)
    async def ab_tester_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "deploy_models")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="ab_tester.html",
            context=_page_context(user, nonce, "ab_tester"),
        )

    @app.get("/governance", response_class=HTMLResponse)
    async def governance_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "toggle_strategies")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="governance.html",
            context=_page_context(user, nonce, "governance"),
        )

    @app.get("/capacity", response_class=HTMLResponse)
    async def capacity_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="capacity.html",
            context=_page_context(user, nonce, "capacity"),
        )

    @app.get("/metrics-trend", response_class=HTMLResponse)
    async def metrics_trend_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user = _resolve_session_user(request, dashboard)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="metrics_trend.html",
            context=_page_context(user, nonce, "metrics_trend"),
        )

    @app.get("/data-quality", response_class=HTMLResponse)
    async def data_quality_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="data_quality.html",
            context=_page_context(user, nonce, "data_quality"),
        )

    @app.get("/observability", response_class=HTMLResponse)
    async def observability_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_logs")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="observability.html",
            context=_page_context(user, nonce, "observability"),
        )

    @app.get("/intelligence", response_class=HTMLResponse)
    @app.get("/business-intelligence", response_class=HTMLResponse)
    async def intelligence_page(request: Request):
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="intelligence.html",
            context=_page_context(user, nonce, "intelligence"),
        )

    @app.get("/security", response_class=HTMLResponse)
    async def security_page(request: Request):  # type: ignore[no-untyped-def]
        """Admin-only page - its APIs (/api/auth/users, /api/auth/audit) always
        required admin, but the page itself only required login. A non-admin
        who navigated here got a page full of 403 error rows instead of a
        clean redirect. Gate the page the same way as its data."""
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_logs", admin_only=True)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="security.html",
            context=_page_context(user, nonce, "security"),
        )

    @app.get("/intelligence/presentation", response_class=HTMLResponse)
    async def presentation_page(request: Request):  # type: ignore[no-untyped-def]
        nonce = getattr(request.state, "nonce", "")
        user, err = _require_permission_page(request, dashboard, "view_state")
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="presentation.html",
            context=_page_context(user, nonce, "presentation"),
        )

    # SPA redirect pages — these redirect to /#page-{anchor}
    _redirect_pages = [
        ("/trading", "trading"),
        ("/signals", "signals"),
        ("/risk", "risk"),
        ("/broker", "broker"),
        ("/ml", "ml"),
        ("/health", "health"),
        ("/logs", "logs"),
        ("/system/state", "system-state"),
    ]
    for _p, _a in _redirect_pages:
        def _make_redirect(page_anchor: str):  # type: ignore[no-untyped-def]
            async def _redirect():  # type: ignore[no-untyped-def]
                return RedirectResponse(url=f"/#page-{page_anchor}")
            return _redirect
        app.get(_p, response_class=RedirectResponse, include_in_schema=False)(_make_redirect(_a))
