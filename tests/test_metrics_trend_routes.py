"""Tests for enterprise dashboard success-metrics trend routes.

Covers:
  - register_metrics_trend_routes is importable and callable
  - GET /api/metrics/trend (full report, degraded state)
  - GET /api/metrics/trend/stats
  - GET /api/metrics/trend/snapshots
  - GET /api/metrics/trend/validate/{metric_id}
  - /metrics-trend HTML page route (auth redirect + authenticated render)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient


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
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
    )
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# ── Registration ──────────────────────────────────────────────────────────────


def test_register_metrics_trend_routes_exists():
    from core.enterprise_dashboard.routes.metrics_trend import register_metrics_trend_routes
    assert callable(register_metrics_trend_routes)


def test_register_metrics_trend_routes_runs():
    app = FastAPI()
    dashboard = MagicMock()
    admin_only = lambda: None  # noqa: E731
    operator_or_admin = lambda: None  # noqa: E731
    from core.enterprise_dashboard.routes.metrics_trend import register_metrics_trend_routes
    register_metrics_trend_routes(app, dashboard, admin_only, operator_or_admin)
    assert len(app.routes) > 0


# ── API endpoints (mocked trend module) ──────────────────────────────────────


@pytest.fixture()
def trend_report() -> dict:
    """A realistic trend report payload mirroring SuccessMetricsTrend.get_report()."""
    return {
        "metric_ids": ["MET-07", "MET-08"],
        "total_snapshots": 2,
        "snapshots": [
            {
                "captured_at": 1000.0,
                "captured_at_iso": "2026-08-01T00:00:00+00:00",
                "release_label": "v1.0.0",
                "indicators": {"dead_code_findings": 120.0, "test_files": 100.0},
            },
            {
                "captured_at": 2000.0,
                "captured_at_iso": "2026-08-04T00:00:00+00:00",
                "release_label": "v2.0.0",
                "indicators": {"dead_code_findings": 100.0, "test_files": 130.0},
            },
        ],
        "verdicts": {
            "MET-07": {"metric_id": "MET-07", "passed": True, "direction": "DOWN",
                       "snapshots": 2, "detail": "trending DOWN"},
            "MET-08": {"metric_id": "MET-08", "passed": True, "direction": "UP",
                       "snapshots": 2, "detail": "trending UP"},
        },
        "generated_at": "2026-08-04T00:00:00+00:00",
    }


def _stub_trend(trend_report: dict, monkeypatch) -> None:
    """Patch get_metrics_trend() with a stub returning the given report/stats."""

    class _Stub:
        def get_report(self):
            return trend_report

        def get_stats(self):
            return {
                "total_snapshots": trend_report["total_snapshots"],
                "MET-07_direction": "DOWN",
                "MET-08_direction": "UP",
                "has_enough_data": True,
            }

        def list_snapshots(self, limit=50):
            return []

        def validate_metric(self, metric_id):
            return trend_report["verdicts"].get(metric_id, {
                "metric_id": metric_id, "passed": False, "direction": "NO_DATA",
                "snapshots": 0, "detail": "insufficient time-series data",
            })

    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._trend",
        lambda: _Stub(),
    )


def test_trend_full_report(client: TestClient, monkeypatch, trend_report):
    _stub_trend(trend_report, monkeypatch)
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_snapshots"] == 2
    assert set(data["verdicts"]) == {"MET-07", "MET-08"}
    assert data["verdicts"]["MET-07"]["direction"] == "DOWN"
    assert len(data["snapshots"]) == 2
    assert data["has_enough_data"] is True


def test_trend_stats(client: TestClient, monkeypatch, trend_report):
    _stub_trend(trend_report, monkeypatch)
    resp = client.get("/api/metrics/trend/stats", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["stats"]["has_enough_data"] is True
    assert data["stats"]["MET-07_direction"] == "DOWN"


def test_trend_snapshots(client: TestClient, monkeypatch, trend_report):
    _stub_trend(trend_report, monkeypatch)
    resp = client.get("/api/metrics/trend/snapshots", headers={"accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_trend_validate(client: TestClient, monkeypatch, trend_report):
    _stub_trend(trend_report, monkeypatch)
    resp = client.get("/api/metrics/trend/validate/MET-07",
                      headers={"accept": "application/json"})
    assert resp.status_code == 200
    verdict = resp.json()["verdict"]
    assert verdict["direction"] == "DOWN"
    assert verdict["passed"] is True


def test_trend_unavailable_degrades_gracefully(client: TestClient, monkeypatch):
    """When the trend module import fails, endpoints return unavailable."""
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._trend",
        lambda: (_ for _ in ()).throw(ImportError("no trend module")),
    )
    # Stub the register check too so this test stays hermetic (no real reads
    # of the 43k-row register during unit tests).
    _stub_register_consistency(monkeypatch)
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["total_snapshots"] == 0
    assert data["snapshots"] == []


# ── Register consistency exposure ─────────────────────────────────────────────


def _stub_register_consistency(monkeypatch, ok: bool = True, drifted=()) -> None:
    """Patch the register consistency check with a realistic result."""
    registers = {
        "docs/dead_code_register.md": {"ok": True, "expected_prefix": "DC-"},
        "docs/duplicate_code_register.md": {"ok": True, "expected_prefix": "DUP-"},
        "docs/config_drift_register.md": {"ok": True, "expected_prefix": "CDR-"},
        "docs/doc_drift_register.md": {"ok": True, "expected_prefix": "DDR-"},
    }
    for rp in drifted:
        registers[rp] = {"ok": False, "expected_prefix": "XX-"}
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._register_consistency",
        lambda: {"ok": ok, "registers": registers,
                 "checked_at": "2026-08-04T00:00:00+00:00"},
    )


def test_trend_full_report_includes_register_consistency(client: TestClient,
                                                         monkeypatch,
                                                         trend_report):
    _stub_trend(trend_report, monkeypatch)
    _stub_register_consistency(monkeypatch)
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    rc = resp.json()["register_consistency"]
    assert rc["ok"] is True
    assert rc["status"] == "aligned"
    assert set(rc["registers"]) == {
        "docs/dead_code_register.md", "docs/duplicate_code_register.md",
        "docs/config_drift_register.md", "docs/doc_drift_register.md",
    }
    assert rc["drifted_registers"] == []


def test_trend_full_report_reports_drift(client: TestClient, monkeypatch,
                                         trend_report):
    _stub_trend(trend_report, monkeypatch)
    _stub_register_consistency(monkeypatch, ok=False,
                               drifted=("docs/config_drift_register.md",))
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    data = resp.json()
    # Trend data is still served; only the register health is flagged.
    assert data["status"] == "ok"
    assert data["total_snapshots"] == 2
    rc = data["register_consistency"]
    assert rc["ok"] is False
    assert rc["status"] == "drift"
    assert rc["drifted_registers"] == ["docs/config_drift_register.md"]


def test_trend_stats_includes_register_consistency(client: TestClient,
                                                   monkeypatch,
                                                   trend_report):
    _stub_trend(trend_report, monkeypatch)
    _stub_register_consistency(monkeypatch)
    resp = client.get("/api/metrics/trend/stats",
                      headers={"accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["register_consistency"]["status"] == "aligned"


def test_trend_register_consistency_unavailable_degrades(client: TestClient,
                                                         monkeypatch,
                                                         trend_report):
    _stub_trend(trend_report, monkeypatch)
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._register_consistency",
        lambda: (_ for _ in ()).throw(ImportError("no trend module")),
    )
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    rc = resp.json()["register_consistency"]
    assert rc["status"] == "unavailable"
    assert rc["ok"] is False
    assert "detail" in rc


def test_trend_stats_reports_drift_compactly(client: TestClient, monkeypatch,
                                             trend_report):
    _stub_trend(trend_report, monkeypatch)
    _stub_register_consistency(monkeypatch, ok=False,
                               drifted=("docs/doc_drift_register.md",))
    resp = client.get("/api/metrics/trend/stats",
                      headers={"accept": "application/json"})
    assert resp.status_code == 200
    rc = resp.json()["register_consistency"]
    assert rc["status"] == "drift"
    assert rc["drifted_registers"] == ["docs/doc_drift_register.md"]
    # Stats payload is compact: no full per-register detail.
    assert "registers" not in rc


def test_trend_full_report_strips_row_ids(client: TestClient, monkeypatch,
                                          trend_report):
    """The API must not serialize the bulky per-register row_ids lists."""
    _stub_trend(trend_report, monkeypatch)
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._register_consistency",
        lambda: {
            "ok": True,
            "checked_at": "2026-08-04T00:00:00+00:00",
            "registers": {
                "docs/dead_code_register.md": {
                    "ok": True, "expected_prefix": "DC-",
                    "row_ids": [f"DC-{i:03d}" for i in range(1, 50001)],
                    "tracker_count": 50000, "parsed_count": 50000,
                    "matching_count": 50000, "foreign_ids": [],
                    "count_agrees": True, "file_exists": True,
                },
            },
        },
    )
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    detail = resp.json()["register_consistency"]["registers"][
        "docs/dead_code_register.md"]
    assert "row_ids" not in detail
    assert detail["parsed_count"] == 50000
    assert detail["expected_prefix"] == "DC-"


def test_trend_register_consistency_independent_of_trend(client: TestClient,
                                                         monkeypatch):
    """A broken trend module must not hide a healthy register consistency check."""
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._trend",
        lambda: (_ for _ in ()).throw(ImportError("no trend module")),
    )
    _stub_register_consistency(monkeypatch)
    resp = client.get("/api/metrics/trend", headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "unavailable"
    assert data["register_consistency"]["status"] == "aligned"


# ── Release audit trail ───────────────────────────────────────────────────────


def _write_audit_record(tmp_path: Path, filename: str, **fields: dict) -> Path:
    """Write a release audit JSON record into a temp logs/audit dir."""
    audit_dir = tmp_path / "logs" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": 1785421090.0, "version": "2.58.0", "branch": "main",
        "date": "2026-08-04", "changes": ["a", "b"], "verified": False,
        "reproducible": True,
    }
    record.update(fields)
    path = audit_dir / filename
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_release_audits_surfaces_register_gate(client: TestClient, monkeypatch,
                                               tmp_path: Path):
    """Release audit records surface the register gate verdict in the API."""
    _write_audit_record(tmp_path, "release_v2.58.0_2026-08-04.json",
                        register_gate_passed=True, register_gate_status="aligned",
                        trend_snapshot_captured=True)
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._AUDIT_DIR",
        tmp_path / "logs" / "audit",
    )
    resp = client.get("/api/metrics/trend/release-audits",
                      headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["count"] == 1
    audit = data["audits"][0]
    assert audit["version"] == "2.58.0"
    assert audit["register_gate_passed"] is True
    assert audit["register_gate_status"] == "aligned"
    assert audit["trend_snapshot_captured"] is True
    assert audit["changes_count"] == 2


def test_release_audits_legacy_records_default_unknown(client: TestClient,
                                                       monkeypatch,
                                                       tmp_path: Path):
    """Records written before the gate fields existed default to unknown."""
    _write_audit_record(tmp_path, "release_v2.50.0_2026-06-01.json")
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._AUDIT_DIR",
        tmp_path / "logs" / "audit",
    )
    resp = client.get("/api/metrics/trend/release-audits",
                      headers={"accept": "application/json"})
    audit = resp.json()["audits"][0]
    assert audit["register_gate_passed"] is None
    assert audit["register_gate_status"] == "unknown"


def test_release_audits_drift_verdict(client: TestClient, monkeypatch,
                                      tmp_path: Path):
    """A drift-failed gate is surfaced distinctly in the audit trail."""
    _write_audit_record(tmp_path, "release_v2.59.0_2026-08-05.json",
                        register_gate_passed=False, register_gate_status="drift",
                        trend_snapshot_captured=False)
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._AUDIT_DIR",
        tmp_path / "logs" / "audit",
    )
    resp = client.get("/api/metrics/trend/release-audits",
                      headers={"accept": "application/json"})
    audit = resp.json()["audits"][0]
    assert audit["register_gate_passed"] is False
    assert audit["register_gate_status"] == "drift"


def test_audit_dir_resolves_to_repo_logs_audit():
    """The audit dir must point at the repo root's logs/audit, not core/logs."""
    from core.enterprise_dashboard.routes import metrics_trend as mt
    repo_root = Path(mt.__file__).resolve().parent.parent.parent.parent
    assert mt._AUDIT_DIR == repo_root / "logs" / "audit"


def test_release_audits_empty_when_no_records(client: TestClient, monkeypatch,
                                              tmp_path: Path):
    """No audit dir/records yields an empty, graceful response."""
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._AUDIT_DIR",
        tmp_path / "no" / "audits" / "here",
    )
    resp = client.get("/api/metrics/trend/release-audits",
                      headers={"accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["count"] == 0
    assert data["audits"] == []


def test_release_audits_sorted_newest_first(client: TestClient, monkeypatch,
                                            tmp_path: Path):
    """Records are returned newest-first by modification time."""
    old = _write_audit_record(tmp_path, "release_v2.50.0_2026-06-01.json",
                              version="2.50.0", timestamp=1780000000.0)
    new = _write_audit_record(tmp_path, "release_v2.58.0_2026-08-04.json",
                              timestamp=1785421090.0,
                              register_gate_passed=True,
                              register_gate_status="aligned")
    import os
    os.utime(old, (1780000000, 1780000000))
    os.utime(new, (1785421090, 1785421090))
    monkeypatch.setattr(
        "core.enterprise_dashboard.routes.metrics_trend._AUDIT_DIR",
        tmp_path / "logs" / "audit",
    )
    resp = client.get("/api/metrics/trend/release-audits",
                      headers={"accept": "application/json"})
    versions = [a["version"] for a in resp.json()["audits"]]
    assert versions == ["2.58.0", "2.50.0"]


# ── HTML page route ───────────────────────────────────────────────────────────


def test_metrics_trend_page_redirects_when_not_logged_in(client: TestClient):
    resp = client.get("/metrics-trend", headers={"accept": "text/html"})
    assert resp.status_code in (200, 303, 307)
    if resp.status_code in (303, 307):
        assert "/login" in resp.headers.get("location", "")


def test_metrics_trend_page_authenticated(client: TestClient, monkeypatch,
                                          tmp_path: Path, trend_report):
    import os as os_mod

    from core.enterprise_dashboard import EnterpriseDashboard
    os_mod.environ["OPBUYING_DEFAULT_ADMIN_PASSWORD"] = "Admin@123!test"

    db = EnterpriseDashboard(config={
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": _make_state_file(tmp_path),
        "auth_db_path": str(tmp_path / "admin_auth.db"),
        "broker_name": "Test",
        "execution_mode": "paper",
    }, db_path=_make_trades_db(tmp_path))
    pw = "Admin@123!test"
    user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
    assert user is not None, "Admin authentication failed"
    token = db._auth.create_session(user)
    c = TestClient(db.app)
    c.cookies.set("opb_session", token.token)

    _stub_trend(trend_report, monkeypatch)
    resp = c.get("/metrics-trend")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    html = resp.text.lower()
    assert "success metrics trend" in html
    assert "met-07" in html
    assert "met-08" in html
    assert "/api/metrics/trend" in html
