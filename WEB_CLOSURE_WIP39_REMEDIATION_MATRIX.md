# OPB WEB CLOSURE WIP39 — Confirmed External URL Remediation Matrix

Confirmed external paths reviewed: 10
Already centralized: 3
Confirmed non-centralized candidates: 7

## Already centralized — no mutation
- `core/notifications/rich_signal_formatter.py:206` — `cockpit_url = build_action_url("/my-signals", base_url=base_url)`
- `core/auth/routes.py:1081` — `sso_redirect_uri = build_action_url(`
- `core/auth/routes.py:1093` — `sso._config.redirect_uri = build_action_url(`

## Non-centralized candidates — surgical repair targets
- `core/auth/sso.py:17` — `redirect_uri="https://example.com/api/auth/sso/callback",`
- `core/auth/sso.py:167` — `redirect_uri=cfg.get("sso_redirect_uri", ""),`
- `core/auth/sso.py:199` — `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- `core/auth/sso.py:212` — `redirect_uri=self._config.redirect_uri,`
- `core/auth/sso.py:258` — `redirect_uri=self._config.redirect_uri,`
- `core/auth/sso.py:431` — `issues.append("Missing sso_redirect_uri")`
- `core/auth/routes.py:1085` — `app_config["sso_redirect_uri"] = sso_redirect_uri`

## Safety rule
Only non-centralized runtime external-link construction is eligible for mutation. Already-centralized paths receive regression protection instead of another edit.