"""Unit tests for core.config_helpers."""

from __future__ import annotations

import base64

from core.config_helpers import decode_if_b64, deep_merge_dict, normalize_tg_trade_patterns, redact


def test_decode_if_b64_roundtrip():
    raw = "secret-token"
    enc = "b64:" + base64.b64encode(raw.encode()).decode()
    assert decode_if_b64(enc) == raw
    assert decode_if_b64("") == ""
    assert decode_if_b64(None) is None


def test_redact_short_and_long():
    assert redact("ab") == "***"
    assert redact("abcdefghij") == "ab********"


def test_deep_merge_dict_nested():
    base = {"a": 1, "gui": {"x": 1, "y": 2}}
    overlay = {"gui": {"y": 9}, "b": 2}
    assert deep_merge_dict(base, overlay) == {"a": 1, "gui": {"x": 1, "y": 9}, "b": 2}
    assert deep_merge_dict(base, None) == base


def test_normalize_tg_patterns_custom_vs_default():
    defaults = ("A", "B")
    assert normalize_tg_trade_patterns({}, defaults) == defaults
    assert normalize_tg_trade_patterns({"TG_TRADE_CRITICAL_PATTERNS": [" x ", ""]}, defaults) == ("x",)
