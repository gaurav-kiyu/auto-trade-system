"""Small shared config utilities for index + stock entry scripts (secrets, TG patterns)."""

from __future__ import annotations

import base64
from typing import Any


def decode_if_b64(s: Any) -> Any:
    """Decode values prefixed with ``b64:`` in config JSON for light obfuscation."""
    if not s or not isinstance(s, str):
        return s
    if s.startswith("b64:"):
        try:
            return base64.b64decode(s[4:]).decode()
        except (ValueError, TypeError):
            return s
    return s


def redact(s: str) -> str:
    """Show first ~20%% of a secret, mask the rest (config print / logs)."""
    if not s or len(s) < 4:
        return "***"
    keep = max(2, len(s) // 5)
    return s[:keep] + "*" * (len(s) - keep)


def deep_merge_dict(base: dict, overlay: dict | None) -> dict:
    """Recursively merge overlay into base (config overlays, GUI_* nested dicts)."""
    out = dict(base)
    if not isinstance(overlay, dict):
        return out
    for k, v in overlay.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def normalize_tg_trade_patterns(cfg: dict, default_patterns: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve TG_TRADE_CRITICAL_PATTERNS from config list or fall back to app defaults."""
    raw = cfg.get("TG_TRADE_CRITICAL_PATTERNS")
    if isinstance(raw, list) and len(raw) > 0:
        return tuple(str(x).strip() for x in raw if str(x).strip())
    return default_patterns


# Keys whose entire value must be replaced — sub-objects that hold credentials.
_AUDIT_REDACT_SUBOBJECTS: frozenset[str] = frozenset({"BROKER_CONFIG"})

# Top-level scalar keys that hold sensitive tokens or passwords.
_AUDIT_REDACT_SCALARS: frozenset[str] = frozenset({"BOT_TOKEN", "CHAT_ID"})


def build_audit_config_snapshot(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *cfg* that is safe to pass to AuditEngine.record().

    Rules applied in order:
      - Keys starting with ``_NOTE`` are annotation noise — omitted.
      - Keys in ``_AUDIT_REDACT_SUBOBJECTS`` (e.g. BROKER_CONFIG) are replaced
        with ``{"redacted": True}`` so the key is visible but credentials are not.
      - Keys in ``_AUDIT_REDACT_SCALARS`` (BOT_TOKEN, CHAT_ID) are partially
        masked via ``redact()``.
      - All other keys are copied as-is.

    Intended usage::

        snapshot = build_audit_config_snapshot(cfg)
        audit.record("effective_config", severity="AUDIT", **snapshot)

    The result is a flat dict suitable for JSON serialisation.
    """
    out: dict[str, Any] = {}
    for k, v in cfg.items():
        if k.startswith("_NOTE"):
            continue
        if k in _AUDIT_REDACT_SUBOBJECTS:
            out[k] = {"redacted": True}
        elif k in _AUDIT_REDACT_SCALARS:
            out[k] = redact(str(v)) if v else ""
        else:
            out[k] = v
    return out
