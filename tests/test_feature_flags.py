"""Tests for Feature Flags module (core/feature_flags.py)."""

from __future__ import annotations

import pytest
from core.feature_flags import (
    FlagEvaluation,
    get_feature_flag_manager,
    reset_feature_flag_manager,
)


@pytest.fixture(autouse=True)
def reset_flags(tmp_path, monkeypatch):
    reset_feature_flag_manager()
    # Isolate JSON persistence to a per-test temp path. The manager writes
    # registered flags to json/feature_flags.json on every register, and the
    # reset only nulls the singleton — without this isolation flags registered
    # by earlier tests (and any real runtime store) leak into later tests.
    monkeypatch.setattr("core.feature_flags.Path", lambda *a: tmp_path / "flags.json")
    yield
    reset_feature_flag_manager()


# ── Registration ──────────────────────────────────────────────────────────


class TestRegistration:
    def test_register_flag(self):
        fm = get_feature_flag_manager()
        flag = fm.register_flag("test_feature", default=False, description="A test flag")
        assert flag.key == "test_feature"
        assert flag.default is False
        assert flag.description == "A test flag"

    def test_register_flag_default_enabled(self):
        fm = get_feature_flag_manager()
        flag = fm.register_flag("enabled_feature", default=True)
        assert flag.default is True
        assert flag.rollout_pct == 100.0

    def test_register_flag_with_owners_and_tags(self):
        fm = get_feature_flag_manager()
        flag = fm.register_flag("ml_v2", default=False, owners=["ml-team"], tags=["machine-learning", "experimental"])
        assert "ml-team" in flag.owners
        assert "machine-learning" in flag.tags

    def test_get_flag(self):
        fm = get_feature_flag_manager()
        fm.register_flag("my_flag", default=True)
        flag = fm.get_flag("my_flag")
        assert flag is not None
        assert flag.key == "my_flag"
        assert flag.default is True

    def test_get_flag_unknown(self):
        fm = get_feature_flag_manager()
        flag = fm.get_flag("nonexistent")
        assert flag is None

    def test_unregister_flag(self):
        fm = get_feature_flag_manager()
        fm.register_flag("temp_flag")
        assert fm.get_flag("temp_flag") is not None
        fm.unregister_flag("temp_flag")
        assert fm.get_flag("temp_flag") is None

    def test_unregister_flag_unknown(self):
        fm = get_feature_flag_manager()
        assert fm.unregister_flag("nonexistent") is False

    def test_list_flags(self):
        fm = get_feature_flag_manager()
        fm.register_flag("flag_a", default=True)
        fm.register_flag("flag_b", default=False)
        flags = fm.list_flags()
        assert len(flags) == 2

    def test_list_flags_filtered_by_tag(self):
        fm = get_feature_flag_manager()
        fm.register_flag("flag_a", default=True, tags=["alpha"])
        fm.register_flag("flag_b", default=False, tags=["beta"])
        flags = fm.list_flags(tag="alpha")
        assert len(flags) == 1
        assert flags[0].key == "flag_a"


# ── Toggle Control ────────────────────────────────────────────────────────


class TestToggleControl:
    def test_set_enabled(self):
        fm = get_feature_flag_manager()
        fm.register_flag("my_flag", default=False)
        fm.set_enabled("my_flag", True)
        assert fm.get_flag("my_flag").default is True

    def test_set_enabled_unknown(self):
        fm = get_feature_flag_manager()
        assert fm.set_enabled("nonexistent", True) is False

    def test_set_rollout(self):
        fm = get_feature_flag_manager()
        fm.register_flag("rolled", default=False)
        fm.set_rollout("rolled", 50.0)
        flag = fm.get_flag("rolled")
        assert flag.rollout_pct == 50.0
        assert flag.default is True

    def test_set_rollout_zero(self):
        fm = get_feature_flag_manager()
        fm.register_flag("disabled_for_all", default=True)
        fm.set_rollout("disabled_for_all", 0.0)
        assert fm.get_flag("disabled_for_all").default is False

    def test_set_rollout_clamped(self):
        fm = get_feature_flag_manager()
        fm.register_flag("clamped", default=False)
        fm.set_rollout("clamped", -10.0)
        assert fm.get_flag("clamped").rollout_pct == 0.0

    def test_environment_override(self):
        fm = get_feature_flag_manager()
        fm.set_environment("production")
        fm.register_flag("prod_feature", default=False)
        fm.set_environment_override("prod_feature", "production", True)
        assert fm.get_flag("prod_feature").environment_overrides.get("production") is True


# ── Evaluation ────────────────────────────────────────────────────────────


class TestEvaluation:
    def test_is_enabled_default_true(self):
        fm = get_feature_flag_manager()
        fm.register_flag("enabled", default=True)
        assert fm.is_enabled("enabled") is True

    def test_is_enabled_default_false(self):
        fm = get_feature_flag_manager()
        fm.register_flag("disabled", default=False)
        assert fm.is_enabled("disabled") is False

    def test_is_enabled_unknown(self):
        fm = get_feature_flag_manager()
        assert fm.is_enabled("unknown") is False

    def test_is_enabled_rollout_bucket(self):
        fm = get_feature_flag_manager()
        fm.register_flag("partial", default=True)
        fm.set_rollout("partial", 0.0)  # 0% enabled
        # 0% rollout disables the flag entirely (default derived from rollout),
        # regardless of whether a user_id is supplied.
        assert fm.is_enabled("partial") is False

    def test_is_enabled_rollout_with_user(self):
        fm = get_feature_flag_manager()
        fm.register_flag("partial_user", default=True)
        fm.set_rollout("partial_user", 0.0)
        # With user_id, rollout check applies
        assert fm.is_enabled("partial_user", user_id="test_user") is False

    def test_is_enabled_context_force_disable(self):
        fm = get_feature_flag_manager()
        fm.register_flag("forced", default=True)
        assert fm.is_enabled("forced", context={"force_disable": True}) is False

    def test_is_enabled_context_force_enable(self):
        fm = get_feature_flag_manager()
        fm.register_flag("forced2", default=False)
        assert fm.is_enabled("forced2", context={"force_enable": True}) is True

    def test_environment_override_takes_precedence(self):
        fm = get_feature_flag_manager()
        fm.set_environment("staging")
        fm.register_flag("staging_feature", default=False)
        fm.set_environment_override("staging_feature", "staging", True)
        assert fm.is_enabled("staging_feature") is True

    def test_evaluate_returns_detailed_info(self):
        fm = get_feature_flag_manager()
        fm.register_flag("eval_flag", default=True)
        result = fm.evaluate("eval_flag")
        assert isinstance(result, FlagEvaluation)
        assert result.key == "eval_flag"
        assert result.enabled is True

    def test_evaluate_unknown(self):
        fm = get_feature_flag_manager()
        result = fm.evaluate("unknown")
        assert result.enabled is False
        assert result.reason == "unknown_flag"


# ── Statistics ────────────────────────────────────────────────────────────


class TestStats:
    def test_get_stats_empty(self):
        fm = get_feature_flag_manager()
        stats = fm.get_stats()
        assert stats["total_flags"] == 0

    def test_get_stats_with_flags(self):
        fm = get_feature_flag_manager()
        fm.register_flag("flag_a", default=True)
        fm.register_flag("flag_b", default=False)
        stats = fm.get_stats()
        assert stats["total_flags"] == 2
        assert stats["enabled"] == 1
        assert stats["disabled"] == 1

    def test_get_stats_partial_rollout(self):
        fm = get_feature_flag_manager()
        fm.register_flag("partial_flag", default=True)
        fm.set_rollout("partial_flag", 50.0)
        stats = fm.get_stats()
        assert stats["partial_rollouts"] == 1

    def test_bucket_user_deterministic(self):
        fm = get_feature_flag_manager()
        result1 = fm._bucket_user("test_flag", "user_1")
        result2 = fm._bucket_user("test_flag", "user_1")
        assert result1 == result2

    def test_bucket_user_different(self):
        fm = get_feature_flag_manager()
        result1 = fm._bucket_user("test_flag", "user_1")
        result2 = fm._bucket_user("test_flag", "user_2")
        # Different users may get different buckets
        assert isinstance(result1, float)
        assert isinstance(result2, float)


# ── Singleton ─────────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_returns_same_instance(self):
        fm1 = get_feature_flag_manager()
        fm2 = get_feature_flag_manager()
        assert fm1 is fm2

    def test_reset_creates_new_instance(self):
        fm1 = get_feature_flag_manager()
        reset_feature_flag_manager()
        fm2 = get_feature_flag_manager()
        assert fm1 is not fm2
