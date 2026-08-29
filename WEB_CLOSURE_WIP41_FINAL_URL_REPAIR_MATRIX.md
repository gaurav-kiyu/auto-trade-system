# OPB WEB CLOSURE WIP41 — Final URL Repair Matrix

WIP40 targets re-inspected: 7
Direct/external repair candidates: 7
Already centralized: 0
Ambiguous: 0

## Repair candidates
- **Target 1** `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",` — `EXTERNAL_LINK_CANDIDATE`
- **Target 2** `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),` — `EXTERNAL_LINK_CANDIDATE`
- **Target 3** `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")` — `EXTERNAL_LINK_CANDIDATE`
- **Target 4** `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,` — `EXTERNAL_LINK_CANDIDATE`
- **Target 5** `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,` — `EXTERNAL_LINK_CANDIDATE`
- **Target 6** `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")` — `EXTERNAL_LINK_CANDIDATE`
- **Target 7** `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri` — `EXTERNAL_LINK_CANDIDATE`

## Already centralized

## Ambiguous — no mutation