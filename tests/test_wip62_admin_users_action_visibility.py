"""WIP62 regression tests for Admin Users action visibility and interaction."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_admin_users_table_has_horizontal_scroll_containment():
    text=(ROOT/"templates/enterprise/admin_users.html").read_text(encoding="utf-8")
    assert ".admin-users-table-wrap" in text
    assert "overflow-x: auto" in text


def test_actions_are_sticky_and_clickable():
    text=(ROOT/"templates/enterprise/admin_users.html").read_text(encoding="utf-8")
    assert "th:last-child, .admin-users-table td:last-child" in text
    assert "data-action=\"view-user\"" in text
    assert "data-action=\"open-edit-modal\"" in text
    assert "data-action=\"delete-user\"" in text
    assert "data-action=\"view-user\"} viewUser" not in text


def test_dynamic_action_delegation_exists():
    text=(ROOT/"templates/enterprise/admin_users.html").read_text(encoding="utf-8")
    assert "permissionsTableBody').addEventListener('click'" in text
    assert "btn.dataset.action === 'view-user'" in text
    assert "viewUser(username)" in text


def test_column_header_filters_are_wired():
    text=(ROOT/"templates/enterprise/admin_users.html").read_text(encoding="utf-8")
    for field in ("colFilterUser","colFilterRole","colFilterSignalStatus","colFilterTier",
                  "colFilterCategory","colFilterQuota","colFilterChannel"):
        assert f'id="{field}"' in text
        assert field in text
    assert "renderPermissionRows" in text
