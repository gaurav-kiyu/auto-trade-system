"""Shared soft-reload primitives for long-running stock/index bots.


__all__ = [
    "apply_safe_key_patch",
    "ignored_keys_warning",
    "partition_soft_reload_changes",
    "soft_reload_diff_entry",
]

Keeps change classification and diff-entry shape identical across processes
without pulling in logging, globals, or bot-specific _SAFE_RELOAD_KEY sets.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Set
from typing import Any

__all__ = [
    "apply_safe_key_patch",
    "ignored_keys_warning",
    "partition_soft_reload_changes",
    "soft_reload_diff_entry",
]


def partition_soft_reload_changes(
    old_cfg: Mapping[str, Any],
    new_cfg: Mapping[str, Any],
    immutable_keys: Set[str],
    safe_reload_keys: Set[str],
) -> tuple[list[str], list[str], list[str]]:
    """Return ``(changed, blocked, ignored)`` key lists in stable scan order of *new_cfg* keys."""
    changed = [k for k in new_cfg if new_cfg[k] != old_cfg.get(k)]
    blocked = [k for k in changed if k in immutable_keys]
    ignored = [k for k in changed if k not in safe_reload_keys and k not in immutable_keys]
    return changed, blocked, ignored


def soft_reload_diff_entry(key: str, old: Any, new: Any) -> tuple[str, dict[str, Any]]:
    """Human summary segment plus structured diff row for logs / audit."""
    return f"{key}:{old}→{new}", {"key": key, "old": old, "new": new}


def apply_safe_key_patch(
    old_cfg: MutableMapping[str, Any],
    new_cfg: Mapping[str, Any],
    safe_reload_keys: Set[str],
    validator_fn: Callable[[MutableMapping[str, Any]], list[str]] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Mutate *old_cfg* for keys in *safe_reload_keys* when *new_cfg* differs (including new keys).

    *validator_fn*, if provided, is called with a copy of the merged config before committing.
    If it returns a non-empty error list the patch is rejected and diff_log contains a rejection entry.
    """
    reloaded: list[str] = []
    diff_log: list[dict[str, Any]] = []
    candidate: dict[str, Any] = {}
    for k in safe_reload_keys:
        if k in new_cfg and new_cfg[k] != old_cfg.get(k):
            candidate[k] = new_cfg[k]
    if not candidate:
        return reloaded, diff_log
    if validator_fn is not None:
        merged_preview = dict(old_cfg)
        merged_preview.update(candidate)
        errors = validator_fn(merged_preview)
        if errors:
            diff_log.append({"rejected": True, "errors": errors, "candidate_keys": list(candidate)})
            return reloaded, diff_log
    for k, new_val in candidate.items():
        old_val = old_cfg.get(k)
        old_cfg[k] = new_val
        seg, row = soft_reload_diff_entry(k, old_val, new_val)
        reloaded.append(seg)
        diff_log.append(row)
    return reloaded, diff_log


def ignored_keys_warning(ignored: list[str]) -> str | None:
    """Return a human-readable warning when config keys were changed but silently skipped.

    Call this after partition_soft_reload_changes() and log the result at WARNING
    level so operators know a restart is required for those keys to take effect.

    Returns None when *ignored* is empty (no warning needed).

    Example::

        changed, blocked, ignored = partition_soft_reload_changes(old, new, immutable, safe)
        msg = ignored_keys_warning(ignored)
        if msg:
            log.warning(msg)
    """
    if not ignored:
        return None
    keys = ", ".join(sorted(ignored))
    return (
        f"Soft-reload: {len(ignored)} key(s) changed in config but NOT applied "
        f"(restart required): {keys}"
    )
