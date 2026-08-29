# OPB WEB CLOSURE WIP46 — SSO Call-Site & URL Consumer Dossier

This pass traces the seven SSO candidates into their enclosing functions and records URL consumers/resolver usage.
No source mutation was performed.

## Target 1 — `core/auth/sso.py:17`
- Function: `UNKNOWN`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `none`

## Target 2 — `core/auth/sso.py:167`
- Function: `def from_config(`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `),
            redirect_uri=cfg.get(, Create an SSOAuthenticator from a config dict.

        Expected config keys:
            - sso_enabled (bool)
            - sso_provider (str): google, microsoft, github, or custom
            - sso_client_id (str)
            - sso_client_secret (str)
            - sso_redirect_uri (str)
            - sso_scope (str, optional)
            - sso_authorize_url (str, optional, for custom providers)
            - sso_token_url (str, optional, for custom providers)
            - sso_userinfo_url (str, optional, for custom providers)
        `

## Target 3 — `core/auth/sso.py:199`
- Function: `def get_authorization_url(self, state: str | None = None) -> str | None:`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `)
            return None

        state = state or secrets.token_urlsafe(32)
        with self._lock:
            self._state_store[state] = time.time() + self._state_ttl

        try:
            from authlib.integrations.requests_client import OAuth2Session

            session = OAuth2Session(
                client_id=self._config.client_id,
                client_secret=self._config.client_secret,
                redirect_uri=self._config.redirect_uri,
                scope=self._config.scope,
            )
            uri, _ = session.create_authorization_url(
                self._config.authorize_url,
                state=state,
            )
            return uri  # type: ignore[no-any-return]
        except ImportError:
            _log.warning(, )
            return None
        if not self._config.client_id or not self._config.redirect_uri:
            _log.warning(`

## Target 4 — `core/auth/sso.py:212`
- Function: `def get_authorization_url(self, state: str | None = None) -> str | None:`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `)
            return None

        state = state or secrets.token_urlsafe(32)
        with self._lock:
            self._state_store[state] = time.time() + self._state_ttl

        try:
            from authlib.integrations.requests_client import OAuth2Session

            session = OAuth2Session(
                client_id=self._config.client_id,
                client_secret=self._config.client_secret,
                redirect_uri=self._config.redirect_uri,
                scope=self._config.scope,
            )
            uri, _ = session.create_authorization_url(
                self._config.authorize_url,
                state=state,
            )
            return uri  # type: ignore[no-any-return]
        except ImportError:
            _log.warning(, )
            return None
        if not self._config.client_id or not self._config.redirect_uri:
            _log.warning(`

## Target 5 — `core/auth/sso.py:258`
- Function: `async def handle_callback(self, code: str, state: str) -> SSOUser | None:`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `Handle the OAuth2 callback, exchanging the code for tokens and user info.

        Args:
            code: The authorization code from the provider.
            state: The OAuth2 state parameter (must match get_authorization_url).

        Returns:
            SSOUser on success, None on failure.

        , [SSO] Callback handling failed: %s, [SSO] authlib not installed -- cannot handle callback`

## Target 6 — `core/auth/sso.py:431`
- Function: `def is_ready(self) -> tuple[bool, list[str]]:`
- Resolver calls in function: `0`
- Request-origin references: `none`
- URL-like literals: `)
        if not self._config.redirect_uri:
            issues.append(`

## Target 7 — `core/auth/routes.py:1085`
- Function: `async def sso_login(`
- Resolver calls in function: `2`
- Request-origin references: `request.base_url`
- URL-like literals: `, {}) or {}
            sso_redirect_uri = build_action_url(
                , , {}) or {}
        sso._config.redirect_uri = build_action_url(
            , /sso/callback, Initiate SSO login with the specified provider.

        Query params:
            provider: OAuth2 provider (google, microsoft, github).

        Returns:
            Dict with ``authorization_url`` to redirect the user to.

        , sso_redirect_uri`
