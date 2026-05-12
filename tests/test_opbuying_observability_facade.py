"""Facade must stay importable and aligned with subsystem modules."""

from __future__ import annotations

import importlib


def test_opbuying_observability_reexports_match_submodules():
    facade = importlib.import_module("core.opbuying_observability")
    mp = importlib.import_module("core.metrics_plaintext")
    ca = importlib.import_module("core.config_audit_log")
    sr = importlib.import_module("core.soft_reload_common")

    assert facade.format_bot_metrics_plaintext is mp.format_bot_metrics_plaintext
    assert facade.append_soft_reload_audit_diff is ca.append_soft_reload_audit_diff
    assert facade.format_config_audit_log_line is ca.format_config_audit_log_line
    assert facade.partition_soft_reload_changes is sr.partition_soft_reload_changes
    assert facade.apply_safe_key_patch is sr.apply_safe_key_patch
    assert facade.soft_reload_diff_entry is sr.soft_reload_diff_entry
