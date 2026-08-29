"""TLS/SSL Configuration (Phase 15 — Security Certification).

Provides TLS configuration helpers for HTTPS enforcement, secure
WebSocket connections, and outbound API calls to broker endpoints.

Usage:
    from core.auth.tls_config import TLSConfig

    config = TLSConfig()
    ssl_context = config.get_ssl_context()
    assert config.is_tls_enabled
"""

from __future__ import annotations

# Optional: starlette is only needed for enforce_https() middleware
# Not installed by default — guard with find_spec
import importlib.util
import logging
import os
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_HAS_STARLETTE: bool = importlib.util.find_spec("starlette") is not None

_log = logging.getLogger(__name__)

__all__ = [
    "TLSConfig",
    "MIN_TLS_VERSION",
    "SECURE_CIPHERS",
]

# Minimum TLS version: 1.2 (reject SSLv3, TLSv1.0, TLSv1.1)
MIN_TLS_VERSION = ssl.TLSVersion.TLSv1_2

# Secure cipher suite (Mozilla intermediate compatibility)
SECURE_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-CHACHA20-POLY1305:"
    "DHE-RSA-AES128-GCM-SHA256:"
    "DHE-RSA-AES256-GCM-SHA384"
)


@dataclass
class TLSConfig:
    """TLS/SSL configuration for secure communications.

    Attributes:
        enabled: Whether TLS enforcement is enabled.
        cert_path: Path to TLS certificate file (PEM format).
        key_path: Path to TLS private key file (PEM format).
        ca_cert_path: Path to CA certificate bundle for verification.
        min_tls_version: Minimum allowed TLS version.
        ciphers: Allowed cipher suite string.
        verify_hostname: Whether to verify hostnames on outbound connections.
        verify_mode: SSL verification mode (CERT_REQUIRED, CERT_OPTIONAL, CERT_NONE).
    """

    enabled: bool = True
    cert_path: str = ""
    key_path: str = ""
    ca_cert_path: str = ""
    min_tls_version: int = MIN_TLS_VERSION
    ciphers: str = SECURE_CIPHERS
    verify_hostname: bool = True
    verify_mode: int = ssl.CERT_REQUIRED

    @classmethod
    def from_env(cls) -> TLSConfig:
        """Create TLSConfig from environment variables.

        Env vars:
            OPBUYING_TLS_ENABLED: Enable TLS (default: true)
            OPBUYING_TLS_CERT: Path to certificate file
            OPBUYING_TLS_KEY: Path to private key file
            OPBUYING_TLS_CA_CERT: Path to CA certificate bundle
        """
        return cls(
            enabled=os.environ.get("OPBUYING_TLS_ENABLED", "true").lower() in ("true", "1", "yes"),
            cert_path=os.environ.get("OPBUYING_TLS_CERT", ""),
            key_path=os.environ.get("OPBUYING_TLS_KEY", ""),
            ca_cert_path=os.environ.get("OPBUYING_TLS_CA_CERT", ""),
        )

    @classmethod
    def from_dict(cls, cfg: dict[str, Any]) -> TLSConfig:
        """Create TLSConfig from configuration dict."""
        tls = cfg.get("tls_config", {})
        return cls(
            enabled=bool(tls.get("enabled", True)),
            cert_path=str(tls.get("cert_path", "")),
            key_path=str(tls.get("key_path", "")),
            ca_cert_path=str(tls.get("ca_cert_path", "")),
        )

    @property
    def is_tls_enabled(self) -> bool:
        return self.enabled and bool(self.cert_path) and bool(self.key_path)

    def get_ssl_context(self, purpose: str = "server") -> ssl.SSLContext:
        """Create an SSL context with secure defaults.

        Args:
            purpose: "server" for server-side TLS, "client" for outbound connections.

        Returns:
            Configured SSLContext.
        """
        if purpose == "server":
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        else:
            ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

        ctx.minimum_version = self.min_tls_version
        ctx.set_ciphers(self.ciphers)

        if self.verify_mode == ssl.CERT_NONE:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        else:
            ctx.check_hostname = self.verify_hostname
            ctx.verify_mode = self.verify_mode

        if self.ca_cert_path:
            ca_path = Path(self.ca_cert_path)
            if ca_path.is_file():
                ctx.load_verify_locations(ca_path)

        if self.cert_path and self.key_path:
            ctx.load_cert_chain(self.cert_path, self.key_path)

        _log.info(
            "TLS configured: enabled=%s, purpose=%s, min_tls=%s, ciphers=%s",
            self.is_tls_enabled, purpose, self.min_tls_version, "SECURE",
        )
        return ctx

    def enforce_https(self, app):
        """Middleware to enforce HTTPS on a web application.

        Can be used with FastAPI/Flask apps to redirect HTTP to HTTPS.
        Requires the ``starlette`` package (not installed by default).
        Returns the app unchanged if starlette is not available.

        Args:
            app: The web application instance (FastAPI or Flask).

        Returns:
            The same app with HTTPS enforcement middleware, or unchanged
            if starlette is not installed.
        """
        if not self.enabled:
            return app

        if not _HAS_STARLETTE:
            _log.warning(
                "HTTPS enforcement requires starlette — install with: "
                "pip install starlette"
            )
            return app

        try:
            from starlette.responses import RedirectResponse

            @app.middleware("http")
            async def https_redirect(request, call_next):
                """Redirect HTTP to HTTPS."""
                if request.headers.get("x-forwarded-proto", "").lower() != "https":
                    url = str(request.url).replace("http://", "https://", 1)
                    return RedirectResponse(url, status_code=301)
                return await call_next(request)

            _log.info("HTTPS enforcement middleware enabled")
        except ImportError:
            _log.warning(
                "Failed to import starlette for HTTPS enforcement — "
                "install with: pip install starlette"
            )

        return app

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "cert_path": self.cert_path if self.cert_path else "(not set)",
            "key_path": self.key_path if self.key_path else "(not set)",
            "min_tls_version": str(self.min_tls_version),
            "verify_hostname": self.verify_hostname,
        }
