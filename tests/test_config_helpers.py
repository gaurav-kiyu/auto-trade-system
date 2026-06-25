"""Tests for core/config_helpers.py - shared config utilities.

Covers:
- decode_if_b64 (b64 prefix, no prefix, non-string)
- redact (shows first ~20%, masks rest)
- deep_merge_dict (nested merge, overlay None, non-dict values)
- normalize_tg_trade_patterns (list, missing, empty)
- build_audit_config_snapshot (redact sub-objects, scalars, omit _NOTE keys)
"""
from __future__ import annotations


from core.config_helpers import (
    _AUDIT_REDACT_SCALARS,
    _AUDIT_REDACT_SUBOBJECTS,
    build_audit_config_snapshot,
    decode_if_b64,
    deep_merge_dict,
    normalize_tg_trade_patterns,
    redact,
)


# =============================================================================
# decode_if_b64 Tests
# =============================================================================

class TestDecodeIfB64:
    def test_b64_decodes(self):
        import base64
        encoded = base64.b64encode(b"my_secret_token").decode()
        result = decode_if_b64(f"b64:{encoded}")
        assert result == "my_secret_token"

    def test_no_prefix_returns_as_is(self):
        assert decode_if_b64("hello") == "hello"

    def test_non_string_returns_as_is(self):
        assert decode_if_b64(42) == 42
        assert decode_if_b64(None) is None
        assert decode_if_b64([1, 2, 3]) == [1, 2, 3]

    def test_empty_string_returns_empty(self):
        assert decode_if_b64("") == ""

    def test_b64_invalid_returns_original(self):
        """If b64: prefix but invalid base64, return as-is."""
        result = decode_if_b64("b64:!!!invalid!!!")
        assert result == "b64:!!!invalid!!!"


# =============================================================================
# redact Tests
# =============================================================================

class TestRedact:
    def test_redacts_long_string(self):
        result = redact("abcdefghij")  # 10 chars, keep = 2
        assert result.startswith("ab")
        assert result.endswith("*" * 8)
        assert len(result) == 10

    def test_short_string(self):
        result = redact("ab")  # len < 4
        assert result == "***"

    def test_empty_string(self):
        assert redact("") == "***"

    def test_very_long_string(self):
        s = "a" * 100
        result = redact(s)
        # keep = max(2, 100 // 5) = max(2, 20) = 20
        assert result == "a" * 20 + "*" * 80


# =============================================================================
# deep_merge_dict Tests
# =============================================================================

class TestDeepMergeDict:
    def test_basic_merge(self):
        base = {"a": 1, "b": 2}
        overlay = {"b": 3, "c": 4}
        result = deep_merge_dict(base, overlay)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"db": {"host": "localhost", "port": 5432}}
        overlay = {"db": {"port": 5433, "user": "admin"}}
        result = deep_merge_dict(base, overlay)
        assert result["db"]["host"] == "localhost"
        assert result["db"]["port"] == 5433
        assert result["db"]["user"] == "admin"

    def test_overlay_none_returns_base(self):
        base = {"a": 1}
        result = deep_merge_dict(base, None)
        assert result == {"a": 1}

    def test_overlay_non_dict_returns_base(self):
        base = {"a": 1}
        result = deep_merge_dict(base, "not dict")
        assert result == {"a": 1}

    def test_overlay_overwrites_base_non_dict(self):
        """If base has non-dict and overlay has non-dict for same key, overlay wins."""
        base = {"a": {"nested": "val"}}
        overlay = {"a": "scalar"}
        result = deep_merge_dict(base, overlay)
        assert result["a"] == "scalar"

    def test_empty_base(self):
        base = {}
        overlay = {"a": 1}
        result = deep_merge_dict(base, overlay)
        assert result == {"a": 1}

    def test_empty_overlay(self):
        base = {"a": 1}
        result = deep_merge_dict(base, {})
        assert result == {"a": 1}


# =============================================================================
# normalize_tg_trade_patterns Tests
# =============================================================================

class TestNormalizeTgTradePatterns:
    def test_from_list(self):
        cfg = {"TG_TRADE_CRITICAL_PATTERNS": ["BUY", "SELL", " EXIT "]}
        result = normalize_tg_trade_patterns(cfg, ("DEFAULT",))
        assert result == ("BUY", "SELL", "EXIT")

    def test_empty_list_falls_back(self):
        cfg = {"TG_TRADE_CRITICAL_PATTERNS": []}
        result = normalize_tg_trade_patterns(cfg, ("DEFAULT", "PATTERN"))
        assert result == ("DEFAULT", "PATTERN")

    def test_missing_key_falls_back(self):
        cfg = {}
        result = normalize_tg_trade_patterns(cfg, ("SOS", "ENTRY"))
        assert result == ("SOS", "ENTRY")

    def test_non_list_value_falls_back(self):
        cfg = {"TG_TRADE_CRITICAL_PATTERNS": "invalid"}
        result = normalize_tg_trade_patterns(cfg, ("DEFAULT",))
        assert result == ("DEFAULT",)


# =============================================================================
# build_audit_config_snapshot Tests
# =============================================================================

class TestBuildAuditConfigSnapshot:
    def test_full_config(self):
        cfg = {
            "BOT_TOKEN": "secret123",
            "CHAT_ID": "chat456",
            "BROKER_CONFIG": {"api_key": "key123", "secret": "s3cret"},
            "ENVIRONMENT": "production",
            "MAX_DAILY_LOSS": -2000.0,
        }
        snapshot = build_audit_config_snapshot(cfg)
        # BOT_TOKEN should be redacted
        assert snapshot["BOT_TOKEN"] != "secret123"
        assert len(snapshot["BOT_TOKEN"]) > 0
        assert "*" in snapshot["BOT_TOKEN"]
        # CHAT_ID should be redacted
        assert "*" in snapshot["CHAT_ID"]
        # BROKER_CONFIG should be redacted sub-object
        assert snapshot["BROKER_CONFIG"] == {"redacted": True}
        # Other keys should be preserved
        assert snapshot["ENVIRONMENT"] == "production"
        assert snapshot["MAX_DAILY_LOSS"] == -2000.0

    def test_omits_note_keys(self):
        cfg = {
            "_NOTE_comment": "this is a comment",
            "REAL_KEY": "value",
        }
        snapshot = build_audit_config_snapshot(cfg)
        assert "_NOTE_comment" not in snapshot
        assert snapshot["REAL_KEY"] == "value"

    def test_empty_value_handling(self):
        cfg = {"BOT_TOKEN": "", "CHAT_ID": None}
        snapshot = build_audit_config_snapshot(cfg)
        assert snapshot["BOT_TOKEN"] == ""
        assert snapshot["CHAT_ID"] == ""

    def test_redact_subobjects_set(self):
        assert "BROKER_CONFIG" in _AUDIT_REDACT_SUBOBJECTS

    def test_redact_scalars_set(self):
        assert "BOT_TOKEN" in _AUDIT_REDACT_SCALARS
        assert "CHAT_ID" in _AUDIT_REDACT_SCALARS

    def test_flat_dict_output(self):
        cfg = {"SIMPLE_KEY": "simple_value", "NESTED": {"inner": "val"}}
        snapshot = build_audit_config_snapshot(cfg)
        assert snapshot["SIMPLE_KEY"] == "simple_value"
        assert snapshot["NESTED"] == {"inner": "val"}
