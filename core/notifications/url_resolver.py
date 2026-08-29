"""Canonical External URL & Action Link Resolver (OPB-URL-GOVERNANCE-2026).

Centralizes resolution of external public base URLs, notification action links,
charting deep links, and cockpit navigation endpoints across all environments
(development, staging, test, and production).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
from typing import Any

_log = logging.getLogger("url_resolver")

# Canonical production public URL
DEFAULT_PRODUCTION_URL = "https://gaurav-cockpit.servegame.com"
DEFAULT_DEV_URL = "http://localhost:8000"

_CACHED_CONFIG: dict[str, Any] | None = None


def _is_loopback_url(url: str) -> bool:
    """Return True when a URL points to a local-only host."""
    try:
        parsed = urllib.parse.urlparse((url or "").strip())
        host = (parsed.hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".localhost")
    except Exception:
        return False


def invalidate_public_url_cache() -> None:
    """Invalidate cached global configuration after an Admin configuration change."""
    global _CACHED_CONFIG
    _CACHED_CONFIG = None


def _get_global_config() -> dict[str, Any]:
    """Lazy-load json/config.json if available."""
    global _CACHED_CONFIG
    if _CACHED_CONFIG is not None:
        return _CACHED_CONFIG

    config_path = os.path.join(os.path.dirname(__file__), "..", "..", "json", "config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                _CACHED_CONFIG = json.load(f)
                return _CACHED_CONFIG
        except Exception:
            pass

    _CACHED_CONFIG = {}
    return _CACHED_CONFIG


def is_production_environment(cfg: dict[str, Any] | None = None) -> bool:
    """Determine whether the current process is executing in a production environment."""
    # 1. Explicit environment variable flag
    env_name = (os.environ.get("OPB_ENV") or os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or "").lower()
    if env_name in ("prod", "production", "live"):
        return True

    # 2. Hostname / AWS deployment heuristic
    if os.path.exists("/home/ubuntu/auto-trade-system") or os.environ.get("AWS_EXECUTION_ENV"):
        return True

    # 3. Config dictionary inspection
    active_cfg = cfg or _get_global_config()
    if active_cfg:
        env_cfg = str(active_cfg.get("ENVIRONMENT", "")).lower()
        if env_cfg in ("prod", "production", "live"):
            return True
        mode = str(active_cfg.get("EXECUTION_MODE", "")).upper()
        if mode in ("AUTO", "LIVE", "SIGNAL_ONLY") and active_cfg.get("web_dashboard_host") == "0.0.0.0":
            return True

    return False


def get_deployment_base_url(cfg: dict[str, Any] | None = None) -> str:
    """Resolve the deployment/infrastructure public URL, excluding Admin overrides.

    This is intentionally separate from get_public_base_url(): the deployment
    URL is an infrastructure-level value and is displayed read-only in the
    Admin Configuration UI. Application-level overrides belong to
    PUBLIC_BASE_URL_ADMIN_OVERRIDE.
    """
    active_cfg = cfg or _get_global_config()

    # Explicit deployment environment variables are authoritative here.
    for env_key in (
        "PUBLIC_BASE_URL",
        "APP_BASE_URL",
        "EXTERNAL_BASE_URL",
        "OPBUYING_PUBLIC_BASE_URL",
    ):
        val = os.environ.get(env_key)
        if isinstance(val, str) and val.strip():
            url = val.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            return url

    # Persisted deployment-level PUBLIC_BASE_URL is a fallback when the
    # deployment environment does not expose the value directly.
    val = active_cfg.get("PUBLIC_BASE_URL")
    if isinstance(val, str) and val.strip():
        url = val.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    if is_production_environment(active_cfg):
        return DEFAULT_PRODUCTION_URL
    return DEFAULT_DEV_URL



def get_public_base_url(cfg: dict[str, Any] | None = None) -> str:
    """Resolve the canonical public base URL for notifications, emails, and external links.

    Resolution order:
      1. Environment variable: PUBLIC_BASE_URL, APP_BASE_URL, EXTERNAL_BASE_URL, OPBUYING_PUBLIC_BASE_URL
      2. Explicit Configuration dict passed by caller
      3. Global configuration dict (json/config.json)
      4. Environment auto-detection:
         - Production -> https://gaurav-cockpit.servegame.com
         - Development -> http://localhost:8000
    """
    # 1. Explicit Admin-managed override. This is intentionally above deployment
    # environment variables so an authorized Admin/Super Admin can change the
    # public origin from the UI and have it reflected consistently at runtime.
    if cfg:
        val = cfg.get("PUBLIC_BASE_URL_ADMIN_OVERRIDE")
        if isinstance(val, str) and val.strip():
            url = val.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            if is_production_environment(cfg) and _is_loopback_url(url):
                return DEFAULT_PRODUCTION_URL
            return url

    global_cfg = _get_global_config()
    val = global_cfg.get("PUBLIC_BASE_URL_ADMIN_OVERRIDE")
    if isinstance(val, str) and val.strip():
        url = val.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        if is_production_environment(cfg) and _is_loopback_url(url):
            return DEFAULT_PRODUCTION_URL
        return url

    # 2. Environment variables retain deployment-level precedence for the
    # legacy PUBLIC_BASE_URL contract when no Admin override is configured.
    for env_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL", "OPBUYING_PUBLIC_BASE_URL"):
        val = os.environ.get(env_key)
        if val and val.strip():
            url = val.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            if is_production_environment(cfg) and _is_loopback_url(url):
                return DEFAULT_PRODUCTION_URL
            return url

    # 3. Persisted legacy configuration fallback.
    if cfg:
        for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):
            val = cfg.get(cfg_key)
            if val and isinstance(val, str) and val.strip():
                url = val.strip().rstrip("/")
                if not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                if is_production_environment(cfg) and _is_loopback_url(url):
                    return DEFAULT_PRODUCTION_URL
                return url

    for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):
        val = global_cfg.get(cfg_key)
        if val and isinstance(val, str) and val.strip():
            url = val.strip().rstrip("/")
            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"
            if is_production_environment(cfg) and _is_loopback_url(url):
                return DEFAULT_PRODUCTION_URL
            return url

    # 4. Environment heuristic
    if is_production_environment(cfg):
        return DEFAULT_PRODUCTION_URL

    return DEFAULT_DEV_URL


def build_action_url(
    path: str = "",
    params: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    base_url: str | None = None,
) -> str:
    """Construct an absolute external action URL with canonical domain and sanitized query params."""
    root = (base_url or get_public_base_url(cfg)).rstrip("/")
    if is_production_environment(cfg) and _is_loopback_url(root):
        root = DEFAULT_PRODUCTION_URL
    clean_path = ("/" + path.lstrip("/")) if path else ""

    if not params:
        return f"{root}{clean_path}"

    filtered_params = {k: v for k, v in params.items() if v is not None and v != ""}
    if not filtered_params:
        return f"{root}{clean_path}"

    query_str = urllib.parse.urlencode(filtered_params)
    separator = "&" if "?" in clean_path else "?"
    return f"{root}{clean_path}{separator}{query_str}"


def build_chart_url(symbol: str) -> str:
    """Build an external TradingView live chart URL for an Indian NSE instrument."""
    clean_sym = symbol.strip().replace("&", "%26")
    return f"https://in.tradingview.com/chart/?symbol=NSE:{clean_sym}"
