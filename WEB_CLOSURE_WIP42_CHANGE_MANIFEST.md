# OPB WEB CLOSURE WIP42 — Surgical URL Repair Change Manifest

Targets received: 7
Changed: 0
Refused/unsafe: 7

## Changed

## Refused / requires manual review
- Target 1 `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",`
- Target 2 `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),`
- Target 3 `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- Target 4 `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,`
- Target 5 `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,`
- Target 6 `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")`
- Target 7 `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri`