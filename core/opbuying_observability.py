"""Stable import surface for stock/index long-running bots.

Submodules stay small and testable; this module re-exports them so entry
points can depend on one path when wiring metrics, audit, and soft-reload.
"""

from __future__ import annotations

from core.config_audit_log import append_soft_reload_audit_diff, format_config_audit_log_line
from core.metrics_plaintext import format_bot_metrics_plaintext
from core.soft_reload_common import (
    apply_safe_key_patch,
    ignored_keys_warning,
    partition_soft_reload_changes,
    soft_reload_diff_entry,
)

__all__ = [
    "append_soft_reload_audit_diff",
    "apply_safe_key_patch",
    "format_bot_metrics_plaintext",
    "format_config_audit_log_line",
    "ignored_keys_warning",
    "partition_soft_reload_changes",
    "soft_reload_diff_entry",
]
