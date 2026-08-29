# OPB WEB CLOSURE WIP67 — Registration Direct-Call Review

## `/register` — `archive/unrelated_modules/realestate/rera_compliance.py:349`

- Direct lifecycle call signals: 0

## `/register` — `archive/unrelated_modules/realestate/webhooks.py:348`

- Direct lifecycle call signals: 0

## `/register` — `core/auth/routes.py:137`

- Direct lifecycle call signals: 11
  - `"""Register a new user (self-registration, defaults to viewer role).`
  - `role = "viewer"  # Self-registration always creates viewers`
  - `role=role,`
  - `# Save email & telegram_chat_id into UserPermissionManager`
  - `perm_mgr = UserPermissionManager.get_instance()`
  - `perm_mgr.update_user_permissions(username, update_data, admin_username="self-register")`
  - `_log.warning("[AUTH] Failed to save user signal permissions on register: %s", e)`
  - `notification_result = notify_new_registration(`
  - `role=role,`
  - `"message": "Account created successfully with viewer role and is pending administrator authorization.",`
  - `"notification": notification_result,`

## `/users` — `core/auth/routes.py:422`

- Direct lifecycle call signals: 14
  - `role = str(body.get("role", "viewer")).strip().lower()`
  - `valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}`
  - `if role not in valid_roles:`
  - `raise HTTPException(status_code=400, detail=f"Unsupported role: {role}")`
  - `if not is_super_admin_identity(admin.username, admin.role) and role != "viewer":`
  - `raise HTTPException(status_code=403, detail="Only Super Admin can create accounts with elevated roles")`
  - `role=role,`
  - `perm_mgr = UserPermissionManager.get_instance()`
  - `"role": role,`
  - `perm_mgr.update_user_permissions(username, create_data, admin_username=admin.username)`
  - `_log.warning("[AUTH] Failed to save user signal permissions on admin create user: %s", e)`
  - `notification_result = notify_new_registration(`
  - `role=role,`
  - `result["notification"] = notification_result`

## `/users/{username}/role` — `core/auth/routes.py:483`

- Direct lifecycle call signals: 16
  - `@router.put("/users/{username}/role")`
  - `async def update_user_role(`
  - `admin: AuthUser = Depends(manage_permissions),`
  - `"""Update a user's role. Admin only."""`
  - `new_role = str(body.get("role", "")).lower()`
  - `# Only the root role may grant/revoke Super Admin. This prevents an`
  - `# ordinary Admin from escalating another account to the root role.`
  - `if new_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
  - `raise HTTPException(status_code=403, detail="Only Super Admin can assign Super Admin role")`
  - `if str(target.role).lower() == "super_admin" and new_role != "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
  - `if str(target.role).lower() == "super_admin" and new_role != "super_admin":`
  - `roots = [u for u in auth_handler.list_users() if str(u.get("role", "")).lower() == "super_admin" and not u.get("disabled")]`
  - `result = auth_handler.update_user_role(username, new_role, admin.username)`
  - `raise HTTPException(status_code=400, detail=result.get("error", "Role update failed"))`
  - `UserPermissionManager.get_instance().update_user_permissions(username, {"role": new_role}, admin_username=admin.username)`
  - `_log.warning("[AUTH] Failed to synchronize role metadata for %s: %s", username, sync_ex)`

## `/users/{username}/reset-password` — `core/auth/routes.py:519`

- Direct lifecycle call signals: 0

## `/users/{username}/disable` — `core/auth/routes.py:536`

- Direct lifecycle call signals: 0

## `/users/{username}/enable` — `core/auth/routes.py:548`

- Direct lifecycle call signals: 0

## `/users/{username}/permissions` — `core/auth/routes.py:661`

- Direct lifecycle call signals: 34
  - `@router.post("/users/{username}/permissions")`
  - `async def update_user_permissions(`
  - `admin: AuthUser = Depends(manage_permissions),`
  - `"""Super Admin update of user signal permissions, category subscriptions, quotas, and channels."""`
  - `target_role = str(target_user.role or "viewer").lower()`
  - `admin_role = admin.role.lower()`
  - `requested_role = str(body.get("role", target_role) or target_role).lower()`
  - `valid_roles = {"super_admin", "admin", "operator", "viewer", "observer", "developer"}`
  - `if requested_role not in valid_roles:`
  - `raise HTTPException(status_code=400, detail=f"Unsupported role: {requested_role}")`
  - `if requested_role != target_role and not is_super_admin_identity(admin.username, admin.role):`
  - `raise HTTPException(status_code=403, detail="Only Super Admin can change user roles")`
  - `if target_role == "super_admin" and not is_super_admin_identity(admin.username, admin.role):`
  - `raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")`
  - `# does not possess. This makes the permission UI an actual security`
  - `requested_allowed = {str(v).lower() for v in (body.get("allowed_permissions") or [])}`
  - `requested_denied = {str(v).lower() for v in (body.get("denied_permissions") or [])}`
  - `if not is_super_admin_identity(admin.username, admin.role):`
  - `from core.auth.permissions import get_role_permissions`
  - `own = {p.value for p in get_role_permissions(admin_role)}`
  - `raise HTTPException(status_code=403, detail="Admin cannot grant permissions beyond their own role")`
  - `if target_role == "super_admin":`
  - `raise HTTPException(status_code=403, detail="Only Super Admin can modify Super Admin permissions")`
  - `if requested_role != target_role:`
  - `role_result = auth_handler.update_user_role(username, requested_role, admin.username)`
  - `if not role_result.get("success"):`
  - `raise HTTPException(status_code=400, detail=role_result.get("error", "Role update failed"))`
  - `target_role = requested_role`
  - `mgr = UserPermissionManager.get_instance()`
  - `ok, msg, updated = mgr.update_user_permissions(username, {**body, "role": target_role}, admin_username=admin.username)`
  - `_log.info("[ADMIN_SYNC] Synchronized admin user permissions to system config: %s", list(cfg_updates.keys()))`
  - `auth_handler._audit_log(`
  - `"user_permissions_updated", admin.username, "",`
  - `return {"success": True, "message": msg, "permissions": updated}`

## `/users/{username}/toggle-signals` — `core/auth/routes.py:741`

- Direct lifecycle call signals: 3
  - `admin: AuthUser = Depends(manage_permissions),`
  - `mgr = UserPermissionManager.get_instance()`
  - `auth_handler._audit_log(`

## `/users/{username}/revoke-sessions` — `core/auth/routes.py:831`

- Direct lifecycle call signals: 2
  - `auth_handler._audit_log(`
  - `# ── Audit log (admin) ─────────────────────────────────────────────────────`
