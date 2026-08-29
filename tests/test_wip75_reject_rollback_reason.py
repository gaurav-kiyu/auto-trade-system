"""WIP75 mandatory reason contract for reject/rollback."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_reason_requirement_is_documented():
    p=ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md"
    text=p.read_text(encoding="utf-8")
    assert "Mandatory reason requirement" in text
    assert "REJECT" in text and "ROLLBACK" in text
    assert "Minimum length: 10 characters." in text


def test_reason_is_server_enforced():
    text=(ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md").read_text(encoding="utf-8")
    assert "The server must enforce the requirement" in text


def test_reason_is_audited():
    text=(ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md").read_text(encoding="utf-8")
    assert "reason is stored with the action" in text
    assert "audit trail" in text
