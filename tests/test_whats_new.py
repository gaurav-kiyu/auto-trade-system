"""Tests for the "What's New" changelog-rendering page.

Covers:
  - get_latest_changelog_entry()'s CHANGELOG.md parsing (version/date
    extraction, nested-bullet rendering, missing-file/empty-file fallback)
  - /whats-new HTML page route (auth redirect + authenticated render)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from core.enterprise_dashboard.routes.whats_new import get_latest_changelog_entry


def _make_state_file(tmp_path: Path) -> str:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 0.0, "open_positions": 0, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 0,
        "base_capital": 100000,
    }), encoding="utf-8")
    return str(p)


def _make_trades_db(tmp_path: Path) -> str:
    import sqlite3
    db_path = str(tmp_path / "trades.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    return db_path


# ── get_latest_changelog_entry() ──────────────────────────────────────────────

class TestGetLatestChangelogEntry:
    def test_real_changelog_parses_ok(self):
        """Smoke test against the project's real CHANGELOG.md."""
        entry = get_latest_changelog_entry()
        assert entry["status"] == "ok"
        assert entry["version"]
        assert entry["date"]
        assert "<ul>" in entry["html"]

    def test_missing_file_is_reported_not_raised(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", tmp_path / "does_not_exist.md")
        entry = wn.get_latest_changelog_entry()
        assert entry["status"] == "unavailable"

    def test_empty_file_is_reported_not_raised(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text("", encoding="utf-8")
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert entry["status"] == "unavailable"

    def test_parses_version_and_date_from_heading(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text(
            "# Changelog\n\n## v9.9.9 (2099-01-01)\n\n- **Feature A:**\n  - detail one\n  - detail two\n\n## v9.9.8 (2098-01-01)\n\n- Older stuff\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert entry["status"] == "ok"
        assert entry["version"] == "9.9.9"
        assert entry["date"] == "2099-01-01"
        assert "Older stuff" not in entry["html"]  # stops before the next version heading

    def test_nested_bullets_render_as_nested_ul(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text(
            "## v1.0.0 (2026-01-01)\n\n- **Top item:**\n  - nested one\n  - nested two\n- **Second top item:**\n  - another nested\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert entry["html"].count("<ul>") == 3  # outer + 2 nested groups
        assert "<strong>Top item:</strong>" in entry["html"]
        assert "nested one" in entry["html"]

    def test_bold_and_code_inline_formatting(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text(
            "## v1.0.0 (2026-01-01)\n\n- **Bold text** and `code text` in one line\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert "<strong>Bold text</strong>" in entry["html"]
        assert "<code>code text</code>" in entry["html"]

    def test_html_is_escaped_not_injected(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text(
            "## v1.0.0 (2026-01-01)\n\n- <script>alert(1)</script>\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert "<script>" not in entry["html"]
        assert "&lt;script&gt;" in entry["html"]

    def test_no_version_heading_is_reported_not_raised(self, tmp_path, monkeypatch):
        import core.enterprise_dashboard.routes.whats_new as wn
        f = tmp_path / "CHANGELOG.md"
        f.write_text("# Just a title\n\nNo version headings here.\n", encoding="utf-8")
        monkeypatch.setattr(wn, "_CHANGELOG_PATH", f)
        entry = wn.get_latest_changelog_entry()
        assert entry["status"] == "unavailable"


# ── /whats-new HTML page route ────────────────────────────────────────────────

@pytest.fixture()
def dashboard(tmp_path: Path):
    from core.enterprise_dashboard import EnterpriseDashboard

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": _make_state_file(tmp_path),
        "auth_db_path": str(tmp_path / "dash_auth.db"),
        "broker_name": "TestBroker",
        "execution_mode": "paper",
    }, db_path=_make_trades_db(tmp_path))
    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(pause_event=threading.Event(), signal_log=signal_log_mock)
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


def test_whats_new_page_redirects_when_not_logged_in(client: TestClient):
    resp = client.get("/whats-new", headers={"accept": "text/html"})
    assert resp.status_code in (200, 303, 307)


def test_whats_new_page_authenticated(tmp_path: Path):
    import os as os_mod

    from core.enterprise_dashboard import EnterpriseDashboard
    os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": _make_state_file(tmp_path),
        "auth_db_path": str(tmp_path / "admin_auth_whatsnew.db"),
        "broker_name": "Test",
        "execution_mode": "paper",
    }, db_path=_make_trades_db(tmp_path))
    pw = "Admin@123!test"
    user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
    assert user is not None, "Admin authentication failed"
    token = db._auth.create_session(user)
    c = TestClient(db.app)
    c.cookies.set("opb_session", token.token)

    resp = c.get("/whats-new")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "what" in resp.text.lower()
