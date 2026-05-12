import pytest

from core.soft_reload_common import (
    apply_safe_key_patch,
    partition_soft_reload_changes,
    soft_reload_diff_entry,
)


def test_partition_soft_reload_changes():
    old = {"A": 1, "B": 2, "IMM": 0}
    new = {"A": 1, "B": 3, "IMM": 9, "X": 1}
    imm = frozenset({"IMM"})
    safe = frozenset({"A", "B"})
    changed, blocked, ignored = partition_soft_reload_changes(old, new, imm, safe)
    assert set(changed) == {"B", "IMM", "X"}
    assert blocked == ["IMM"]
    assert set(ignored) == {"X"}


def test_soft_reload_diff_entry():
    seg, row = soft_reload_diff_entry("K", 1, 2)
    assert seg == "K:1→2"
    assert row == {"key": "K", "old": 1, "new": 2}


def test_apply_safe_key_patch_mutates_and_returns():
    old: dict = {"a": 1, "b": 2, "c": 3}
    new = {"a": 9, "b": 2, "d": 4}
    safe = frozenset({"a", "b", "d"})
    reloaded, diff_log = apply_safe_key_patch(old, new, safe)
    # Same as in-process soft reload: safe keys may be introduced from overlay when missing in cfg.
    assert old == {"a": 9, "b": 2, "c": 3, "d": 4}
    assert set(reloaded) == {"a:1→9", "d:None→4"}
    assert {tuple(sorted(d.items())) for d in diff_log} == {
        (("key", "a"), ("new", 9), ("old", 1)),
        (("key", "d"), ("new", 4), ("old", None)),
    }


@pytest.mark.parametrize(
    ("key", "old", "new", "expected_seg"),
    [
        ("SCAN_INTERVAL", 60, 45, "SCAN_INTERVAL:60→45"),
        ("FLAG", False, True, "FLAG:False→True"),
    ],
)
def test_soft_reload_diff_entry_param(key, old, new, expected_seg):
    seg, _row = soft_reload_diff_entry(key, old, new)
    assert seg == expected_seg
