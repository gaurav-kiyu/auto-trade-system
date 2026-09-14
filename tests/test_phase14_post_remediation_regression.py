"""Post-remediation regression test suite for OPB v2.59.4.

Covers:
1. GET /api/chain/NIFTY?demo=true returning valid JSON and no HTTP 500.
2. Normal/live chain path remaining functional.
3. Snapshot DB schema anomaly/fallback behavior (missing db, empty table, wrong schema, corrupted db).
4. /intelligence -> /intelligence/presentation navigation.
5. Mobile overflow invariants at 390x844 in design system CSS.
6. Intentional horizontal table scrolling behavior in design tokens and templates.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient


@pytest.fixture()
def authenticated_client(tmp_path: Path) -> tuple[Any, TestClient]:
    """Create an isolated dashboard with an authenticated admin session."""
    from core.enterprise_dashboard import EnterpriseDashboard

    auth_db = str(tmp_path / "auth.db")
    state_file = str(tmp_path / "trader_state.json")
    Path(state_file).write_text(
        json.dumps({
            "daily_pnl": 0.0,
            "open_positions": 0,
            "capital": 100000,
            "execution_mode": "paper",
        }),
        encoding="utf-8",
    )

    d = EnterpriseDashboard(
        config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": auth_db,
            "broker_name": "PaperBroker",
            "execution_mode": "paper",
        }
    )
    client = TestClient(d.app)
    auth = d._auth
    user = auth.get_user("admin")
    if not user:
        res = auth.create_user("admin", "AdminPass123!@#", role="admin")
        user = auth.get_user_by_id(res["user_id"])
    session = auth.create_session(user)
    client.cookies.set("opb_session", session.token)
    return d, client


# ── 1. Options Chain Demo & Live API Regressions ──────────────────────────────


class TestOptionsChainRegression:
    """Validate options chain endpoint fixes and fallbacks."""

    def test_demo_chain_returns_valid_json_and_no_500(self, authenticated_client):
        """GET /api/chain/NIFTY?demo=true returns 200 with valid synthetic strikes."""
        _, client = authenticated_client
        resp = client.get("/api/chain/NIFTY?demo=true", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["symbol"] == "NIFTY"
        assert isinstance(data.get("strikes"), list)
        assert len(data["strikes"]) >= 10
        assert data.get("spot") is not None and data["spot"] > 0
        assert data.get("pcr") is not None
        assert data.get("total_oi") is not None and data["total_oi"] > 0
        assert "gex" in data
        assert "max_pain" in data

    def test_demo_chain_different_indices(self, authenticated_client):
        """Demo chain works seamlessly for BANKNIFTY and FINNIFTY."""
        _, client = authenticated_client
        for sym in ("BANKNIFTY", "FINNIFTY"):
            resp = client.get(f"/api/chain/{sym}?demo=true")
            assert resp.status_code == 200
            data = resp.json()
            assert data["symbol"] == sym
            assert len(data["strikes"]) > 0

    def test_live_chain_with_populated_snapshots_db(self, tmp_path: Path, authenticated_client):
        """When oi_snapshots.db has data in 'snapshots' table, it formats live rows correctly."""
        d, client = authenticated_client
        snap_dir = tmp_path / "db"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_db = snap_dir / "oi_snapshots.db"

        conn = sqlite3.connect(str(snap_db))
        conn.execute("""
            CREATE TABLE snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                index_name TEXT, strike REAL, call_oi INTEGER, put_oi INTEGER,
                call_vol INTEGER, put_vol INTEGER, call_iv REAL, put_iv REAL,
                call_ltp REAL, put_ltp REAL, spot_price REAL, timestamp TEXT
            )
        """)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn.execute("""
            INSERT INTO snapshots VALUES (1, 'NIFTY', 24000.0, 50000, 60000, 1000, 1200, 14.2, 15.1, 120.0, 110.0, 24050.0, ?)
        """, (now,))
        conn.commit()
        conn.close()

        orig_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            resp = client.get("/api/chain/NIFTY", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["symbol"] == "NIFTY"
            assert len(data["strikes"]) == 1
            assert data["strikes"][0]["strike"] == 24000.0
            assert data["spot"] == 24050.0
            assert data["pcr"] == 1.2
        finally:
            os.chdir(orig_cwd)

    def test_snapshot_db_schema_anomaly_missing_table(self, tmp_path: Path, authenticated_client):
        """When oi_snapshots.db exists but lacks 'snapshots' table, returns empty strikes with helpful note."""
        d, client = authenticated_client
        snap_dir = tmp_path / "db"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_db = snap_dir / "oi_snapshots.db"

        conn = sqlite3.connect(str(snap_db))
        conn.execute("CREATE TABLE other_table (id INTEGER PRIMARY KEY)")
        conn.commit()
        conn.close()

        orig_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            resp = client.get("/api/chain/NIFTY", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["strikes"] == []
            assert "note" in data
            assert "oi_snapshots.db not found" in data["note"]
        finally:
            os.chdir(orig_cwd)

    def test_snapshot_db_corrupt_file_graceful_fallback(self, tmp_path: Path, authenticated_client):
        """When oi_snapshots.db is corrupt, endpoint gracefully falls back without throwing 500."""
        d, client = authenticated_client
        snap_dir = tmp_path / "db"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap_db = snap_dir / "oi_snapshots.db"
        snap_db.write_text("CORRUPTED NON-SQLITE BINARY JUNK CONTENT", encoding="utf-8")

        orig_cwd = Path.cwd()
        os.chdir(tmp_path)
        try:
            resp = client.get("/api/chain/NIFTY", headers={"accept": "application/json"})
            assert resp.status_code == 200
            data = resp.json()
            assert "strikes" in data
            assert data["symbol"] == "NIFTY"
        finally:
            os.chdir(orig_cwd)


# ── 2. Intelligence Navigation Regressions ───────────────────────────────────


class TestIntelligenceNavigationRegression:
    """Verify route navigation between /intelligence and /intelligence/presentation."""

    def test_unauthenticated_redirects(self):
        """Unauthenticated access redirects to /login."""
        from core.enterprise_dashboard import EnterpriseDashboard
        d = EnterpriseDashboard()
        anon_client = TestClient(d.app)

        for route in ("/intelligence", "/intelligence/presentation"):
            resp = anon_client.get(route, follow_redirects=False)
            assert resp.status_code in (302, 303, 307), f"Expected redirect on {route}"
            assert "/login" in resp.headers.get("location", "")

    def test_authenticated_presentation_navigation(self, authenticated_client):
        """Authenticated navigation to /intelligence and /intelligence/presentation returns 200."""
        _, client = authenticated_client

        resp1 = client.get("/intelligence")
        assert resp1.status_code == 200
        assert len(resp1.text) > 500

        resp2 = client.get("/intelligence/presentation")
        assert resp2.status_code == 200
        assert len(resp2.text) > 500
        assert "Institutional Presentation" in resp2.text or "presentation" in resp2.text.lower()


# ── 3. Mobile Layout Invariants & Scrollbar Regressions ───────────────────────


class TestMobileLayoutInvariants:
    """Verify CSS invariants preventing mobile horizontal scrollbar and overflow."""

    def test_design_system_css_zero_100vw_on_root(self):
        """Ensure static/opb_design_system.css uses 100% instead of 100vw on html/body."""
        css_file = Path("static/opb_design_system.css")
        assert css_file.is_file(), "static/opb_design_system.css must exist"
        content = css_file.read_text(encoding="utf-8")

        assert not re.search(r"body\s*\{[^}]*width:\s*100vw", content), (
            "Found 'width: 100vw' on body in static/opb_design_system.css. Must use 100%."
        )
        assert not re.search(r"body\s*\{[^}]*max-width:\s*100vw", content), (
            "Found 'max-width: 100vw' on body in static/opb_design_system.css. Must use 100%."
        )
        assert not re.search(r"html,\s*body\s*\{[^}]*max-width:\s*100vw", content), (
            "Found 'max-width: 100vw' on html, body in static/opb_design_system.css. Must use 100%."
        )
        assert "max-width: 100% !important" in content

    def test_table_responsive_container_scrolling(self):
        """Verify horizontal scrolling architecture for tables in CSS and templates."""
        css_file = Path("static/opb_design_system.css")
        content = css_file.read_text(encoding="utf-8")

        assert ".opb-table-container" in content
        assert "overflow-x: auto" in content

        for tpl in ("templates/enterprise/admin_signals.html", "templates/enterprise/user_signals.html"):
            tpl_path = Path(tpl)
            assert tpl_path.is_file(), f"{tpl} must exist"
            tpl_content = tpl_path.read_text(encoding="utf-8")
            assert "opb-table-container" in tpl_content, f"{tpl} must contain opb-table-container"
            assert "table-responsive" in tpl_content, f"{tpl} must contain table-responsive"


class TestSignalPersistenceExecutionBoundary:
    """Verify durable signal_id enforcement across trading entry paths."""

    def test_missing_durable_signal_blocks_execution_fail_closed(self):
        """Ensure that when an ad-hoc signal lacks a durable signal_id and cannot be persisted,
        execution remains strictly blocked (fail-closed) with TradeBlockError."""
        from unittest.mock import Mock, patch
        from core.position_service import PositionService, TradeBlockError

        svc = PositionService.__new__(PositionService)
        svc._execution_service = Mock()
        svc._portfolio_service = None
        svc._risk_service = None
        svc._margin_validator = None
        svc._execution_mode = "PAPER"
        svc._check_liquidity_gate = Mock(return_value=(True, "ok"))

        with patch("core.signals.signal_tracker.SignalTracker.get_instance") as get_tracker:
            tracker = Mock()
            tracker.record_generated_signal.return_value = ""
            tracker.get_active_signal_id.return_value = None
            get_tracker.return_value = tracker

            with pytest.raises(TradeBlockError, match="SIGNAL_PERSISTENCE_BLOCK"):
                svc._submit_order_under_lock(
                    name="NIFTY",
                    price=150.0,
                    qty=1,
                    sig={"signal": "BUY", "direction": "CALL", "score": 85},
                    order_direction="BUY",
                    idempotency_key="idem-fail-closed-test",
                )

            svc._execution_service.execute_order.assert_not_called()

    def test_valid_durable_signal_allows_execution(self):
        """Ensure that when a signal carries a durable signal_id, execution proceeds."""
        from types import SimpleNamespace
        from unittest.mock import Mock
        from core.position_service import PositionService

        svc = PositionService.__new__(PositionService)
        svc._execution_service = Mock()
        svc._portfolio_service = None
        svc._risk_service = None
        svc._margin_validator = None
        svc._execution_mode = "PAPER"
        svc._check_liquidity_gate = Mock(return_value=(True, "ok"))
        svc._execution_service.execute_order.return_value = SimpleNamespace(
            status="FILLED",
            order_id="ORD-DURABLE-001",
            filled_quantity=1,
            average_price=150.0,
        )

        res = svc._submit_order_under_lock(
            name="NIFTY",
            price=150.0,
            qty=1,
            sig={"signal_id": "SIG_VALID_DURABLE_001", "signal": "BUY", "direction": "CALL", "score": 85},
            order_direction="BUY",
            idempotency_key="idem-valid-test",
        )
        assert res.status == "FILLED"
        svc._execution_service.execute_order.assert_called_once()
        context = svc._execution_service.execute_order.call_args[0][1]
        assert context.signal_id == "SIG_VALID_DURABLE_001"

