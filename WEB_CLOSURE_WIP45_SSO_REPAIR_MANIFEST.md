# OPB WEB CLOSURE WIP45 — SSO Semantic Repair Manifest

Targets reviewed: 7
Safely repaired: 0
Manual/unchanged: 7

## Safely repaired

## Manual / unchanged
- `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",` — not an exact application-owned base-url concatenation
- `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),` — not an exact application-owned base-url concatenation
- `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")` — not an exact application-owned base-url concatenation
- `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,` — not an exact application-owned base-url concatenation
- `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,` — not an exact application-owned base-url concatenation
- `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")` — not an exact application-owned base-url concatenation
- `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri` — not an exact application-owned base-url concatenation