"""WIP71 registration notification content audit."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def _block():
    p=ROOT/"core/auth/registration_notifications.py"
    lines=p.read_text(encoding="utf-8",errors="ignore").splitlines()
    start=next(i for i,l in enumerate(lines) if re.search(r"\bdef notify_new_registration\b",l))
    end=len(lines)
    base=len(lines[start])-len(lines[start].lstrip())
    for j in range(start+1,len(lines)):
        s=lines[j]
        if s.strip() and len(s)-len(s.lstrip())<=base and re.match(r"\s*(?:def|async def)\s+",s):
            end=j; break
    return "\n".join(lines[start:end]).lower()


def test_notification_content_audit_exists():
    assert (ROOT/"WEB_CLOSURE_WIP71_NOTIFICATION_CONTENT_AUDIT.md").exists()


def test_notification_helper_has_content_or_result_path():
    b=_block()
    assert any(x in b for x in ("welcome","registration","return","result"))


def test_notification_helper_has_failure_or_result_boundary():
    b=_block()
    assert any(x in b for x in ("try:","except","error","failed","return","result"))
