"""
HTML page route registration for the Enterprise Dashboard.

Handles: /, /login, /register, /admin/users, /admin/config,
/admin/kill-switch, /change-password, and SPA redirect pages.
"""

from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse

_log = logging.getLogger(__name__)


def register_page_routes(app, dashboard, _require_admin_page):
    """Register all HTML page routes on the FastAPI app.

    Args:
        app: FastAPI application instance.
        dashboard: EnterpriseDashboard instance.
        _require_admin_page: Callable (request) -> (user, error_response)
            used to check admin auth for admin-only HTML pages.
    """

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        session_token = request.cookies.get("opb_session", "")
        user = None
        if session_token:
            token = dashboard._auth.verify_session(session_token)
            if token:
                user = dashboard._auth.get_user_by_id(token.user_id)
        if user is None:
            return RedirectResponse(url="/login")
        return dashboard._templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={"user": user.to_dict(), "nonce": nonce},
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        return dashboard._templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"nonce": nonce},
        )

    @app.get("/register", response_class=HTMLResponse)
    async def register_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        return dashboard._templates.TemplateResponse(
            request=request,
            name="register.html",
            context={"nonce": nonce},
        )

    @app.get("/admin/users", response_class=HTMLResponse)
    async def admin_users_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        user, err = _require_admin_page(request)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_users.html",
            context={"user": user.to_dict(), "nonce": nonce},
        )

    @app.get("/admin/config", response_class=HTMLResponse)
    async def admin_config_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        user, err = _require_admin_page(request)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="admin_config.html",
            context={"user": user.to_dict(), "nonce": nonce},
        )

    @app.get("/admin/kill-switch", response_class=HTMLResponse)
    async def kill_switch_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        user, err = _require_admin_page(request)
        if err:
            return err
        return dashboard._templates.TemplateResponse(
            request=request,
            name="kill_switch.html",
            context={"user": user.to_dict(), "nonce": nonce},
        )

    @app.get("/change-password", response_class=HTMLResponse)
    async def change_password_page(request: Request):
        nonce = getattr(request.state, 'nonce', '')
        return dashboard._templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context={"nonce": nonce},
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
        def _make_redirect(page_anchor: str):
            async def _redirect():
                return RedirectResponse(url=f"/#page-{page_anchor}")
            return _redirect
        app.get(_p, response_class=RedirectResponse, include_in_schema=False)(_make_redirect(_a))
