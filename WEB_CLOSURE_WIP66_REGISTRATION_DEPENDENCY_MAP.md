# OPB WEB CLOSURE WIP66 — Registration Dependency Map

Concrete registration route neighborhoods: 11

## `/register` — `archive/unrelated_modules/realestate/rera_compliance.py:349`
```python
    @router.post("/register")
    async def register_builder(
        rera_number: str = Query(...),
        builder_name: str = Query(...),
        project_name: str = Query(...),
        project_address: str = Query(""),
    ):
        """Register a builder/project with RERA number."""
        try:
            result = engine.register_builder(rera_number, builder_name, project_name, project_address)
            return {"success": True, "registration": result.to_dict()}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.get("/validate-format")
    async def validate_rera_format(rera_number: str = Query(...)):
        """Validate the format of a RERA number without verification."""
        parsed = RERAComplianceEngine.validate_format(rera_number)
        if not parsed:
            raise HTTPException(status_code=400, detail="Invalid RERA number format")
        return {"success": True, "valid": True, "parsed": parsed}

    @router.get("/check")
    async def check_compliance(property_id: str = Query("", description="Property ID to check")):
        """Check RERA compliance for a property."""
        # Try to get property if property_service is wired
        from realestate.application.services import create_default_services
        svc = create_default_services()
        ps = svc["property_service"]
        prop = ps.get_property(property_id) if property_id else None
        if property_id and not prop:
            raise HTTPException(status_code=404, detail="Property not found")
        result = engine.check_property_compliance(prop) if prop else {"status": "no_property", "score": 0, "checks": {}, "recommendations": ["No property provided"]}
        return {"success": True, "compliance": result}

    @router.get("/stats")
    async def compliance_stats():
        """Get RERA compliance statistics."""
        return {"success": True, "stats": engine.get_compliance_stats()}

    @router.get("/registrations")
    async def list_registrations(state: str = Query("", description="Filter by state code (e.g., MH, KA)")):
        """List all RERA registrations, optionally filtered by state."""
        return {"success": True, "registrations": engine.get_registrations(state or None)}

    return router


# ╀═════════════════════════════════════════════════════════════════════════════
# HTML Page Router
# ═══════════════════════════════════════════════════════════════════════════════

def create_rera_page_router() -> APIRouter:
    """Create router for the RERA compliance dashboard page."""
    router = APIRouter(tags=["Real Estate Pages"])
    templates = _get_templates()

    @router.get("/realestate/rera", response_class=HTMLResponse)
    async def rera_dashboard(request: Request):
        """RERA compliance dashboard page."""
        return templates.TemplateResponse(
            request=request,
            name="rera_dashboard.html",
            context={},
        )

    return router
```

## `/register` — `archive/unrelated_modules/realestate/webhooks.py:348`
```python
    @router.post("/register")
    async def register_webhook(
        url: str = Query(..., description="HTTPS endpoint URL"),
        events: str = Query(..., description="Comma-separated event types"),
        description: str = Query(""),
    ):
        """Register a new webhook endpoint."""
        event_list = [e.strip() for e in events.split(",") if e.strip()]
        endpoint = eng.register_endpoint(url, event_list, description=description)
        return {"success": True, "endpoint": endpoint.to_dict(), "secret": endpoint.secret}

    @router.delete("/{endpoint_id}")
    async def unregister_webhook(endpoint_id: str):
        """Remove a webhook endpoint."""
        if not eng.unregister_endpoint(endpoint_id):
            raise HTTPException(status_code=404, detail="Endpoint not found")
        return {"success": True}

    @router.get("/endpoints")
    async def list_endpoints():
        """List all registered webhook endpoints."""
        return {"endpoints": [ep.to_dict() for ep in eng.list_endpoints()]}

    @router.post("/test/{event_type}")
    async def test_dispatch(
        event_type: str,
        payload: str = Query("{}", description="JSON payload to test with"),
    ):
        """Test-dispatch an event to all matching endpoints."""
        import json
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"test": True}
        deliveries = eng.dispatch(event_type, data)
        return {
            "success": True,
            "event": event_type,
            "deliveries": [d.to_dict() for d in deliveries],
            "matched_endpoints": len(deliveries),
        }

    @router.get("/deliveries")
    async def delivery_history(limit: int = Query(50, ge=1, le=200)):
        """Get recent webhook deliveries."""
        deliveries = eng.get_delivery_history(limit)
        return {"deliveries": [d.to_dict() for d in deliveries]}

    @router.get("/deliveries/failed")
    async def failed_deliveries(limit: int = Query(20, ge=1, le=100)):
        """Get failed webhook deliveries."""
        deliveries = eng.get_failed_deliveries(limit)
        return {"deliveries": [d.to_dict() for d in deliveries]}

    @router.get("/stats")
    async def webhook_stats():
        """Get webhook engine statistics."""
        return eng.get_stats()

    return router
```

## `/register` — `core/auth/routes.py:137`
```python
    @router.post("/register")
    async def register(
        request: Request,
    ) -> dict:
        """Register a new user (self-registration, defaults to viewer role).

        Rate limited to 5 registrations per IP per 15 minutes.

        JSON body:
            username: Unique username.
            password: Password (min 8 chars).
            display_name: Optional display name.

        Returns:
            Dict with success status and user info.

        """
        # Apply rate limiting (5 registrations per IP per 15 minutes)
        client_ip = get_client_ip(request)
        result = _register_rate_limiter.is_allowed(f"register:{client_ip}")
        if result == LimitResult.DENIED:
            _log.warning("[AUTH] Register rate limited for IP: %s", client_ip)
            raise HTTPException(
                status_code=429,
                detail="Too many registration attempts. Please try again later.",
            )

        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        display_name = str(body.get("display_name", ""))
        email = str(body.get("email", "")).strip()
        telegram_chat_id = str(body.get("telegram_chat_id", "")).strip()
        role = "viewer"  # Self-registration always creates viewers

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        if len(password) < 8:
            raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

        result = auth_handler.create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            created_by="self-register",
            email=email,
            telegram_chat_id=telegram_chat_id,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Registration failed"))

        # Save email & telegram_chat_id into UserPermissionManager
        try:
            perm_mgr = UserPermissionManager.get_instance()
            update_data: dict[str, Any] = {}
            if email:
                update_data["email"] = email
                update_data["email_enabled"] = True
            if telegram_chat_id:
                update_data["telegram_chat_id"] = telegram_chat_id
                update_data["telegram_enabled"] = True
            if update_data:
                perm_mgr.update_user_permissions(username, update_data, admin_username="self-register")
        except Exception as e:
            _log.warning("[AUTH] Failed to save user signal permissions on register: %s", e)

        notification_result = notify_new_registration(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            created_by="self-register",
        )
        return {
            "success": True,
            "message": "Account created successfully with viewer role and is pending administrator authorization.",
            "notification": notification_result,
        }

    # ── Login ─────────────────────────────────────────────────────────────────

    @router.get("/login")
    async def login_get() -> Response:
        """Redirect GET /api/auth/login directly to the HTML login page."""
        return RedirectResponse(url="/login", status_code=307)

    @router.post("/login")
    async def login(
        request: Request,
        response: Response,
    ) -> dict:
        """Authenticate and create a session."""
        try:
            body = await request.json()
            username = str(body.get("username", "")).strip()
            password = str(body.get("password", "")).strip()
        except Exception:
            try:
                form = await request.form()
                username = str(form.get("username", "")).strip()
                password = str(form.get("password", "")).strip()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid request body")

        ip = get_client_ip(request)
        ua = request.headers.get("user-agent", "")

        if not username or not password:
```

## `/users` — `core/auth/routes.py:422`
```python
    @router.post("/users")
    async def create_user(
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Create a new user. Admin only."""
        body = await request.json()
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        role = str(body.get("role", "viewer")).strip().lower()
        display_name = str(body.get("display_name", ""))
        email = str(body.get("email", "")).strip()
        telegram_chat_id = str(body.get("telegram_chat_id", "")).strip()

        if not username or not password:
            raise HTTPException(status_code=400, detail="Username and password required")

        valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}
        if role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")
        if not is_super_admin_identity(admin.username, admin.role) and role != "viewer":
            raise HTTPException(status_code=403, detail="Only Super Admin can create accounts with elevated roles")

        result = auth_handler.create_user(
            username=username,
            password=password,
            role=role,
            display_name=display_name,
            created_by=admin.username,
            email=email,
            telegram_chat_id=telegram_chat_id,
        )
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "User creation failed"))

        try:
            perm_mgr = UserPermissionManager.get_instance()
            create_data: dict[str, Any] = {
                "display_name": display_name or username,
                "role": role,
            }
            if email:
                create_data["email"] = email
                create_data["email_enabled"] = True
            if telegram_chat_id:
                create_data["telegram_chat_id"] = telegram_chat_id
                create_data["telegram_enabled"] = True
            perm_mgr.update_user_permissions(username, create_data, admin_username=admin.username)
        except Exception as e:
            _log.warning("[AUTH] Failed to save user signal permissions on admin create user: %s", e)

        notification_result = notify_new_registration(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            created_by=admin.username,
        )
        result["notification"] = notification_result
        return result

    @router.put("/users/{username}/role")
    async def update_user_role(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Update a user's role. Admin only."""
        body = await request.json()
        new_role = str(body.get("role", "")).lower()
        target = auth_handler.get_user(username)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Only the root role may grant/revoke Super Admin. This prevents an
        # ordinary Admin from escalating another account to the root role.
        if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can assign Super Admin role")
        if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can modify a Super Admin")

        # Never remove the final active Super Admin.
        if str(target.role).lower() == "super_admin" and new_role != "super_admin":
            roots = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() == "super_admin" and not u.get("disabled")]
            if len(roots) <= 1:
                raise HTTPException(status_code=400, detail="The last active Super Admin cannot be demoted")

        result = auth_handler.update_user_role(username, new_role, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Role update failed"))
        try:
            UserPermissionManager.get_instance().update_user_permissions(username, {"role": new_role}, admin_username=admin.username)
        except Exception as sync_ex:
            _log.warning("[AUTH] Failed to synchronize role metadata for %s: %s", username, sync_ex)

        return result

    @router.post("/users/{username}/reset-password")
    async def reset_user_password(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Admin-forced password reset. Admin only."""
        body = await request.json()
        new_password = str(body.get("new_password", ""))

        result = auth_handler.admin_reset_password(username, new_password, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed"))
```

## `/users/{username}/role` — `core/auth/routes.py:483`
```python
    @router.put("/users/{username}/role")
    async def update_user_role(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Update a user's role. Admin only."""
        body = await request.json()
        new_role = str(body.get("role", "")).lower()
        target = auth_handler.get_user(username)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")

        # Only the root role may grant/revoke Super Admin. This prevents an
        # ordinary Admin from escalating another account to the root role.
        if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can assign Super Admin role")
        if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can modify a Super Admin")

        # Never remove the final active Super Admin.
        if str(target.role).lower() == "super_admin" and new_role != "super_admin":
            roots = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() == "super_admin" and not u.get("disabled")]
            if len(roots) <= 1:
                raise HTTPException(status_code=400, detail="The last active Super Admin cannot be demoted")

        result = auth_handler.update_user_role(username, new_role, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Role update failed"))
        try:
            UserPermissionManager.get_instance().update_user_permissions(username, {"role": new_role}, admin_username=admin.username)
        except Exception as sync_ex:
            _log.warning("[AUTH] Failed to synchronize role metadata for %s: %s", username, sync_ex)

        return result

    @router.post("/users/{username}/reset-password")
    async def reset_user_password(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Admin-forced password reset. Admin only."""
        body = await request.json()
        new_password = str(body.get("new_password", ""))

        result = auth_handler.admin_reset_password(username, new_password, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed"))

        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/disable")
    async def disable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Disable a user account. Admin only."""
        result = auth_handler.disable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Disable failed"))
        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/enable")
    async def enable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Delete a user with safety guards for the current/last administrator."""
        target = username.strip().lower()
        if target == admin.username.strip().lower():
            raise HTTPException(status_code=400, detail="You cannot delete your own active administrator account")

        # Never allow the control plane to remove the final administrator.
        admins = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() in {"admin", "super_admin"} and not u.get("disabled")]
        target_user = auth_handler.get_user(target)
        if target_user and str(target_user.role).lower() in {"admin", "super_admin"} and len(admins) <= 1:
            raise HTTPException(status_code=400, detail="The last active administrator cannot be deleted")

        result = auth_handler.delete_user(target, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        UserPermissionManager.get_instance().delete_user_permissions(target)
        return result

    # ── Super Admin User Signal Permissions & Quotas ──────────────────────────

    @router.get("/user-permissions")
    async def list_all_user_permissions(
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """List all users with full signal permissions, quotas, and categories."""
        mgr = UserPermissionManager.get_instance()
        auth_users = auth_handler.list_users()
        active_unames = {u["username"] for u in auth_users}
        mgr.prune_stale_users(active_unames)

```

## `/users/{username}/reset-password` — `core/auth/routes.py:519`
```python
    @router.post("/users/{username}/reset-password")
    async def reset_user_password(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Admin-forced password reset. Admin only."""
        body = await request.json()
        new_password = str(body.get("new_password", ""))

        result = auth_handler.admin_reset_password(username, new_password, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Password reset failed"))

        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/disable")
    async def disable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Disable a user account. Admin only."""
        result = auth_handler.disable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Disable failed"))
        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/enable")
    async def enable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Delete a user with safety guards for the current/last administrator."""
        target = username.strip().lower()
        if target == admin.username.strip().lower():
            raise HTTPException(status_code=400, detail="You cannot delete your own active administrator account")

        # Never allow the control plane to remove the final administrator.
        admins = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() in {"admin", "super_admin"} and not u.get("disabled")]
        target_user = auth_handler.get_user(target)
        if target_user and str(target_user.role).lower() in {"admin", "super_admin"} and len(admins) <= 1:
            raise HTTPException(status_code=400, detail="The last active administrator cannot be deleted")

        result = auth_handler.delete_user(target, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        UserPermissionManager.get_instance().delete_user_permissions(target)
        return result

    # ── Super Admin User Signal Permissions & Quotas ──────────────────────────

    @router.get("/user-permissions")
    async def list_all_user_permissions(
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """List all users with full signal permissions, quotas, and categories."""
        mgr = UserPermissionManager.get_instance()
        auth_users = auth_handler.list_users()
        active_unames = {u["username"] for u in auth_users}
        mgr.prune_stale_users(active_unames)

        for u in auth_users:
            uname = u["username"]
            perm = mgr.get_user_permissions(uname)
            u_email = u.get("email") or (u.get("metadata") or {}).get("email", "")
            u_tg = u.get("telegram_chat_id") or (u.get("metadata") or {}).get("telegram_chat_id", "")
            u_name = u.get("display_name") or (u.get("metadata") or {}).get("display_name", "")
            u_role = u.get("role", "viewer")

            if not perm:
                mgr.update_user_permissions(
                    uname,
                    {
                        "display_name": u_name or uname,
                        "role": u_role,
                        "is_active": not u.get("disabled", False),
                        "signals_enabled": True if u_role in {"admin", "super_admin"} else False,
                        "email": u_email or ("ai.auto.gaurav@gmail.com, adv.syj@gmail.com" if uname == "admin" else ""),
                        "email_enabled": True if uname == "admin" or bool(u_email) else False,
                        "telegram_chat_id": u_tg,
                        "telegram_enabled": bool(u_tg),
                    },
                    admin_username="system-sync",
                )

        all_perms = mgr.list_all_permissions()
        return {
            "success": True,
            "categories": ALL_CATEGORIES,
            "permissions": all_perms,
        }

    @router.get("/users/{username}/permissions")
    async def get_user_permissions(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
```

## `/users/{username}/disable` — `core/auth/routes.py:536`
```python
    @router.post("/users/{username}/disable")
    async def disable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Disable a user account. Admin only."""
        result = auth_handler.disable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Disable failed"))
        auth_handler.revoke_all_user_sessions(username)
        return result

    @router.post("/users/{username}/enable")
    async def enable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Delete a user with safety guards for the current/last administrator."""
        target = username.strip().lower()
        if target == admin.username.strip().lower():
            raise HTTPException(status_code=400, detail="You cannot delete your own active administrator account")

        # Never allow the control plane to remove the final administrator.
        admins = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() in {"admin", "super_admin"} and not u.get("disabled")]
        target_user = auth_handler.get_user(target)
        if target_user and str(target_user.role).lower() in {"admin", "super_admin"} and len(admins) <= 1:
            raise HTTPException(status_code=400, detail="The last active administrator cannot be deleted")

        result = auth_handler.delete_user(target, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        UserPermissionManager.get_instance().delete_user_permissions(target)
        return result

    # ── Super Admin User Signal Permissions & Quotas ──────────────────────────

    @router.get("/user-permissions")
    async def list_all_user_permissions(
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """List all users with full signal permissions, quotas, and categories."""
        mgr = UserPermissionManager.get_instance()
        auth_users = auth_handler.list_users()
        active_unames = {u["username"] for u in auth_users}
        mgr.prune_stale_users(active_unames)

        for u in auth_users:
            uname = u["username"]
            perm = mgr.get_user_permissions(uname)
            u_email = u.get("email") or (u.get("metadata") or {}).get("email", "")
            u_tg = u.get("telegram_chat_id") or (u.get("metadata") or {}).get("telegram_chat_id", "")
            u_name = u.get("display_name") or (u.get("metadata") or {}).get("display_name", "")
            u_role = u.get("role", "viewer")

            if not perm:
                mgr.update_user_permissions(
                    uname,
                    {
                        "display_name": u_name or uname,
                        "role": u_role,
                        "is_active": not u.get("disabled", False),
                        "signals_enabled": True if u_role in {"admin", "super_admin"} else False,
                        "email": u_email or ("ai.auto.gaurav@gmail.com, adv.syj@gmail.com" if uname == "admin" else ""),
                        "email_enabled": True if uname == "admin" or bool(u_email) else False,
                        "telegram_chat_id": u_tg,
                        "telegram_enabled": bool(u_tg),
                    },
                    admin_username="system-sync",
                )

        all_perms = mgr.list_all_permissions()
        return {
            "success": True,
            "categories": ALL_CATEGORIES,
            "permissions": all_perms,
        }

    @router.get("/users/{username}/permissions")
    async def get_user_permissions(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Get signal permissions and quota usage for a specific user."""
        mgr = UserPermissionManager.get_instance()
        u = auth_handler.get_user(username)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        u_meta = u.metadata or {}
        u_email = getattr(u, "email", None) or u_meta.get("email", "")
        u_tg = getattr(u, "telegram_chat_id", None) or u_meta.get("telegram_chat_id", "")
        u_name = u.display_name or u_meta.get("display_name", u.username)

        perm = mgr.get_user_permissions(username)
        if not perm:
            mgr.update_user_permissions(
                username,
                {
                    "display_name": u_name,
```

## `/users/{username}/enable` — `core/auth/routes.py:548`
```python
    @router.post("/users/{username}/enable")
    async def enable_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Enable a disabled user. Admin only."""
        result = auth_handler.enable_user(username, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Enable failed"))
        return result

    @router.delete("/users/{username}")
    async def delete_user(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Delete a user with safety guards for the current/last administrator."""
        target = username.strip().lower()
        if target == admin.username.strip().lower():
            raise HTTPException(status_code=400, detail="You cannot delete your own active administrator account")

        # Never allow the control plane to remove the final administrator.
        admins = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() in {"admin", "super_admin"} and not u.get("disabled")]
        target_user = auth_handler.get_user(target)
        if target_user and str(target_user.role).lower() in {"admin", "super_admin"} and len(admins) <= 1:
            raise HTTPException(status_code=400, detail="The last active administrator cannot be deleted")

        result = auth_handler.delete_user(target, admin.username)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Delete failed"))
        UserPermissionManager.get_instance().delete_user_permissions(target)
        return result

    # ── Super Admin User Signal Permissions & Quotas ──────────────────────────

    @router.get("/user-permissions")
    async def list_all_user_permissions(
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """List all users with full signal permissions, quotas, and categories."""
        mgr = UserPermissionManager.get_instance()
        auth_users = auth_handler.list_users()
        active_unames = {u["username"] for u in auth_users}
        mgr.prune_stale_users(active_unames)

        for u in auth_users:
            uname = u["username"]
            perm = mgr.get_user_permissions(uname)
            u_email = u.get("email") or (u.get("metadata") or {}).get("email", "")
            u_tg = u.get("telegram_chat_id") or (u.get("metadata") or {}).get("telegram_chat_id", "")
            u_name = u.get("display_name") or (u.get("metadata") or {}).get("display_name", "")
            u_role = u.get("role", "viewer")

            if not perm:
                mgr.update_user_permissions(
                    uname,
                    {
                        "display_name": u_name or uname,
                        "role": u_role,
                        "is_active": not u.get("disabled", False),
                        "signals_enabled": True if u_role in {"admin", "super_admin"} else False,
                        "email": u_email or ("ai.auto.gaurav@gmail.com, adv.syj@gmail.com" if uname == "admin" else ""),
                        "email_enabled": True if uname == "admin" or bool(u_email) else False,
                        "telegram_chat_id": u_tg,
                        "telegram_enabled": bool(u_tg),
                    },
                    admin_username="system-sync",
                )

        all_perms = mgr.list_all_permissions()
        return {
            "success": True,
            "categories": ALL_CATEGORIES,
            "permissions": all_perms,
        }

    @router.get("/users/{username}/permissions")
    async def get_user_permissions(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Get signal permissions and quota usage for a specific user."""
        mgr = UserPermissionManager.get_instance()
        u = auth_handler.get_user(username)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        u_meta = u.metadata or {}
        u_email = getattr(u, "email", None) or u_meta.get("email", "")
        u_tg = getattr(u, "telegram_chat_id", None) or u_meta.get("telegram_chat_id", "")
        u_name = u.display_name or u_meta.get("display_name", u.username)

        perm = mgr.get_user_permissions(username)
        if not perm:
            mgr.update_user_permissions(
                username,
                {
                    "display_name": u_name,
                    "role": u.role,
                    "is_active": not u.disabled,
                    "signals_enabled": True if u.role in {"admin", "super_admin"} else False,
                    "email": u_email or ("ai.auto.gaurav@gmail.com, adv.syj@gmail.com" if username == "admin" else ""),
                    "email_enabled": True if username == "admin" or bool(u_email) else False,
                    "telegram_chat_id": u_tg,
                    "telegram_enabled": bool(u_tg),
                },
                admin_username="system-sync",
            )
            perm = mgr.get_user_permissions(username)

```

## `/users/{username}/permissions` — `core/auth/routes.py:661`
```python
    @router.post("/users/{username}/permissions")
    async def update_user_permissions(
        username: str,
        request: Request,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """Super Admin update of user signal permissions, category subscriptions, quotas, and channels."""
        body = await request.json()
        target_user = auth_handler.get_user(username)
        if target_user is None:
            raise HTTPException(status_code=404, detail="User not found")

        target_role = str(target_user.role or "viewer").lower()
        admin_role = admin.role.lower()
        requested_role = str(body.get("role", target_role) or target_role).lower()
        valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}
        if requested_role not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Unsupported role: {requested_role}")
        if requested_role != target_role and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can change user roles")
        if target_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):
            raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")

        # Only Super Admin can grant capabilities the requesting administrator
        # does not possess. This makes the permission UI an actual security
        # boundary rather than a cosmetic menu control.
        requested_allowed = {str(v).lower() for v in (body.get("allowed_permissions") or [])}
        requested_denied = {str(v).lower() for v in (body.get("denied_permissions") or [])}
        if not is_super_admin_identity(admin.username, admin.role):
            from core.auth.permissions import get_role_permissions
            own = {p.value for p in get_role_permissions(admin_role)}
            if not requested_allowed.issubset(own):
                raise HTTPException(status_code=403, detail="Admin cannot grant permissions beyond their own role")
            if target_role == "super_admin":
                raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")

        if requested_role != target_role:
            role_result = auth_handler.update_user_role(username, requested_role, admin.username)
            if not role_result.get("success"):
                raise HTTPException(status_code=400, detail=role_result.get("error", "Role update failed"))
            target_role = requested_role

        mgr = UserPermissionManager.get_instance()
        ok, msg, updated = mgr.update_user_permissions(username, {**body, "role": target_role}, admin_username=admin.username)
        if ok:
            auth_handler.update_user_metadata(
                username,
                {
                    "email": body.get("email", ""),
                    "telegram_chat_id": body.get("telegram_chat_id", ""),
                },
                display_name=body.get("display_name"),
            )
            # Synchronize admin user changes across json/config.json and runtime config
            if username == "admin":
                try:
                    from core.config_manager import get_config_manager
                    cfg_mgr = get_config_manager()
                    cfg_updates = {}
                    if "email" in body:
                        cfg_updates["EMAIL_TO"] = str(body["email"])
                        if "email_enabled" in body:
                            cfg_updates["EMAIL_ENABLED"] = bool(body["email_enabled"])
                    if "telegram_chat_id" in body:
                        cfg_updates["CHAT_ID"] = str(body["telegram_chat_id"])
                    if cfg_updates:
                        cfg_mgr.update(cfg_updates)
                        _log.info("[ADMIN_SYNC] Synchronized admin user permissions to system config: %s", list(cfg_updates.keys()))
                except Exception as sync_ex:
                    _log.warning("[ADMIN_SYNC] Could not sync admin user to system config: %s", sync_ex)

        auth_handler._audit_log(
            "user_permissions_updated", admin.username, "",
            {"target_user": username, "changed_keys": list(body.keys()), "ok": ok},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "permissions": updated}

    @router.post("/users/{username}/toggle-signals")
    async def toggle_user_signals(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """One-click toggle of master signal delivery for a user."""
        mgr = UserPermissionManager.get_instance()
        ok, msg, enabled = mgr.toggle_user_signals(username, admin_username=admin.username)
        auth_handler._audit_log(
            "user_signals_toggled", admin.username, "",
            {"target_user": username, "signals_enabled": enabled, "ok": ok},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "signals_enabled": enabled}

    # ── Signal Intelligence, Category Accuracy & User Delivery History ────────

    @router.get("/signals/analytics")
    async def get_admin_signal_analytics(
        timeframe: str = "all",
        category: str = "all",
        tier: str = "all",
        status: str = "all",
        admin: AuthUser = Depends(view_signal_analytics),
    ) -> dict:
        """Signal Intelligence / Accuracy / Category Breakdown for authorized viewers."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
```

## `/users/{username}/toggle-signals` — `core/auth/routes.py:741`
```python
    @router.post("/users/{username}/toggle-signals")
    async def toggle_user_signals(
        username: str,
        admin: AuthUser = Depends(manage_permissions),
    ) -> dict:
        """One-click toggle of master signal delivery for a user."""
        mgr = UserPermissionManager.get_instance()
        ok, msg, enabled = mgr.toggle_user_signals(username, admin_username=admin.username)
        auth_handler._audit_log(
            "user_signals_toggled", admin.username, "",
            {"target_user": username, "signals_enabled": enabled, "ok": ok},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"success": True, "message": msg, "signals_enabled": enabled}

    # ── Signal Intelligence, Category Accuracy & User Delivery History ────────

    @router.get("/signals/analytics")
    async def get_admin_signal_analytics(
        timeframe: str = "all",
        category: str = "all",
        tier: str = "all",
        status: str = "all",
        admin: AuthUser = Depends(view_signal_analytics),
    ) -> dict:
        """Signal Intelligence / Accuracy / Category Breakdown for authorized viewers."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        return tracker.get_admin_signal_analytics(timeframe=timeframe, category=category, tier=tier, status=status)

    @router.get("/signals/my-history")
    async def get_my_signal_history(
        year: str = "all",
        month: str = "all",
        week: str = "all",
        day: str = "all",
        category: str = "all",
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Personalized received signal feed for the authenticated user with time filters."""
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        return tracker.get_user_received_signals(
            username=current_user.username,
            year=year,
            month=month,
            week=week,
            day=day,
            category=category,
        )

    @router.post("/signals/{signal_id}/mark-order-placed")
    async def mark_signal_order_placed(
        signal_id: str,
        request: Request,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Admin marks/unmarks "I actually placed an order off this signal"
        for historical record-keeping (templates/enterprise/admin_signals.html's
        Order Placed? column) - independent of the automatic price-based
        outcome grading in SignalTracker.update_active_signal_outcomes()."""
        body = await request.json()
        placed = bool(body.get("placed", True))
        from core.signals.signal_tracker import SignalTracker
        tracker = SignalTracker.get_instance()
        ok = tracker.mark_order_placed(signal_id, placed, admin.username)
        auth_handler._audit_log(
            "signal_order_placed_marked", admin.username, "",
            {"signal_id": signal_id, "placed": placed},
            success=ok,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="Signal not found")
        return {"success": True, "signal_id": signal_id, "placed": placed}

    # ── Session management (admin) ────────────────────────────────────────────

    @router.get("/users/{username}/sessions")
    async def get_user_sessions(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> list:
        """Get sessions for a user. Admin only."""
        user = auth_handler.get_user(username)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return auth_handler.get_user_sessions(user.user_id)

    @router.post("/users/{username}/revoke-sessions")
    async def revoke_user_sessions(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Revoke all sessions for a user. Admin only."""
        count = auth_handler.revoke_all_user_sessions(username)
        auth_handler._audit_log(
            "user_sessions_revoked", admin.username, "",
            {"target_user": username, "sessions_revoked": count},
        )
        return {"success": True, "sessions_revoked": count}

    # ── Audit log (admin) ─────────────────────────────────────────────────────

    @router.get("/audit")
    async def get_audit_log(
        limit: int = 100,
        event_type: str | None = None,
        admin: AuthUser = Depends(manage_users),
```

## `/users/{username}/revoke-sessions` — `core/auth/routes.py:831`
```python
    @router.post("/users/{username}/revoke-sessions")
    async def revoke_user_sessions(
        username: str,
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Revoke all sessions for a user. Admin only."""
        count = auth_handler.revoke_all_user_sessions(username)
        auth_handler._audit_log(
            "user_sessions_revoked", admin.username, "",
            {"target_user": username, "sessions_revoked": count},
        )
        return {"success": True, "sessions_revoked": count}

    # ── Audit log (admin) ─────────────────────────────────────────────────────

    @router.get("/audit")
    async def get_audit_log(
        limit: int = 100,
        event_type: str | None = None,
        admin: AuthUser = Depends(manage_users),
    ) -> list[dict[str, Any]]:
        """Get auth audit log. Admin only."""
        from datetime import datetime, timedelta, timezone
        raw_logs = auth_handler.get_audit_log(limit=limit, event_type=event_type)
        ist = timezone(timedelta(hours=5, minutes=30))
        results = []
        for entry in raw_logs:
            item = dict(entry)
            ts = item.get("timestamp")
            if isinstance(ts, (int, float)):
                try:
                    dt = datetime.fromtimestamp(ts, tz=ist)
                    item["timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                    item["timestamp"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    item["timestamp_str"] = str(ts)
                    item["timestamp"] = str(ts)
            else:
                item["timestamp_str"] = str(ts or "-")
            results.append(item)
        return results

    # ── Auth stats ────────────────────────────────────────────────────────────

    @router.get("/stats")
    async def auth_stats(
        admin: AuthUser = Depends(manage_users),
    ) -> dict:
        """Get auth system statistics."""
        return auth_handler.get_stats()

    # ── MFA Routes ────────────────────────────────────────────────────────────

    @router.post("/mfa/setup")
    async def mfa_setup(
        current_user: AuthUser = Depends(auth_deps.require_auth),
    ) -> dict:
        """Generate a new MFA secret and provisioning URI for the current user.

        This does NOT enable MFA yet. The user must verify a token first
        via POST /api/auth/mfa/verify.

        Returns:
            Dict with ``secret``, ``provisioning_uri``, and ``recovery_codes``.
            The recovery codes are shown only once — the user must save them.

        """
        secret = generate_mfa_secret()
        provisioning_uri = get_mfa_provisioning_uri(
            username=current_user.username,
            secret=secret,
            issuer="OPB Enterprise",
        )
        recovery_codes = generate_recovery_codes()

        # Save secret (but don't enable MFA yet)
        auth_handler.set_mfa_secret(current_user.username, secret)

        # Return hashed recovery codes for storage
        hashed_codes = [hash_recovery_code(c) for c in recovery_codes]
        auth_handler.update_mfa_recovery_codes(current_user.username, hashed_codes)

        return {
            "success": True,
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "recovery_codes": recovery_codes,
            "note": "Save these recovery codes securely. They will not be shown again.",
        }

    @router.post("/mfa/verify")
    async def mfa_verify(
        request: Request,
        current_user: AuthUser = Depends(auth_deps.require_auth),
        current_token: AuthToken = Depends(_get_token_from_state),
    ) -> dict:
        """Verify a TOTP token to enable MFA.

        JSON body:
            token: The 6-digit TOTP code from the authenticator app.

        On success, MFA is enabled for the user.
        """
        body = await request.json()
        token = str(body.get("token", "")).strip()

        if not token:
            raise HTTPException(status_code=400, detail="Token required")

        secret = auth_handler.get_mfa_secret(current_user.username)
```
