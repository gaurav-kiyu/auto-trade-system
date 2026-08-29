# OPB WEB CLOSURE WIP38 — External URL Forensic Review

Candidates reviewed: 10
Confirmed external-link paths: 10
False-positive/config/internal candidates: 0

## Confirmed external-link paths

### `core/notifications/rich_signal_formatter.py:206`
- Pattern: `external-url-construction`
- Source: `cockpit_url = build_action_url("/my-signals", base_url=base_url)`
- Context:
  - `204: `
  - `205:         tv_chart_url = build_chart_url(symbol)`
  - `206:         cockpit_url = build_action_url("/my-signals", base_url=base_url)`
  - `207: `
  - `208:         asset_type_label = "the option position" if human_sym["is_option"] else "the stock position"`

### `core/auth/sso.py:17`
- Pattern: `external-url-construction`
- Source: `redirect_uri="https://example.com/api/auth/sso/callback",`
- Context:
  - `15:         client_id="...",`
  - `16:         client_secret="...",`
  - `17:         redirect_uri="https://example.com/api/auth/sso/callback",`
  - `18:     )`
  - `19: `

### `core/auth/sso.py:167`
- Pattern: `external-url-construction`
- Source: `redirect_uri=cfg.get("sso_redirect_uri", ""),`
- Context:
  - `165:             client_id=cfg.get("sso_client_id", ""),`
  - `166:             client_secret=cfg.get("sso_client_secret", ""),`
  - `167:             redirect_uri=cfg.get("sso_redirect_uri", ""),`
  - `168:             authorize_url=cfg.get("sso_authorize_url", provider_cfg.get("authorize_url", "")),`
  - `169:             token_url=cfg.get("sso_token_url", provider_cfg.get("token_url", "")),`

### `core/auth/sso.py:199`
- Pattern: `external-url-construction`
- Source: `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- Context:
  - `197:             return None`
  - `198:         if not self._config.client_id or not self._config.redirect_uri:`
  - `199:             _log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
  - `200:             return None`
  - `201: `

### `core/auth/sso.py:212`
- Pattern: `external-url-construction`
- Source: `redirect_uri=self._config.redirect_uri,`
- Context:
  - `210:                 client_id=self._config.client_id,`
  - `211:                 client_secret=self._config.client_secret,`
  - `212:                 redirect_uri=self._config.redirect_uri,`
  - `213:                 scope=self._config.scope,`
  - `214:             )`

### `core/auth/sso.py:258`
- Pattern: `external-url-construction`
- Source: `redirect_uri=self._config.redirect_uri,`
- Context:
  - `256:                 client_id=self._config.client_id,`
  - `257:                 client_secret=self._config.client_secret,`
  - `258:                 redirect_uri=self._config.redirect_uri,`
  - `259:                 scope=self._config.scope,`
  - `260:             ) as client:`

### `core/auth/sso.py:431`
- Pattern: `external-url-construction`
- Source: `issues.append("Missing sso_redirect_uri")`
- Context:
  - `429:             issues.append("Missing sso_client_secret")`
  - `430:         if not self._config.redirect_uri:`
  - `431:             issues.append("Missing sso_redirect_uri")`
  - `432:         if not self._config.authorize_url:`
  - `433:             issues.append("Missing sso_authorize_url (check provider config)")`

### `core/auth/routes.py:1081`
- Pattern: `external-url-construction`
- Source: `sso_redirect_uri = build_action_url(`
- Context:
  - `1079:             from core.auth.sso import SSOAuthenticator`
  - `1080:             app_config = getattr(request.app.state, "config", {}) or {}`
  - `1081:             sso_redirect_uri = build_action_url(`
  - `1082:                 "/api/auth/sso/callback",`
  - `1083:                 cfg=app_config,`

### `core/auth/routes.py:1085`
- Pattern: `external-url-construction`
- Source: `app_config["sso_redirect_uri"] = sso_redirect_uri`
- Context:
  - `1083:                 cfg=app_config,`
  - `1084:             )`
  - `1085:             app_config["sso_redirect_uri"] = sso_redirect_uri`
  - `1086:             sso = SSOAuthenticator.from_config(auth_handler, app_config)`
  - `1087: `

### `core/auth/routes.py:1093`
- Pattern: `external-url-construction`
- Source: `sso._config.redirect_uri = build_action_url(`
- Context:
  - `1091:         # would make the provider redirect the user to an unusable URL.`
  - `1092:         app_config = getattr(request.app.state, "config", {}) or {}`
  - `1093:         sso._config.redirect_uri = build_action_url(`
  - `1094:             "/api/auth/sso/callback",`
  - `1095:             cfg=app_config,`

## False-positive/config/internal candidates