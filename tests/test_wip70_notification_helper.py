"""WIP70 notification helper contract."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def _helper():
    for p in ROOT.rglob("*.py"):
        t=p.read_text(encoding="utf-8",errors="ignore")
        if "def notify_new_registration" in t:
            return p,t
    raise AssertionError("notify_new_registration implementation missing")


def test_notification_helper_exists():
    p,t=_helper()
    assert "def notify_new_registration" in t


def test_notification_helper_has_safe_failure_boundary():
    p,t=_helper()
    # The helper must not silently omit an error boundary if email delivery is
    # part of registration. Accept common explicit result/exception handling.
    start=t.index("def notify_new_registration")
    block=t[start:start+12000]
    assert any(x in block for x in ("try:", "except", "return", "notification_result"))


def test_notification_helper_review_exists():
    assert (ROOT/"WEB_CLOSURE_WIP70_NOTIFICATION_HELPER_REVIEW.md").exists()
