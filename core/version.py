"""Canonical Version Source of Truth for OPB Auto-Trade System.

Reads canonical version from the root VERSION file with deterministic fallback.
Prevents version drift between HUD, navigation, release notes, and APIs.
"""

from __future__ import annotations

import logging
from pathlib import Path

_log = logging.getLogger(__name__)

# Root is 2 parents up from core/version.py
_ROOT = Path(__file__).resolve().parent.parent
_VERSION_FILE = _ROOT / "VERSION"


def get_app_version() -> str:
    """Return the authoritative application version string (e.g. '2.60.0')."""
    try:
        if _VERSION_FILE.is_file():
            ver = _VERSION_FILE.read_text(encoding="utf-8").strip()
            if ver:
                return ver
    except Exception as exc:
        _log.warning("[VERSION] Failed to read VERSION file: %s", exc)
    return "2.60.0"


def get_app_version_tag() -> str:
    """Return the authoritative version tag (e.g. 'v2.60.0')."""
    ver = get_app_version()
    return ver if ver.startswith("v") else f"v{ver}"


APP_VERSION: str = get_app_version()
APP_VERSION_TAG: str = get_app_version_tag()
