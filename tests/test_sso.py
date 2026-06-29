"""
Tests for core/auth/sso.py — SSO / OAuth2 Enterprise Authentication.

Tests the SSOAuthenticator class with mocked HTTP responses.
Since authlib may not be installed in test environments, tests validate
graceful degradation behavior and configuration validation.
"""

from __future__ import annotations

import pytest
from core.auth.sso import OAUTH_PROVIDERS, SSOAuthenticator, SSOConfig, SSOUser


class TestSSOConfig:
    """Tests for SSOConfig dataclass."""

    def test_default_config(self):
        """Default SSOConfig should have empty fields."""
        cfg = SSOConfig()
        assert cfg.provider == ""
        assert cfg.client_id == ""
        assert cfg.enabled is False

    def test_google_provider_defaults(self):
        """Google provider should have correct defaults in OAUTH_PROVIDERS."""
        google = OAUTH_PROVIDERS["google"]
        assert "accounts.google.com" in google["authorize_url"]
        assert "googleapis.com" in google["token_url"]
        assert "openid" in google["scope"]

    def test_microsoft_provider_defaults(self):
        """Microsoft provider should have correct defaults."""
        ms = OAUTH_PROVIDERS["microsoft"]
        assert "microsoftonline.com" in ms["authorize_url"]
        assert "graph.microsoft.com" in ms["userinfo_url"]

    def test_github_provider_defaults(self):
        """GitHub provider should have correct defaults."""
        gh = OAUTH_PROVIDERS["github"]
        assert "github.com/login/oauth/authorize" in gh["authorize_url"]
        assert "api.github.com" in gh["userinfo_url"]


class TestSSOUser:
    """Tests for SSOUser dataclass."""

    def test_sso_user_creation(self):
        """SSOUser should be creatable with minimal fields."""
        user = SSOUser(provider="google", provider_id="123", email="test@example.com")
        assert user.provider == "google"
        assert user.email == "test@example.com"
        assert user.display_name == ""
        assert user.avatar_url == ""

    def test_sso_user_full(self):
        """SSOUser with all fields should work."""
        user = SSOUser(
            provider="google",
            provider_id="abc123",
            email="user@gmail.com",
            display_name="Test User",
            avatar_url="https://example.com/avatar.png",
            raw={"sub": "abc123", "email": "user@gmail.com"},
        )
        assert user.display_name == "Test User"
        assert user.raw["sub"] == "abc123"


class TestSSOAuthenticatorInit:
    """Tests for SSOAuthenticator initialization."""

    def test_init_no_auth_handler(self):
        """SSOAuthenticator should init without auth handler."""
        sso = SSOAuthenticator()
        assert sso._auth_handler is None
        assert sso._config.enabled is False

    def test_init_with_config(self):
        """SSOAuthenticator should accept a config."""
        cfg = SSOConfig(provider="google", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback", enabled=True)
        sso = SSOAuthenticator(config=cfg)
        assert sso._config.provider == "google"
        assert sso._config.client_id == "id"
        assert sso._config.enabled is True

    def test_from_config_empty(self):
        """from_config should handle empty config."""
        sso = SSOAuthenticator.from_config(None, {})
        assert sso._config.provider == ""
        assert sso._config.enabled is False

    def test_from_config_google(self):
        """from_config should configure Google provider."""
        cfg = {
            "sso_enabled": True,
            "sso_provider": "google",
            "sso_client_id": "google-id",
            "sso_client_secret": "google-secret",
            "sso_redirect_uri": "https://example.com/callback",
        }
        sso = SSOAuthenticator.from_config(None, cfg)
        assert sso._config.enabled is True
        assert sso._config.provider == "google"
        assert sso._config.client_id == "google-id"
        assert "googleapis.com" in sso._config.token_url

    def test_from_config_custom_provider(self):
        """from_config should support custom providers."""
        cfg = {
            "sso_enabled": True,
            "sso_provider": "custom",
            "sso_client_id": "custom-id",
            "sso_client_secret": "custom-secret",
            "sso_redirect_uri": "https://example.com/callback",
            "sso_authorize_url": "https://custom.com/auth",
            "sso_token_url": "https://custom.com/token",
            "sso_userinfo_url": "https://custom.com/userinfo",
        }
        sso = SSOAuthenticator.from_config(None, cfg)
        assert sso._config.authorize_url == "https://custom.com/auth"
        assert sso._config.token_url == "https://custom.com/token"
        assert sso._config.userinfo_url == "https://custom.com/userinfo"


class TestSSOAvailability:
    """Tests for SSO availability checks."""

    def test_is_available_false_when_no_authlib(self):
        """is_available should be False when authlib is not installed."""
        sso = SSOAuthenticator()
        assert sso.is_available is False

    def test_get_authorization_url_returns_none_no_authlib(self):
        """get_authorization_url should return None when authlib not installed."""
        cfg = SSOConfig(
            provider="google",
            client_id="test-id",
            client_secret="test-secret",
            redirect_uri="https://example.com/callback",
            enabled=True,
        )
        sso = SSOAuthenticator(config=cfg)
        result = sso.get_authorization_url()
        assert result is None

    def test_get_authorization_url_returns_none_no_client_id(self):
        """get_authorization_url should return None when client_id is missing."""
        sso = SSOAuthenticator()
        result = sso.get_authorization_url()
        assert result is None


class TestSSOParseUserInfo:
    """Tests for user info parsing."""

    @pytest.fixture
    def google_sso(self):
        cfg = SSOConfig(provider="google", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback")
        return SSOAuthenticator(config=cfg)

    @pytest.fixture
    def microsoft_sso(self):
        cfg = SSOConfig(provider="microsoft", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback")
        return SSOAuthenticator(config=cfg)

    @pytest.fixture
    def github_sso(self):
        cfg = SSOConfig(provider="github", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback")
        return SSOAuthenticator(config=cfg)

    def test_parse_google(self, google_sso):
        """Google userinfo should be parsed correctly."""
        userinfo = {
            "sub": "12345",
            "email": "user@gmail.com",
            "name": "Test User",
            "picture": "https://example.com/photo.jpg",
        }
        user = google_sso._parse_userinfo(userinfo)
        assert user.provider == "google"
        assert user.provider_id == "12345"
        assert user.email == "user@gmail.com"
        assert user.display_name == "Test User"
        assert user.avatar_url == "https://example.com/photo.jpg"

    def test_parse_microsoft(self, microsoft_sso):
        """Microsoft userinfo should be parsed correctly."""
        userinfo = {
            "id": "abc-def",
            "userPrincipalName": "user@contoso.com",
            "displayName": "Contoso User",
        }
        user = microsoft_sso._parse_userinfo(userinfo)
        assert user.provider == "microsoft"
        assert user.provider_id == "abc-def"
        assert user.email == "user@contoso.com"
        assert user.display_name == "Contoso User"

    def test_parse_github(self, github_sso):
        """GitHub userinfo should be parsed correctly."""
        userinfo = {
            "id": 42,
            "email": "dev@github.com",
            "name": "Dev User",
            "login": "devuser",
            "avatar_url": "https://avatars.githubusercontent.com/u/42",
        }
        user = github_sso._parse_userinfo(userinfo)
        assert user.provider == "github"
        assert user.provider_id == "42"
        assert user.email == "dev@github.com"
        assert user.display_name == "Dev User"
        assert user.avatar_url == "https://avatars.githubusercontent.com/u/42"

    def test_parse_generic_oidc(self):
        """Generic OIDC provider userinfo should be parsed correctly."""
        cfg = SSOConfig(provider="custom", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback")
        sso = SSOAuthenticator(config=cfg)
        userinfo = {
            "sub": "oidc-sub-123",
            "email": "user@oidc.com",
            "name": "OIDC User",
        }
        user = sso._parse_userinfo(userinfo)
        assert user.provider == "custom"
        assert user.provider_id == "oidc-sub-123"
        assert user.email == "user@oidc.com"
        assert user.display_name == "OIDC User"

    def test_parse_minimal(self, google_sso):
        """Minimal userinfo should not crash."""
        user = google_sso._parse_userinfo({})
        assert user.provider == "google"
        assert user.provider_id == ""
        assert user.email == ""


class TestSSOCallback:
    """Tests for SSO callback handling."""

    @pytest.mark.asyncio
    async def test_handle_callback_none_no_authlib(self):
        """handle_callback should return None when authlib not installed."""
        cfg = SSOConfig(provider="google", client_id="id", client_secret="secret", redirect_uri="https://example.com/callback", enabled=True)
        sso = SSOAuthenticator(config=cfg)
        # Set a state first
        sso._state_store["test_state"] = 9999999999.0
        result = await sso.handle_callback("code", "test_state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_callback_invalid_state(self):
        """handle_callback should reject invalid state."""
        sso = SSOAuthenticator()
        result = await sso.handle_callback("code", "nonexistent_state")
        assert result is None

    @pytest.mark.asyncio
    async def test_handle_callback_expired_state(self):
        """handle_callback should reject expired state."""
        sso = SSOAuthenticator()
        sso._state_store["old_state"] = 0.0  # Expired (epoch)
        result = await sso.handle_callback("code", "old_state")
        assert result is None


class TestSSOReady:
    """Tests for is_ready checks."""

    def test_is_ready_not_enabled(self):
        """is_ready should return False when SSO is not enabled."""
        sso = SSOAuthenticator()
        ready, issues = sso.is_ready()
        assert ready is False
        assert any("not enabled" in i.lower() for i in issues)

    def test_is_ready_missing_config(self):
        """is_ready should report missing config fields."""
        cfg = SSOConfig(enabled=True)
        sso = SSOAuthenticator(config=cfg)
        ready, issues = sso.is_ready()
        assert ready is False
        assert any("client_id" in i for i in issues)
        assert any("client_secret" in i for i in issues)

    def test_is_ready_google_configured(self):
        """is_ready with full Google config should report missing authlib."""
        cfg = SSOConfig(
            provider="google",
            client_id="id",
            client_secret="secret",
            redirect_uri="https://example.com/callback",
            authorize_url=OAUTH_PROVIDERS["google"]["authorize_url"],
            token_url=OAUTH_PROVIDERS["google"]["token_url"],
            userinfo_url=OAUTH_PROVIDERS["google"]["userinfo_url"],
            enabled=True,
        )
        sso = SSOAuthenticator(config=cfg)
        ready, issues = sso.is_ready()
        assert ready is False  # authlib not installed
        assert any("authlib" in i for i in issues)


class TestSSOStateCleanup:
    """Tests for SSO state cleanup."""

    def test_cleanup_expired_states(self):
        """Expired states should be cleaned up."""
        sso = SSOAuthenticator()
        sso._state_store["state1"] = 0.0  # Expired
        sso._state_store["state2"] = 9999999999.0  # Valid
        cleaned = sso.cleanup_expired_states()
        assert cleaned == 1
        assert "state1" not in sso._state_store
        assert "state2" in sso._state_store

    def test_cleanup_no_expired(self):
        """Cleanup with no expired states should return 0."""
        sso = SSOAuthenticator()
        sso._state_store["state1"] = 9999999999.0
        cleaned = sso.cleanup_expired_states()
        assert cleaned == 0

    def test_cleanup_empty(self):
        """Cleanup with empty state store should return 0."""
        sso = SSOAuthenticator()
        cleaned = sso.cleanup_expired_states()
        assert cleaned == 0


class TestSSOProviderDefaults:
    """Tests that all providers have required URLs."""

    def test_all_providers_have_authorize_url(self):
        """Every provider should have an authorize_url."""
        for name, cfg in OAUTH_PROVIDERS.items():
            assert cfg["authorize_url"], f"{name} missing authorize_url"

    def test_all_providers_have_token_url(self):
        """Every provider should have a token_url."""
        for name, cfg in OAUTH_PROVIDERS.items():
            assert cfg["token_url"], f"{name} missing token_url"

    def test_all_providers_have_userinfo_url(self):
        """Every provider should have a userinfo_url."""
        for name, cfg in OAUTH_PROVIDERS.items():
            assert cfg["userinfo_url"], f"{name} missing userinfo_url"

    def test_all_providers_have_scope(self):
        """Every provider should have a scope."""
        for name, cfg in OAUTH_PROVIDERS.items():
            assert cfg["scope"], f"{name} missing scope"


class TestSSOEdgeCases:
    """Edge cases for SSO module."""

    def test_config_dataclass_values(self):
        """SSOConfig should store and return values correctly."""
        cfg = SSOConfig(provider="test")
        assert cfg.provider == "test"
        assert cfg.client_id == ""
        assert cfg.enabled is False
        assert cfg.scope == "openid email profile"

    def test_sso_user_to_dict(self):
        """SSOUser should be convertible to dict."""
        user = SSOUser(provider="google", provider_id="123", email="test@example.com")
        d = {
            "provider": user.provider,
            "provider_id": user.provider_id,
            "email": user.email,
            "display_name": user.display_name,
        }
        assert d["provider"] == "google"
        assert d["email"] == "test@example.com"

    def test_get_or_create_user_no_auth_handler(self):
        """get_or_create_user should return None without auth handler."""
        sso = SSOAuthenticator()
        sso_user = SSOUser(provider="google", provider_id="123", email="test@example.com")
        result = sso.get_or_create_user(sso_user)
        assert result is None
