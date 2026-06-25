"""
Fuzz Testing for Data Parsing Modules.

Uses Hypothesis to generate random malformed/near-valid inputs for:
  - Option chain JSON parsing
  - Config bootstrap and validation
  - Market data edge cases

All tests verify that modules gracefully handle unexpected input without crashing.
"""

from __future__ import annotations

import json
from typing import Any

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.config_bootstrap import diff_configs, classify_change_risk, ConfigChange
from core.option_chain_json import option_chain_has_rows, option_chain_records


# ==============================================================================
# Hypothesis Strategies — Generate Malformed / Edge-Case Inputs
# ==============================================================================

# Generate arbitrary JSON-like objects (dicts, lists, strings, numbers, nulls)
any_json = st.recursive(
    st.none() | st.booleans() | st.floats(allow_nan=False) | st.text(max_size=50),
    lambda children: st.lists(children, max_size=5)
    | st.dictionaries(st.text(max_size=10), children, max_size=5),
    max_leaves=10,
)

# Generate option-chain-like payloads with random structures
option_chain_payload = st.dictionaries(
    st.text(max_size=20),
    st.one_of(
        st.none(),
        st.just(None),
        st.dictionaries(st.text(max_size=20), any_json, max_size=5),
        st.lists(any_json, max_size=5),
    ),
    max_size=8,
    min_size=0,
)

# Generate config-like dicts
config_dict = st.dictionaries(
    st.text(min_size=1, max_size=40),
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(),
        st.floats(allow_nan=False),
        st.text(max_size=100),
        st.lists(st.integers() | st.text(max_size=20), max_size=10),
    ),
    max_size=20,
    min_size=0,
)

# Generate config keys with various risk levels
config_key = st.text(min_size=1, max_size=30).map(lambda s: s.upper())

# Generate random config change values
config_value = st.one_of(
    st.none(),
    st.integers(min_value=-1000, max_value=10000),
    st.floats(min_value=-0.5, max_value=0.5, allow_nan=False),
    st.booleans(),
    st.text(max_size=50),
    st.lists(st.integers(min_value=0, max_value=100), max_size=5),
)


# ==============================================================================
# Option Chain JSON — Fuzz Tests
# ==============================================================================

class TestOptionChainFuzz:
    """Fuzz tests for option chain JSON parsing — must never crash."""

    @given(option_chain_payload)
    @settings(max_examples=200)
    def test_option_chain_records_never_crashes(self, payload: dict[str, Any]):
        """option_chain_records should never crash on any dict input."""
        result = option_chain_records(payload)
        assert isinstance(result, dict)

    @given(any_json)
    @settings(max_examples=200)
    def test_option_chain_records_non_dict_input(self, payload: Any):
        """option_chain_records should handle non-dict input gracefully."""
        if isinstance(payload, dict):
            payload = payload  # already covered
        result = option_chain_records(payload)
        assert isinstance(result, dict)

    @given(option_chain_payload)
    @settings(max_examples=200)
    def test_option_chain_has_rows_never_crashes(self, payload: dict[str, Any]):
        """option_chain_has_rows should never crash on any dict input."""
        result = option_chain_has_rows(payload)
        assert isinstance(result, bool)

    @given(any_json)
    @settings(max_examples=200)
    def test_option_chain_has_rows_non_dict(self, payload: Any):
        """option_chain_has_rows should handle non-dict input."""
        if isinstance(payload, dict):
            return  # covered
        result = option_chain_has_rows(payload)
        assert isinstance(result, bool)

    @given(st.text(max_size=500))
    @settings(max_examples=100)
    def test_option_chain_from_json_string(self, raw_json: str):
        """option_chain functions should handle arbitrary JSON strings safely."""
        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            return  # Invalid JSON is expected to fail json.loads, not our functions
        if isinstance(data, dict):
            result = option_chain_records(data)
            assert isinstance(result, dict)
            result2 = option_chain_has_rows(data)
            assert isinstance(result2, bool)

    def test_option_chain_null_records_edge(self):
        """Null records field should be handled."""
        assert option_chain_records({"records": None}) == {}
        assert option_chain_has_rows({"records": None}) is False

    def test_option_chain_missing_records(self):
        """Missing records field should return empty dict."""
        assert option_chain_records({}) == {}
        assert option_chain_has_rows({}) is False

    def test_option_chain_empty_data(self):
        """Empty data array should return False for has_rows."""
        payload = {"records": {"data": [], "expiryDates": []}}
        assert option_chain_has_rows(payload) is False
        assert option_chain_records(payload) == {"data": [], "expiryDates": []}

    def test_option_chain_wrong_types(self):
        """Non-dict records value should return empty dict."""
        for bad_value in [123, "string", True, [1, 2, 3]]:
            assert option_chain_records({"records": bad_value}) == {}
            assert option_chain_has_rows({"records": bad_value}) is False

    def test_option_chain_nested_edge_cases(self):
        """Edge cases for deeply nested option chain data."""
        # Very large OI values
        payload = {"records": {"data": [{"strikePrice": 25000, "oi": 999999999}], "expiryDates": ["25APR"]}}
        assert option_chain_has_rows(payload) is True

        # Zero strike price
        payload = {"records": {"data": [{"strikePrice": 0, "oi": 1000}], "expiryDates": ["25APR"]}}
        assert option_chain_has_rows(payload) is True

        # Negative strike price (edge case from market)
        payload = {"records": {"data": [{"strikePrice": -1, "oi": 1000}], "expiryDates": ["25APR"]}}
        rec = option_chain_records(payload)
        assert isinstance(rec, dict)


# ==============================================================================
# Config Bootstrap — Fuzz Tests
# ==============================================================================

class TestConfigFuzz:
    """Fuzz tests for config bootstrap — must never crash."""

    @given(config_key)
    @settings(max_examples=100)
    def test_classify_change_risk_never_crashes(self, key: str):
        """classify_change_risk should handle any key string."""
        assume(len(key) > 0)
        result = classify_change_risk(key)
        assert result in ("CRITICAL", "HIGH", "NORMAL")

    @given(config_key)
    @settings(max_examples=50)
    def test_classify_change_risk_empty_key(self, key: str):
        """classify_change_risk should handle empty or edge keys."""
        result = classify_change_risk(key)
        assert result in ("CRITICAL", "HIGH", "NORMAL")

    def test_classify_change_risk_critical_keys(self):
        """Known critical keys should be classified as CRITICAL."""
        critical = ["MAX_DAILY_LOSS", "MAX_DRAWDOWN", "MAX_OPEN", "EXECUTION_MODE"]
        for key in critical:
            assert classify_change_risk(key) == "CRITICAL", f"{key} should be CRITICAL"

    def test_classify_change_risk_high_keys(self):
        """Known high-risk keys should be classified as HIGH."""
        high = ["SCAN_INTERVAL", "BASE_CAPITAL", "PORTFOLIO_MAX_SL_RISK_PCT"]
        for key in high:
            assert classify_change_risk(key) == "HIGH", f"{key} should be HIGH"

    def test_classify_change_risk_normal_keys(self):
        """Unknown keys should be classified as NORMAL."""
        assert classify_change_risk("UNKNOWN_KEY") == "NORMAL"
        assert classify_change_risk("GUI_THEME") == "NORMAL"

    @given(config_dict, config_dict)
    @settings(max_examples=50)
    def test_diff_configs_never_crashes(self, old_cfg: dict, new_cfg: dict):
        """diff_configs should handle any config dicts."""
        changes = diff_configs(old_cfg, new_cfg, changed_by="test")
        assert isinstance(changes, list)
        for c in changes:
            assert isinstance(c, ConfigChange)
            assert isinstance(c.key, str)
            assert c.risk_level in ("CRITICAL", "HIGH", "NORMAL")
            assert c.changed_by == "test"

    def test_diff_configs_identical(self):
        """Identical configs should produce no changes."""
        cfg = {"CONFIG_VAL_1": 1, "CONFIG_VAL_2": "hello", "CONFIG_VAL_3": True}
        changes = diff_configs(cfg, cfg)
        assert len(changes) == 0

    def test_diff_configs_added_removed(self):
        """Added and removed keys should be detected."""
        old = {"CONFIG_A": 1, "CONFIG_B": "old"}
        new = {"CONFIG_A": 1, "CONFIG_C": "new"}
        changes = diff_configs(old, new, changed_by="test")
        keys = {c.key for c in changes}
        assert "CONFIG_B" in keys  # removed
        assert "CONFIG_C" in keys  # added
        assert "CONFIG_A" not in keys  # unchanged

    def test_diff_configs_none_values(self):
        """None values should be handled."""
        changes = diff_configs({"CONFIG_NONE": None}, {"CONFIG_NONE": "value"})
        assert len(changes) == 1

    def test_diff_configs_empty(self):
        """Empty configs should work."""
        changes = diff_configs({}, {})
        assert len(changes) == 0

    def test_diff_configs_secrets_redacted(self):
        """Secret keys should be redacted from diff output."""
        changes = diff_configs({"api_key": "old_secret"}, {"api_key": "new_secret"})
        # Secret-containing keys should be skipped
        assert len(changes) == 0

    def test_diff_configs_type_changes(self):
        """Type changes should be detected."""
        changes = diff_configs({"CONFIG_TYPE": 1}, {"CONFIG_TYPE": "1"})
        assert len(changes) == 1
        assert changes[0].old_value == 1
        assert changes[0].new_value == "1"

    def test_diff_configs_critical_change_detected(self):
        """Changes to critical keys should have CRITICAL risk level."""
        changes = diff_configs({"MAX_DAILY_LOSS": -600}, {"MAX_DAILY_LOSS": -1000})
        assert len(changes) == 1
        assert changes[0].risk_level == "CRITICAL"


# ==============================================================================
# Edge Case Tests for Config Bootstrap
# ==============================================================================

class TestConfigEdgeCases:
    """Systematic edge case tests for config bootstrap."""

    def test_apply_env_overrides_empty(self):
        """Empty env prefix should apply nothing."""
        from core.config_bootstrap import apply_env_overrides
        count = apply_env_overrides({"KEY": 1}, {"KEY": 1}, prefix="")
        assert count == 0

    def test_apply_env_overrides_type_coercion_bool(self):
        """Boolean env override should coerce string to bool."""
        import os
        from core.config_bootstrap import apply_env_overrides
        cfg = {"ENABLED": True}
        os.environ["OPBUYING_ENABLED"] = "false"
        try:
            count = apply_env_overrides(cfg, {"ENABLED": True})
            assert count == 1
            assert cfg["ENABLED"] is False
        finally:
            os.environ.pop("OPBUYING_ENABLED", None)

    def test_apply_env_overrides_type_coercion_int(self):
        """Integer env override should coerce string to int."""
        import os
        from core.config_bootstrap import apply_env_overrides
        cfg = {"COUNT": 42}
        os.environ["OPBUYING_COUNT"] = "100"
        try:
            count = apply_env_overrides(cfg, {"COUNT": 42})
            assert count == 1
            assert cfg["COUNT"] == 100
        finally:
            os.environ.pop("OPBUYING_COUNT", None)

    def test_apply_env_overrides_type_coercion_float(self):
        """Float env override should coerce string to float."""
        import os
        from core.config_bootstrap import apply_env_overrides
        cfg = {"RATE": 0.5}
        os.environ["OPBUYING_RATE"] = "0.75"
        try:
            count = apply_env_overrides(cfg, {"RATE": 0.5})
            assert count == 1
            assert cfg["RATE"] == 0.75
        finally:
            os.environ.pop("OPBUYING_RATE", None)

    def test_apply_env_overrides_no_match(self):
        """Non-matching env vars should be ignored."""
        import os
        from core.config_bootstrap import apply_env_overrides
        cfg = {"KEY": "value"}
        os.environ["OTHER_VAR"] = "value"
        try:
            count = apply_env_overrides(cfg, {"KEY": "value"})
            assert count == 0
        finally:
            os.environ.pop("OTHER_VAR", None)

    def test_config_change_dataclass_frozen(self):
        """ConfigChange should be a frozen dataclass."""
        from datetime import datetime
        change = ConfigChange(
            key="TEST_KEY",
            old_value=1,
            new_value=2,
            changed_at=datetime.now().isoformat(),
            changed_by="test",
            risk_level="NORMAL",
        )
        assert change.key == "TEST_KEY"
        assert change.risk_level == "NORMAL"
        # Verify it's hashable (frozen)
        d = {change: True}
        assert d[change] is True

    def test_config_change_json_serializable(self):
        """ConfigChange fields should be JSON-serializable."""
        import json
        from datetime import datetime
        change = ConfigChange(
            key="TEST_KEY",
            old_value=42,
            new_value=100,
            changed_at=datetime.now().isoformat(),
            changed_by="test",
            risk_level="HIGH",
        )
        d = {
            "key": change.key,
            "old_value": change.old_value,
            "new_value": change.new_value,
            "risk_level": change.risk_level,
        }
        json.dumps(d)  # Must not raise
