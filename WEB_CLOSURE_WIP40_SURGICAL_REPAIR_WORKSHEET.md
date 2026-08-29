# OPB WEB CLOSURE WIP40 — Seven Surgical URL Repair Targets

Targets carried from WIP39: 7

## Target 1 — `core/auth/sso.py:17`
**Matched line:** `redirect_uri="https://example.com/api/auth/sso/callback",`
**Context:**
- `14:         provider="google",`
- `15:         client_id="...",`
- `16:         client_secret="...",`
- `17:         redirect_uri="https://example.com/api/auth/sso/callback",`
- `18:     )`
- `19: `
- `20:     # FastAPI routes:`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 2 — `core/auth/sso.py:167`
**Matched line:** `redirect_uri=cfg.get("sso_redirect_uri", ""),`
**Context:**
- `164:             provider=provider,`
- `165:             client_id=cfg.get("sso_client_id", ""),`
- `166:             client_secret=cfg.get("sso_client_secret", ""),`
- `167:             redirect_uri=cfg.get("sso_redirect_uri", ""),`
- `168:             authorize_url=cfg.get("sso_authorize_url", provider_cfg.get("authorize_url", "")),`
- `169:             token_url=cfg.get("sso_token_url", provider_cfg.get("token_url", "")),`
- `170:             userinfo_url=cfg.get("sso_userinfo_url", provider_cfg.get("userinfo_url", "")),`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 3 — `core/auth/sso.py:199`
**Matched line:** `_log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
**Context:**
- `196:             _log.warning("[SSO] authlib not installed -- cannot generate auth URL")`
- `197:             return None`
- `198:         if not self._config.client_id or not self._config.redirect_uri:`
- `199:             _log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")`
- `200:             return None`
- `201: `
- `202:         state = state or secrets.token_urlsafe(32)`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 4 — `core/auth/sso.py:212`
**Matched line:** `redirect_uri=self._config.redirect_uri,`
**Context:**
- `209:             session = OAuth2Session(`
- `210:                 client_id=self._config.client_id,`
- `211:                 client_secret=self._config.client_secret,`
- `212:                 redirect_uri=self._config.redirect_uri,`
- `213:                 scope=self._config.scope,`
- `214:             )`
- `215:             uri, _ = session.create_authorization_url(`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 5 — `core/auth/sso.py:258`
**Matched line:** `redirect_uri=self._config.redirect_uri,`
**Context:**
- `255:             async with OAuth2Client(`
- `256:                 client_id=self._config.client_id,`
- `257:                 client_secret=self._config.client_secret,`
- `258:                 redirect_uri=self._config.redirect_uri,`
- `259:                 scope=self._config.scope,`
- `260:             ) as client:`
- `261:                 # Exchange code for token`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 6 — `core/auth/sso.py:431`
**Matched line:** `issues.append("Missing sso_redirect_uri")`
**Context:**
- `428:         if not self._config.client_secret:`
- `429:             issues.append("Missing sso_client_secret")`
- `430:         if not self._config.redirect_uri:`
- `431:             issues.append("Missing sso_redirect_uri")`
- `432:         if not self._config.authorize_url:`
- `433:             issues.append("Missing sso_authorize_url (check provider config)")`
- `434:         if not self._config.token_url:`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.

## Target 7 — `core/auth/routes.py:1085`
**Matched line:** `app_config["sso_redirect_uri"] = sso_redirect_uri`
**Context:**
- `1082:                 "/api/auth/sso/callback",`
- `1083:                 cfg=app_config,`
- `1084:             )`
- `1085:             app_config["sso_redirect_uri"] = sso_redirect_uri`
- `1086:             sso = SSOAuthenticator.from_config(auth_handler, app_config)`
- `1087: `
- `1088:         # Keep the OAuth callback on the canonical public origin configured for`
**Repair contract:** replace only externally visible URL construction with the canonical resolver/builder while preserving route parameters, auth, CSRF, and response behavior.
