"""WIP74 privileged setup-configuration workflow contract."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_workflow_spec_exists():
    p=ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md"
    assert p.exists()
    text=p.read_text(encoding="utf-8")
    assert "PENDING_APPROVAL" in text
    assert "APPROVE, REJECT, or ROLLBACK" in text


def test_sensitive_url_settings_are_in_scope():
    text=(ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md").read_text(encoding="utf-8")
    assert "Deployment URL" in text
    assert "Admin URL override" in text
    assert "Public/Base URL" in text


def test_audit_and_notification_are_mandatory():
    text=(ROOT/"WEB_CLOSURE_WIP74_SETUP_CONFIG_PRIVILEGED_CHANGE_WORKFLOW.md").read_text(encoding="utf-8")
    assert "Super Admin is notified immediately" in text
    assert "Every transition is audited" in text
