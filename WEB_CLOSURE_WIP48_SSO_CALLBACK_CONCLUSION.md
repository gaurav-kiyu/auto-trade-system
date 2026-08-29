# OPB WEB CLOSURE WIP48 — SSO Callback Conclusion

## Concrete URL-construction scan

- `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",`
- `core/auth/sso.py:23` — `redirect_url = sso.get_authorization_url()`
- `core/auth/sso.py:24` — `return RedirectResponse(url=redirect_url)`
- `core/auth/sso.py:26` — `@router.get("/sso/callback")`
- `core/auth/sso.py:27` — `async def sso_callback(code: str, state: str):`
- `core/auth/sso.py:28` — `user = await sso.handle_callback(code, state)`
- `core/auth/sso.py:77` — `redirect_uri: Callback URL after authentication.`
- `core/auth/sso.py:89` — `redirect_uri: str = ""`
- `core/auth/sso.py:154` — `- sso_redirect_uri (str)`
- `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),`
- `core/auth/sso.py:184` — `def get_authorization_url(self, state: str | None = None) -> str | None:`
- `core/auth/sso.py:198` — `if not self._config.client_id or not self._config.redirect_uri:`
- `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,`
- `core/auth/sso.py:215` — `uri, _ = session.create_authorization_url(`
- `core/auth/sso.py:227` — `async def handle_callback(self, code: str, state: str) -> SSOUser | None:`
- `core/auth/sso.py:228` — `"""Handle the OAuth2 callback, exchanging the code for tokens and user info.`
- `core/auth/sso.py:232` — `state: The OAuth2 state parameter (must match get_authorization_url).`
- `core/auth/sso.py:249` — `_log.warning("[SSO] authlib not installed -- cannot handle callback")`
- `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,`
- `core/auth/sso.py:292` — `_log.error("[SSO] Callback handling failed: %s", exc)`
- `core/auth/sso.py:341` — `sso_user: The SSO user returned by handle_callback().`
- `core/auth/sso.py:430` — `if not self._config.redirect_uri:`
- `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")`
- `core/auth/routes.py:12` — `from fastapi.responses import RedirectResponse`
- `core/auth/routes.py:94` — `secure = request.url.scheme == "https"`
- `core/auth/routes.py:109` — `secure = request.url.scheme == "https"`
- `core/auth/routes.py:222` — `"""Redirect GET /api/auth/login directly to the HTML login page."""`
- `core/auth/routes.py:223` — `return RedirectResponse(url="/login", status_code=307)`
- `core/auth/routes.py:265` — `redirect_resp = RedirectResponse(url=target_url, status_code=303)`
- `core/auth/routes.py:266` — `_set_session_cookie(redirect_resp, token.token, auth_handler._token_ttl, request=request)`
- `core/auth/routes.py:267` — `_set_csrf_cookie(redirect_resp, csrf_token, request=request)`
- `core/auth/routes.py:268` — `return redirect_resp  # type: ignore[return-value]`
- `core/auth/routes.py:288` — `"""Logout, revoke session, and redirect browser requests to /login."""`
- `core/auth/routes.py:299` — `redirect_resp = RedirectResponse(url="/login", status_code=303)`
- `core/auth/routes.py:300` — `_clear_session_cookie(redirect_resp)`
- `core/auth/routes.py:301` — `_clear_csrf_cookie(redirect_resp)`
- `core/auth/routes.py:302` — `return redirect_resp`
- `core/auth/routes.py:1073` — `Dict with ``authorization_url`` to redirect the user to.`
- `core/auth/routes.py:1081` — `sso_redirect_uri = build_action_url(`
- `core/auth/routes.py:1082` — `"/api/auth/sso/callback",`
- `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri`
- `core/auth/routes.py:1088` — `# Keep the OAuth callback on the canonical public origin configured for`
- `core/auth/routes.py:1089` — `# this deployment. Do not derive it from request.base_url because that`
- `core/auth/routes.py:1091` — `# would make the provider redirect the user to an unusable URL.`
- `core/auth/routes.py:1093` — `sso._config.redirect_uri = build_action_url(`
- `core/auth/routes.py:1094` — `"/api/auth/sso/callback",`
- `core/auth/routes.py:1098` — `url = sso.get_authorization_url()`
- `core/auth/routes.py:1109` — `return {"success": True, "authorization_url": url}`
- `core/auth/routes.py:1111` — `@router.get("/sso/callback")`
- `core/auth/routes.py:1112` — `async def sso_callback(`
- `core/auth/routes.py:1117` — `"""Handle SSO OAuth2 callback.`
- `core/auth/routes.py:1137` — `sso_user = await sso.handle_callback(code, state)`

## Finding

The SSO module contains provider-side authorization/token configuration and application callback handling.
The application callback route must remain on the canonical public URL boundary.

Canonical callback observed in routes: `False`

No source mutation was made in this pass.

## Required production behavior
Deployment URL → Admin URL Override → Effective URL → canonical resolver → OPB-owned callback URL.
Identity-provider endpoints remain provider configuration.