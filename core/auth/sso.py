"""
SSO / OAuth2 Enterprise Authentication Module.

Provides OAuth2 and OpenID Connect (OIDC) single sign-on integration for the
enterprise web dashboard. Supports Google, Microsoft Azure AD, and generic
OIDC providers.

All SSO operations gracefully degrade if ``authlib`` is not installed.

Usage:
    from core.auth.sso import SSOAuthenticator

    sso = SSOAuthenticator(
        auth_handler=auth_handler,
        provider="google",
        client_id="...",
        client_secret="...",
        redirect_uri="https://example.com/api/auth/sso/callback",
    )

    # FastAPI routes:
    @router.get("/login/sso")
    async def sso_login():
        redirect_url = sso.get_authorization_url()
        return RedirectResponse(url=redirect_url)

    @router.get("/sso/callback")
    async def sso_callback(code: str, state: str):
        user = await sso.handle_callback(code, state)
        token = auth_handler.create_session(user)
        return {"token": token.token}
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Supported SSO providers ──────────────────────────────────────────────────

OAUTH_PROVIDERS: dict[str, dict[str, str]] = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
        "scope": "openid email profile",
    },
    "microsoft": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/v1.0/me",
        "scope": "openid email profile User.Read",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
    },
}


@dataclass
class SSOConfig:
    """Configuration for an SSO/OAuth2 provider.

    Attributes:
        provider: Provider name (google, microsoft, github, or custom).
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        redirect_uri: Callback URL after authentication.
        authorize_url: Custom authorize URL (for custom providers).
        token_url: Custom token URL (for custom providers).
        userinfo_url: Custom userinfo URL (for custom providers).
        scope: OAuth2 scope string.
        enabled: Whether SSO is enabled.
    """
    provider: str = ""
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    authorize_url: str = ""
    token_url: str = ""
    userinfo_url: str = ""
    scope: str = "openid email profile"
    enabled: bool = False


@dataclass
class SSOUser:
    """User info returned by an SSO provider.

    Attributes:
        provider: Provider name.
        provider_id: Unique ID from the provider.
        email: User's email address.
        display_name: User's display name.
        avatar_url: Optional avatar URL.
        raw: Raw userinfo response from the provider.
    """
    provider: str
    provider_id: str
    email: str
    display_name: str = ""
    avatar_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


# ── SSO Authenticator ────────────────────────────────────────────────────────

class SSOAuthenticator:
    """OAuth2/OIDC SSO authenticator.

    Integrates with the existing AuthHandler to create sessions after
    successful SSO authentication.

    Thread-safe. Gracefully degrades if ``authlib`` is not installed.
    """

    def __init__(
        self,
        auth_handler: Any | None = None,
        config: SSOConfig | None = None,
    ):
        self._auth_handler = auth_handler
        self._config = config or SSOConfig()
        self._state_store: dict[str, float] = {}  # state -> expiry timestamp
        self._state_ttl = 300  # 5 minutes
        self._lock = __import__("threading").RLock()

    @classmethod
    def from_config(
        cls,
        auth_handler: Any,
        cfg: dict[str, Any],
    ) -> SSOAuthenticator:
        """Create an SSOAuthenticator from a config dict.

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
        """
        provider = cfg.get("sso_provider", "").lower()
        provider_cfg = OAUTH_PROVIDERS.get(provider, {})

        sso_cfg = SSOConfig(
            provider=provider,
            client_id=cfg.get("sso_client_id", ""),
            client_secret=cfg.get("sso_client_secret", ""),
            redirect_uri=cfg.get("sso_redirect_uri", ""),
            authorize_url=cfg.get("sso_authorize_url", provider_cfg.get("authorize_url", "")),
            token_url=cfg.get("sso_token_url", provider_cfg.get("token_url", "")),
            userinfo_url=cfg.get("sso_userinfo_url", provider_cfg.get("userinfo_url", "")),
            scope=cfg.get("sso_scope", provider_cfg.get("scope", "openid email profile")),
            enabled=cfg.get("sso_enabled", False),
        )
        return cls(auth_handler=auth_handler, config=sso_cfg)

    @property
    def is_available(self) -> bool:
        """Check if authlib is installed."""
        try:
            return True
        except ImportError:
            return False

    def get_authorization_url(self, state: str | None = None) -> str | None:
        """Generate the OAuth2 authorization URL for the configured provider.

        Args:
            state: Optional OAuth2 state parameter (auto-generated if None).

        Returns:
            The full authorization URL, or None if authlib is not installed
            or configuration is incomplete.
        """
        if not self.is_available:
            _log.warning("[SSO] authlib not installed -- cannot generate auth URL")
            return None
        if not self._config.client_id or not self._config.redirect_uri:
            _log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")
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
            return uri
        except ImportError:
            _log.warning("[SSO] authlib submodules not available")
            return None
        except Exception as exc:
            _log.error("[SSO] Failed to create authorization URL: %s", exc)
            return None

    async def handle_callback(self, code: str, state: str) -> SSOUser | None:
        """Handle the OAuth2 callback, exchanging the code for tokens and user info.

        Args:
            code: The authorization code from the provider.
            state: The OAuth2 state parameter (must match get_authorization_url).

        Returns:
            SSOUser on success, None on failure.
        """
        # Verify state
        with self._lock:
            expiry = self._state_store.pop(state, None)
            if expiry is None:
                _log.warning("[SSO] Invalid or expired state parameter")
                return None
            if time.time() > expiry:
                _log.warning("[SSO] State parameter expired")
                return None

        if not self.is_available:
            _log.warning("[SSO] authlib not installed -- cannot handle callback")
            return None

        try:
            from authlib.integrations.httpx_client import OAuth2Client

            async with OAuth2Client(
                client_id=self._config.client_id,
                client_secret=self._config.client_secret,
                redirect_uri=self._config.redirect_uri,
                scope=self._config.scope,
            ) as client:
                # Exchange code for token
                token = await client.fetch_token(
                    self._config.token_url,
                    code=code,
                )
                if not token:
                    _log.warning("[SSO] Token exchange failed")
                    return None

                # Fetch user info
                access_token = token.get("access_token", "")
                if not access_token:
                    _log.warning("[SSO] No access token in response")
                    return None

                headers = {"Authorization": f"Bearer {access_token}"}
                resp = await client.get(self._config.userinfo_url, headers=headers)
                if resp.status_code != 200:
                    _log.warning(
                        "[SSO] Userinfo fetch failed: %d %s",
                        resp.status_code, resp.text[:200],
                    )
                    return None

                userinfo = resp.json()
                return self._parse_userinfo(userinfo)

        except ImportError as exc:
            _log.warning("[SSO] authlib/httpx not available: %s", exc)
            return None
        except Exception as exc:
            _log.error("[SSO] Callback handling failed: %s", exc)
            return None

    def _parse_userinfo(self, userinfo: dict[str, Any]) -> SSOUser:
        """Parse raw userinfo into a standardized SSOUser."""
        provider = self._config.provider

        if provider == "google":
            return SSOUser(
                provider="google",
                provider_id=userinfo.get("sub", ""),
                email=userinfo.get("email", ""),
                display_name=userinfo.get("name", ""),
                avatar_url=userinfo.get("picture", ""),
                raw=userinfo,
            )
        elif provider == "microsoft":
            return SSOUser(
                provider="microsoft",
                provider_id=userinfo.get("id", ""),
                email=userinfo.get("userPrincipalName", userinfo.get("mail", "")),
                display_name=userinfo.get("displayName", ""),
                raw=userinfo,
            )
        elif provider == "github":
            return SSOUser(
                provider="github",
                provider_id=str(userinfo.get("id", "")),
                email=userinfo.get("email", ""),
                display_name=userinfo.get("name", userinfo.get("login", "")),
                avatar_url=userinfo.get("avatar_url", ""),
                raw=userinfo,
            )
        else:
            # Generic OIDC provider
            return SSOUser(
                provider=provider,
                provider_id=userinfo.get("sub", userinfo.get("id", "")),
                email=userinfo.get("email", ""),
                display_name=userinfo.get("name", userinfo.get("preferred_username", "")),
                raw=userinfo,
            )

    def get_or_create_user(self, sso_user: SSOUser) -> Any:
        """Get an existing user or create a new one from SSO data.

        Integrates with the existing AuthHandler to look up users by
        email or create them on first SSO login.

        Args:
            sso_user: The SSO user returned by handle_callback().

        Returns:
            AuthUser from the AuthHandler, or None if integration fails.
        """
        if self._auth_handler is None:
            return None

        # Try to find existing user by SSO-linked email
        username = f"{sso_user.provider}_{sso_user.provider_id}"
        existing = self._auth_handler.get_user(username)

        if existing:
            return existing

        # Try by email
        if sso_user.email:
            existing_by_email = self._auth_handler.get_user(sso_user.email)
            if existing_by_email:
                return existing_by_email

        # Create new user with a random password (SSO users authenticate via OAuth)
        import secrets as sec
        random_pass = sec.token_hex(24)
        display = sso_user.display_name or sso_user.email.split("@")[0] if sso_user.email else sso_user.provider_id
        result = self._auth_handler.create_user(
            username=username,
            password=random_pass,
            role="operator",  # Default role for SSO users
            display_name=display,
            created_by="sso",
        )
        if result.get("success"):
            created = self._auth_handler.get_user(username)
            if created:
                _log.info("[SSO] Created new user from %s: %s", sso_user.provider, username)
                # Force password change on first login via SSO (they don't know the random password)
                self._force_password_change(username)
                return created

        return None

    def _force_password_change(self, username: str) -> None:
        """Force a password change on next login."""
        if self._auth_handler is None:
            return
        try:
            conn = self._auth_handler._get_conn()
            conn.execute(
                "UPDATE users SET must_change_password = 1 WHERE username = ?",
                (username.strip().lower(),),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            _log.debug("[SSO] Failed to set must_change_password: %s", exc)

    def cleanup_expired_states(self) -> int:
        """Remove expired OAuth2 states from the in-memory store.

        Returns:
            Number of expired states removed.
        """
        now = time.time()
        count = 0
        with self._lock:
            expired = [s for s, exp in self._state_store.items() if now > exp]
            for s in expired:
                self._state_store.pop(s, None)
                count += 1
        return count

    def is_ready(self) -> tuple[bool, list[str]]:
        """Check if the SSO authenticator is ready to use.

        Returns:
            Tuple of (ready, issues) where ready is True if all requirements
            are satisfied, and issues is a list of descriptive messages.
        """
        issues: list[str] = []
        if not self._config.enabled:
            issues.append("SSO not enabled in config")
        if not self._config.client_id:
            issues.append("Missing sso_client_id")
        if not self._config.client_secret:
            issues.append("Missing sso_client_secret")
        if not self._config.redirect_uri:
            issues.append("Missing sso_redirect_uri")
        if not self._config.authorize_url:
            issues.append("Missing sso_authorize_url (check provider config)")
        if not self._config.token_url:
            issues.append("Missing sso_token_url (check provider config)")
        if not self._config.userinfo_url:
            issues.append("Missing sso_userinfo_url (check provider config)")
        if not self.is_available:
            issues.append("authlib package not installed: pip install authlib")
        return len(issues) == 0, issues


__all__ = [
    "OAUTH_PROVIDERS",
    "SSOConfig",
    "SSOUser",
    "SSOAuthenticator",
]
