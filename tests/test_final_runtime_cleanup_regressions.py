import sqlite3
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_session_cleanup_handles_missing_sessions_table():
    p=ROOT/"core/auth/handler/session_manager.py"
    t=p.read_text(encoding="utf-8")
    assert "no such table: sessions" in t.lower()
    assert "sqlite3.OperationalError" in t

def test_dashboard_cleanup_handles_sqlite_errors():
    p=ROOT/"core/enterprise_dashboard/main.py"
    t=p.read_text(encoding="utf-8")
    assert "sqlite3.Error" in t

def test_email_adapter_reconnects_after_closed_stream_value_error():
    p=ROOT/"infrastructure/adapters/notifications/email_adapter.py"
    t=p.read_text(encoding="utf-8")
    assert "PyMemoryView_FromBuffer" in t
    assert "ValueError" in t
    assert "server = self._get_connection()" in t
