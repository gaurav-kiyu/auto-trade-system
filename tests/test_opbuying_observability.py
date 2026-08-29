"""Tests for core/opbuying_observability.py — re-export alias module."""

from __future__ import annotations

from core.config_audit_log import (
    append_soft_reload_audit_diff as _ORIG_APPEND,
)
from core.opbuying_observability import (
    append_soft_reload_audit_diff,
    apply_safe_key_patch,
    format_bot_metrics_plaintext,
    format_config_audit_log_line,
    ignored_keys_warning,
    partition_soft_reload_changes,
    soft_reload_diff_entry,
)
from core.soft_reload_common import (
    apply_safe_key_patch as _ORIG_PATCH,
)


class TestOpbuyingObservability:
    """Verify all re-exports match their source symbols."""

    def test_all_exports_callable(self):
        funcs = [
            append_soft_reload_audit_diff,
            apply_safe_key_patch,
            format_bot_metrics_plaintext,
            format_config_audit_log_line,
            ignored_keys_warning,
            partition_soft_reload_changes,
            soft_reload_diff_entry,
        ]
        for fn in funcs:
            assert callable(fn), f"{getattr(fn, '__name__', fn)} is not callable"

    def test_append_soft_reload_audit_diff_reexported(self):
        assert append_soft_reload_audit_diff is _ORIG_APPEND

    def test_apply_safe_key_patch_reexported(self):
        assert apply_safe_key_patch is _ORIG_PATCH

    def test_ignored_keys_warning_returns_string(self):
        result = ignored_keys_warning(["key1", "key2"])
        assert isinstance(result, str)

    def test_soft_reload_diff_entry_returns_tuple(self):
        result = soft_reload_diff_entry("key", "old", "new")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_partition_soft_reload_changes_returns_tuple(self):
        result = partition_soft_reload_changes({}, {}, set(), set())
        assert isinstance(result, tuple)
        assert len(result) == 3
