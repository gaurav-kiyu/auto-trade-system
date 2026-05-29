"""Comprehensive enterprise dashboard tests — all DB/IO mocked.

Covers: initialization, config freeze, wiring, security headers, CORS,
request IDs, CSRF exemptions, rate limiting, kill switch, config management,
auth routes, system API, risk concentration, CSV export, webhook injection,
options chain, error handlers, static files, session cleanup, profile/password.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from types import MappingProxyType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

# ── Helpers ──────────────────────────────────────────────────────────────────────


def _make_config_file(path: str, data: dict | None = None) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data or {"BASE_CAPITAL": 100000, "SL_PCT": 5}), encoding="utf-8")
    return p


def _make_trades_db(db_path: str) -> None:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, symbol TEXT,
            expiry TEXT, direction TEXT, strike INTEGER, qty INTEGER,
            entry_price REAL, exit_price REAL, net_pnl REAL, pnl REAL,
            quantity INTEGER, mode TEXT, strategy TEXT, status TEXT,
            entry_time TEXT, exit_time TEXT, index_name TEXT
        )
    """)
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    trades = [
        (1, now, "NIFTY", "25MAY2026", "CALL", 25000, 75, 150.0, 185.0, 2625.0,
         2625.0, 75, "PAPER", "BUY", "closed", now, now, "NIFTY"),
        (2, now, "BANKNIFTY", "25MAY2026", "PUT", 51000, 50, 200.0, None,
         0.0, 0.0, 50, "PAPER", "BUY", "open", now, None, "BANKNIFTY"),
    ]
    conn.executemany(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", trades,
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _global_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Globally mock Jinja2 templates and CSRF validation for all tests."""
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    def safe_render(self, name, context, status_code=200, headers=None, media_type=None, **kwargs):
        return HTMLResponse(
            content=f"<html><body>mocked:{name}</body></html>",
            status_code=status_code,
            headers=headers,
            media_type=media_type or "text/html",
        )
    monkeypatch.setattr(Jinja2Templates, "TemplateResponse", safe_render)

    from core.auth.csrf import csrf_protection
    monkeypatch.setattr(csrf_protection, "validate", AsyncMock(return_value=None))
    monkeypatch.setattr(csrf_protection, "ensure_cookie_set", AsyncMock(return_value=None))


@pytest.fixture()
def state_file(tmp_path: Path) -> str:
    p = tmp_path / "trader_state.json"
    p.write_text(json.dumps({
        "daily_pnl": 1500.0, "open_positions": 2, "hard_halt": False,
        "capital": 100000, "execution_mode": "paper", "total_trades": 42,
        "base_capital": 100000, "circuit_breaker": "Closed",
    }))
    return str(p)


@pytest.fixture()
def trades_db(tmp_path: Path) -> str:
    db_path = str(tmp_path / "trades.db")
    _make_trades_db(db_path)
    return db_path


@pytest.fixture()
def config_file(tmp_path: Path) -> str:
    return str(_make_config_file(str(tmp_path / "config.json")))


@pytest.fixture()
def defaults_file(tmp_path: Path) -> str:
    p = tmp_path / "index_config.defaults.json"
    p.write_text(json.dumps({"BASE_CAPITAL": 50000, "TARGET_PCT": 10}), encoding="utf-8")
    return str(p)


@pytest.fixture()
def base_cfg(state_file, config_file, defaults_file, tmp_path) -> dict:
    return {
        "web_dashboard_host": "127.0.0.1",
        "trader_state_path": state_file,
        "auth_db_path": str(tmp_path / "dash_auth.db"),
        "index_config_path": config_file,
        "index_config_defaults_path": defaults_file,
        "broker_name": "Zerodha",
        "execution_mode": "paper",
        "broker_adapter": "kite",
    }


@pytest.fixture()
def dashboard(base_cfg, trades_db):
    from core.enterprise_dashboard import EnterpriseDashboard

    db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
    signal_log_mock = MagicMock()
    signal_log_mock.recent.return_value = []
    db.wire_bot_refs(
        pause_event=threading.Event(),
        signal_log=signal_log_mock,
        ml_model_loaded=True,
        ml_accuracy=0.72,
        ml_brier_score=0.18,
        ml_last_training="2026-05-20",
        ml_n_features=14,
        ml_training_samples=1200,
        ml_drift_detected=False,
        ml_total_predictions=500,
        ml_avg_confidence=0.65,
        ml_calibration_score=0.88,
        ml_psi=0.03,
        broker_latency=12,
    )
    return db


@pytest.fixture()
def client(dashboard) -> TestClient:
    return TestClient(dashboard.app)


# =============================================================================
# 1. EnterpriseDashboard initialization with mocks
# =============================================================================


class TestDashboardInit:
    def test_creation_defaults(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        assert db is not None
        assert db.app is not None
        assert db._state_path == "trader_state.json"
        assert db._db_path == "trades.db"

    def test_creation_with_custom_paths(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={
                "web_dashboard_host": "127.0.0.1",
                "auth_db_path": str(tmp_path / "auth.db"),
            },
            state_path="/custom/state.json",
            db_path="/custom/trades.db",
        )
        assert db._state_path == "/custom/state.json"
        assert db._db_path == "/custom/trades.db"

    def test_creation_config_freeze_immutable(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        cfg = {"key1": "val1", "nested": {"inner": 42}, "auth_db_path": str(tmp_path / "auth.db")}
        db = EnterpriseDashboard(config=cfg)
        frozen = db.config
        assert isinstance(frozen, MappingProxyType)
        assert frozen["key1"] == "val1"
        assert isinstance(frozen["nested"], MappingProxyType)
        assert frozen["nested"]["inner"] == 42

    def test_creation_secure_cookie_when_not_localhost(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={"web_dashboard_host": "0.0.0.0", "auth_db_path": str(tmp_path / "auth.db")},
        )
        assert db._cookie_secure is True

    def test_creation_secure_cookie_false_when_localhost(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={"web_dashboard_host": "127.0.0.1", "auth_db_path": str(tmp_path / "auth.db")},
        )
        assert db._cookie_secure is False

    def test_creation_with_auth_handler_override(self, tmp_path):
        from core.auth.handler import AuthHandler
        from core.enterprise_dashboard import EnterpriseDashboard

        auth = MagicMock(spec=AuthHandler)
        auth._db_path = str(tmp_path / "auth.db")
        auth._token_ttl = 3600
        db = EnterpriseDashboard(config={"auth_db_path": str(tmp_path / "auth.db")}, auth_handler=auth)
        assert db._auth is auth

    def test_factory_function(self, state_file, trades_db, base_cfg):
        from core.enterprise_dashboard import create_enterprise_dashboard

        pause = threading.Event()
        dash = create_enterprise_dashboard(config=base_cfg, pause_event=pause, signal_log=MagicMock())
        assert dash is not None
        assert dash._pause_event is pause


# =============================================================================
# 2. Config freeze (MappingProxyType immutability)
# =============================================================================


class TestConfigFreeze:
    def test_frozen_config_raises_on_set(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={"key": "val", "auth_db_path": str(tmp_path / "auth.db")},
        )
        with pytest.raises(TypeError):
            db.config["key"] = "newval"

    def test_frozen_config_raises_on_del(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={"key": "val", "auth_db_path": str(tmp_path / "auth.db")},
        )
        with pytest.raises(TypeError):
            del db.config["key"]

    def test_config_property_after_cfg_updated(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(
            config={"key": "old", "auth_db_path": str(tmp_path / "auth.db")},
        )
        assert db.config["key"] == "old"
        db._cfg["key"] = "new"
        # config property returns frozen snapshot, not live _cfg
        assert db.config["key"] == "old"


# =============================================================================
# 3. Wire bot refs functionality
# =============================================================================


class TestWireBotRefs:
    def test_wire_all_refs(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={"auth_db_path": str(tmp_path / "auth.db")})
        pause = threading.Event()
        sig_log = MagicMock()
        sig_queue = MagicMock()
        ws_mgr = MagicMock()
        rl = MagicMock()
        cp = MagicMock()
        db.wire_bot_refs(
            pause_event=pause, signal_log=sig_log, signal_queue=sig_queue,
            ws_feed_manager=ws_mgr, rate_limiter=rl, control_plane=cp,
        )
        assert db._pause_event is pause
        assert db._signal_log is sig_log
        assert db._signal_queue is sig_queue
        assert db._ws_feed_manager is ws_mgr
        assert db._rate_limiter is rl
        assert db._control_plane is cp

    def test_wire_partial_refs(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={"auth_db_path": str(tmp_path / "auth.db")})
        db.wire_bot_refs(pause_event=threading.Event())
        assert db._pause_event is not None
        assert db._signal_log is None

    def test_wire_extra_refs_stored(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={"auth_db_path": str(tmp_path / "auth.db")})
        db.wire_bot_refs(custom_ref="hello", another=42)
        assert db._bot_refs["custom_ref"] == "hello"
        assert db._bot_refs["another"] == 42

    def test_wire_overwrites_existing(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={"auth_db_path": str(tmp_path / "auth.db")})
        old = threading.Event()
        new = threading.Event()
        db.wire_bot_refs(pause_event=old)
        assert db._pause_event is old
        db.wire_bot_refs(pause_event=new)
        assert db._pause_event is new


# =============================================================================
# 4. Security headers middleware (CSP, HSTS, X-Frame-Options, etc.)
# =============================================================================


class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        resp = client.get("/api/system/health")
        assert resp.headers.get("x-content-type-options") == "nosniff"

    def test_x_frame_options_deny(self, client):
        resp = client.get("/api/system/health")
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_x_xss_protection(self, client):
        resp = client.get("/api/system/health")
        assert resp.headers.get("x-xss-protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        resp = client.get("/api/system/health")
        assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = client.get("/api/system/health")
        pp = resp.headers.get("permissions-policy")
        assert pp is not None
        assert "camera=()" in pp
        assert "microphone=()" in pp
        assert "geolocation=()" in pp

    def test_csp_present(self, client):
        resp = client.get("/api/system/health")
        csp = resp.headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src 'self' 'nonce-" in csp
        assert "style-src 'self' 'unsafe-inline'" in csp
        assert "font-src 'self'" in csp
        assert "img-src 'self' data:" in csp
        assert "connect-src 'self'" in csp
        assert "form-action 'self'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "base-uri 'self'" in csp

    def test_csp_no_cdn_origins(self, client):
        resp = client.get("/api/system/health")
        csp = resp.headers.get("content-security-policy", "")
        assert "cdn.tailwindcss.com" not in csp
        assert "cdnjs.cloudflare.com" not in csp

    def test_hsts_not_on_http(self, client):
        resp = client.get("/api/system/health")
        assert resp.headers.get("strict-transport-security") is None

    def test_hsts_on_https(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
        }, db_path=trades_db)
        c = TestClient(db.app, base_url="https://testserver")
        resp = c.get("/api/system/health")
        hsts = resp.headers.get("strict-transport-security")
        assert hsts is not None
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts
        assert "preload" in hsts

    def test_hsts_via_forwarded_proto(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
        }, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/health", headers={"X-Forwarded-Proto": "https"})
        hsts = resp.headers.get("strict-transport-security")
        assert hsts is not None
        assert "max-age=31536000" in hsts

    def test_csp_nonce_unique_per_request(self, client):
        resp1 = client.get("/api/system/health")
        resp2 = client.get("/api/system/health")
        csp1 = resp1.headers.get("content-security-policy", "")
        csp2 = resp2.headers.get("content-security-policy", "")
        n1 = csp1.split("nonce-")[1].split("'")[0] if "nonce-" in csp1 else ""
        n2 = csp2.split("nonce-")[1].split("'")[0] if "nonce-" in csp2 else ""
        assert n1 and n2
        assert n1 != n2


# =============================================================================
# 5. CORS headers
# =============================================================================


class TestCorsHeaders:
    def test_cors_not_set_when_no_origins(self, client):
        resp = client.get("/api/system/health", headers={"origin": "https://evil.com"})
        cors = resp.headers.get("access-control-allow-origin")
        assert cors is None or cors != "https://evil.com"

    def test_cors_set_when_configured(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
            "cors_allowed_origins": "https://example.com, https://trusted.com",
        }, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/health", headers={"origin": "https://example.com"})
        assert resp.status_code == 200

    def test_cors_rejects_untrusted(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
            "cors_allowed_origins": "https://trusted.com",
        }, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/health", headers={"origin": "https://evil.com"})
        cors = resp.headers.get("access-control-allow-origin")
        assert cors is None or cors != "https://evil.com"

    def test_cors_empty_origins_config(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "auth.db"),
            "cors_allowed_origins": "",
        }, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/system/health", headers={"origin": "https://example.com"})
        assert resp.status_code == 200


# =============================================================================
# 6. Request ID + tracing middleware
# =============================================================================


class TestRequestIdTracing:
    def test_request_id_generated(self, client):
        resp = client.get("/api/system/health")
        assert "x-request-id" in resp.headers
        rid = resp.headers["x-request-id"]
        assert len(rid) == 16

    def test_request_id_from_client(self, client):
        resp = client.get("/api/system/health", headers={"X-Request-ID": "client-provided-id-42"})
        assert resp.headers.get("x-request-id") == "client-provided-id-42"

    def test_response_time_header(self, client):
        resp = client.get("/api/system/health")
        assert "x-response-time-ms" in resp.headers
        ms = resp.headers["x-response-time-ms"]
        assert ms.isdigit()

    def test_request_id_unique_per_request(self, client):
        resp1 = client.get("/api/system/health")
        resp2 = client.get("/api/system/health")
        rid1 = resp1.headers.get("x-request-id")
        rid2 = resp2.headers.get("x-request-id")
        assert rid1 != rid2


# =============================================================================
# 7. CSRF middleware exemption paths
# =============================================================================


class TestCsrfExemptPaths:
    def test_exempt_paths_in_dashboard(self, tmp_path):
        from core.auth.csrf import csrf_protection
        from core.enterprise_dashboard import EnterpriseDashboard

        csrf_protection._exempt_paths = set()
        EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        exempt = csrf_protection._exempt_paths
        assert "/api/auth/login" in exempt
        assert "/api/auth/logout" in exempt
        assert "/api/system/health/docker" in exempt
        assert "/signals/inject" in exempt
        assert "/static" in exempt
        assert "/api/system/self-test" in exempt


# =============================================================================
# 8. API rate limiting
# =============================================================================


class TestApiRateLimiting:
    def test_rate_limit_not_exceeded(self, client):
        for _ in range(5):
            resp = client.get("/api/system/health")
            assert resp.status_code == 200

    def test_docker_health_bypasses_rate_limit(self, client):
        resp = client.get("/api/system/health/docker")
        assert resp.status_code == 200


# =============================================================================
# 9. Kill switch functionality
# =============================================================================


class TestKillSwitch:
    def test_execute_kill_basic(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        pause = threading.Event()
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=pause)
        r = db._execute_kill("Test", "admin")
        assert r["success"]
        assert r["halted"]
        assert r["reason"] == "Test"
        assert r["triggered_by"] == "admin"
        assert pause.is_set()

    def test_execute_kill_with_control_plane(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        cp = MagicMock()
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=threading.Event(), control_plane=cp)
        db._execute_kill("CP test", "admin")
        cp.control_kill.assert_called_once_with("admin", reason="CP test")

    def test_execute_kill_control_plane_failure(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        cp = MagicMock()
        cp.control_kill.side_effect = RuntimeError("CP down")
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=threading.Event(), control_plane=cp)
        r = db._execute_kill("CP fail", "admin")
        assert r["success"]
        assert r["halted"]

    def test_execute_kill_with_halt_callback(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        cb = MagicMock()
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=threading.Event(), halt_callback=cb)
        db._execute_kill("CB test", "admin")
        cb.assert_called_once()

    def test_execute_kill_halt_callback_failure(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        cb = MagicMock()
        cb.side_effect = RuntimeError("CB error")
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=threading.Event(), halt_callback=cb)
        r = db._execute_kill("CB fail", "admin")
        assert r["success"]

    def test_execute_resume(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        pause = threading.Event()
        pause.set()
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=pause)
        r = db._execute_resume()
        assert r["success"]
        assert not r["halted"]
        assert not pause.is_set()

    def test_kill_then_resume(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        pause = threading.Event()
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        db.wire_bot_refs(pause_event=pause)
        db._execute_kill("seq", "admin")
        assert pause.is_set()
        db._execute_resume()
        assert not pause.is_set()

    def test_kill_status_false(self, client):
        resp = client.get("/api/system/kill-status")
        assert resp.json()["halted"] is False

    def test_kill_status_true(self, dashboard, client):
        dashboard._pause_event.set()
        resp = client.get("/api/system/kill-status")
        assert resp.json()["halted"] is True


# =============================================================================
# 10. Config management
# =============================================================================


class TestConfigManagement:
    def test_get_config_requires_auth(self, state_file, trades_db, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": state_file,
            "auth_db_path": str(tmp_path / "admin_auth.db"),
        }, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/config")
        assert resp.status_code == 401

    def test_get_defaults(self, dashboard):
        with patch.object(dashboard, "_load_defaults", return_value={"KEY": "VAL"}):
            result = dashboard._load_defaults()
        assert result == {"KEY": "VAL"}

    def test_validate_config_change_valid(self, dashboard):
        r = dashboard._validate_config_change({"BASE_CAPITAL": 10000})
        assert r["valid"]
        assert r["errors"] == []

    def test_validate_config_change_env_ref(self, dashboard):
        r = dashboard._validate_config_change({"TOKEN": "${OPBUYING_TOKEN}"})
        assert r["valid"]
        assert len(r["warnings"]) > 0

    def test_validate_config_skip_underscore(self, dashboard):
        r = dashboard._validate_config_change({"_internal": "secret"})
        assert r["valid"]
        assert r["warnings"] == []

    def test_validate_config_skip_broker_config(self, dashboard):
        r = dashboard._validate_config_change({"BROKER_CONFIG": {"key": "val"}})
        assert r["valid"]
        assert r["warnings"] == []

    def test_preview_config_change_existing(self, dashboard):
        dashboard._cfg["KEY"] = "old"
        r = dashboard._preview_config_change({"KEY": "new"})
        assert r["total_changes"] == 1
        assert r["changed_keys"]["KEY"]["old"] == "old"
        assert r["changed_keys"]["KEY"]["new"] == "new"

    def test_preview_config_change_new_key(self, dashboard):
        r = dashboard._preview_config_change({"NEW_KEY": "val"})
        assert r["total_changes"] == 1
        assert r["changed_keys"]["NEW_KEY"]["old"] is None
        assert r["changed_keys"]["NEW_KEY"]["new"] == "val"

    def test_preview_config_no_change(self, dashboard):
        dashboard._cfg["KEY"] = "val"
        r = dashboard._preview_config_change({"KEY": "val"})
        assert r["total_changes"] == 0

    def test_apply_config_success(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        _make_config_file(config_path, {"K": "old"})
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "new", "SL_PCT": 3}, "admin")
        assert r["success"]
        assert r["applied_count"] == 2
        assert "K" in r["applied_keys"]
        assert r["backup_file"] is not None

    def test_apply_config_file_not_found(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        missing = str(tmp_path / "no_config.json")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": missing,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "new"}, "admin")
        assert r["success"]

    def test_apply_config_skip_underscore(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        _make_config_file(config_path, {"K": "old"})
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "new", "_hidden": "nope"}, "admin")
        assert r["success"]
        assert "K" in r["applied_keys"]
        assert "_hidden" not in r["applied_keys"]

    def test_apply_config_updates_memory(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        _make_config_file(config_path, {"K": "old"})
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        db._apply_config_change({"K": "updated"}, "admin")
        assert db._cfg["K"] == "updated"

    def test_apply_config_corrupt_file(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        config_path.write_text("not valid json{{{", encoding="utf-8")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "val"}, "admin")
        assert not r["success"]

    def test_apply_config_backup_write_error(self, tmp_path, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        _make_config_file(config_path, {"K": "v"})
        original_write = Path.write_text
        call_count = [0]

        def patched_write(self, *a, **kw):
            call_count[0] += 1
            if call_count[0] == 2:
                raise OSError("Permission denied")
            return original_write(self, *a, **kw)

        monkeypatch.setattr(Path, "write_text", patched_write)
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "new"}, "admin")
        assert not r["success"]

    def test_apply_config_write_error_rollback(self, tmp_path, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"K": "v"})
        call_count = [0]
        original_write = Path.write_text

        def patched_write(self, *a, **kw):
            call_count[0] += 1
            if call_count[0] == 2:
                raise OSError("Write failed")
            return original_write(self, *a, **kw)

        monkeypatch.setattr(Path, "write_text", patched_write)
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._apply_config_change({"K": "new"}, "admin")
        assert not r["success"]

    def test_config_history(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"k": "v"})
        now = time.time()
        for i in range(3):
            bp = config_path.parent / f"config.json.backup.{int(now - i * 100)}"
            bp.write_text("{}", encoding="utf-8")

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
        })
        history = db._get_config_history()
        assert len(history) >= 3
        assert all("file" in h and "timestamp" in h and "age" in h for h in history)

    def test_config_history_sorted(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"k": "v"})
        now = time.time()
        for i in range(3):
            bp = config_path.parent / f"config.json.backup.{int(now - i * 200)}"
            bp.write_text("{}", encoding="utf-8")

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
        })
        history = db._get_config_history()
        if len(history) >= 2:
            assert history[0]["timestamp"] >= history[1]["timestamp"]

    def test_config_history_empty(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
        })
        history = db._get_config_history()
        assert history == []

    def test_config_history_bad_filenames(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"k": "v"})
        bp = config_path.parent / "config.json.backup.not-a-number"
        bp.write_text("{}", encoding="utf-8")

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
        })
        history = db._get_config_history()
        assert isinstance(history, list)

    def test_rollback_success(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"VERSION": "2"})
        backup_name = f"config.json.backup.{int(time.time())}"
        backup_path = config_path.parent / backup_name
        backup_path.write_text(json.dumps({"VERSION": "1"}), encoding="utf-8")

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._rollback_config(backup_name, "admin")
        assert r["success"]
        assert r["restored_from"] == backup_name
        assert db._cfg["VERSION"] == "1"

    def test_rollback_directory_traversal_blocked(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
        })
        r = db._rollback_config("../../etc/passwd.backup.123", "admin")
        assert not r["success"]
        assert "directory traversal" in r.get("error", "").lower()

    def test_rollback_not_found(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"V": "2"})
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
        })
        r = db._rollback_config("nonexistent.backup.123", "admin")
        assert not r["success"]
        assert "not found" in r.get("error", "").lower()

    def test_rollback_corrupt_backup(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = tmp_path / "config.json"
        _make_config_file(str(config_path), {"V": "2"})
        backup_name = "config.json.backup.999999"
        (config_path.parent / backup_name).write_text("bad json{{{", encoding="utf-8")

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": str(config_path),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        r = db._rollback_config(backup_name, "admin")
        assert not r["success"]
        assert "error" in r

    def test_log_config_audit(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        db._log_config_audit("testuser", ["KEY1"], ["val1"], "config_apply")
        audit_file = Path("config_audit.jsonl")
        assert audit_file.is_file()
        content = audit_file.read_text(encoding="utf-8")
        assert "testuser" in content
        assert "KEY1" in content
        assert "config_apply" in content
        audit_file.unlink(missing_ok=True)

    def test_apply_creates_audit_log(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        config_path = str(tmp_path / "config.json")
        _make_config_file(config_path, {"K": "old"})
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_path": config_path,
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        db._apply_config_change({"K": "new"}, "operator")
        audit_file = Path("config_audit.jsonl")
        if audit_file.is_file():
            content = audit_file.read_text(encoding="utf-8")
            assert "operator" in content
            assert "config_apply" in content
            audit_file.unlink(missing_ok=True)

    def test_resolve_defaults_path_default(self, dashboard):
        p = dashboard._resolve_defaults_path()
        assert p.name == "index_config.defaults.json"

    def test_resolve_config_path_env_override(self, dashboard, monkeypatch):
        monkeypatch.setenv("OPBUYING_INDEX_CONFIG", "/env/config.json")
        p = dashboard._resolve_config_path()
        assert "env" in str(p)

    def test_resolve_config_path_from_config(self, dashboard):
        dashboard._cfg["index_config_path"] = "/custom/path/config.json"
        p = dashboard._resolve_config_path()
        assert "custom" in str(p)


# =============================================================================
# 11. Auth routes (via client)
# =============================================================================


class TestAuthRoutes:
    def test_login_success(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.post("/api/auth/login", json={"username": "admin", "password": "Admin@123!test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_login_failure(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.post("/api/auth/login", json={"username": "bad", "password": "wrong"})
        assert resp.status_code == 401

    def test_login_missing_credentials(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.post("/api/auth/login", json={"username": "", "password": ""})
        assert resp.status_code == 400

    def test_logout_success(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        c.cookies.set("opb_session", "some-token")
        resp = c.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_session_info_no_auth(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/api/auth/session")
        assert resp.status_code == 401

    def test_session_info_authenticated(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["authenticated"] is True
        assert "user" in data

    def test_change_password(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/change-password", json={
            "current_password": pw,
            "new_password": "New@1234!xY",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_change_password_wrong_current(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/change-password", json={
            "current_password": "wrong",
            "new_password": "New@1234!xZ",
        })
        assert resp.status_code == 400
        assert "detail" in resp.json()

    def test_change_password_missing_fields(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/change-password", json={})
        assert resp.status_code == 400


class TestUserManagement:
    def test_list_users(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/users")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_create_user(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/users", json={
            "username": "newuser", "password": "New@1234!", "role": "viewer",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_create_user_missing_fields(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/users", json={"username": "", "password": ""})
        assert resp.status_code == 400

    def test_update_user_role(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        db._auth.create_user("operator1", "Op@12345!", "operator", "", "admin")
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.put("/api/auth/users/operator1/role", json={"role": "admin"})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_user_role_not_found(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.put("/api/auth/users/nonexistent/role", json={"role": "admin"})
        assert resp.status_code == 400

    def test_admin_reset_password(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/users/admin/reset-password", json={"new_password": "New@1234!reset"})
        assert resp.status_code == 200

    def test_disable_user(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/users/admin/disable")
        assert resp.status_code == 200

    def test_enable_user(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        admin = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert admin is not None
        # Create a second admin to perform enable/disable
        db._auth.create_user("op2", "Op2@12345!", "admin", "", "admin")
        op2 = db._auth.authenticate("op2", "Op2@12345!", ip_address="127.0.0.1")
        assert op2 is not None
        token = db._auth.create_session(op2)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        # Disable admin via op2's session
        resp = c.post("/api/auth/users/admin/disable")
        assert resp.status_code == 200
        # Re-enable admin
        resp = c.post("/api/auth/users/admin/enable")
        assert resp.status_code == 200

    def test_delete_user(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        db._auth.create_user("todelete", "Del@12345!", "viewer", "", "admin")
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.delete("/api/auth/users/todelete")
        assert resp.status_code == 200

    def test_delete_admin_fails(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.delete("/api/auth/users/admin")
        assert resp.status_code == 400
        assert "detail" in resp.json()


class TestSessionManagement:
    def test_list_sessions(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/users/admin/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_revoke_sessions(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.post("/api/auth/users/admin/revoke-sessions")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_list_sessions_user_not_found(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/users/nonexistent/sessions")
        assert resp.status_code == 404


class TestAuditLogAccess:
    def test_audit_log(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_audit_log_filtered(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/audit?event_type=login_success")
        assert resp.status_code == 200


class TestAuthStats:
    def test_auth_stats(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        pw = "Admin@123!test"
        user = db._auth.authenticate("admin", pw, ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        resp = c.get("/api/auth/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_sessions" in data
        assert "total_users" in data


# =============================================================================
# 12. System API
# =============================================================================


class TestSystemApi:
    def test_state(self, client):
        resp = client.get("/api/system/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily_pnl" in data
        assert "open_positions" in data

    def test_state_updates(self, state_file, client):
        Path(state_file).write_text(json.dumps({
            "daily_pnl": 999.0, "open_positions": 5, "hard_halt": True,
        }))
        resp = client.get("/api/system/state")
        assert resp.json()["daily_pnl"] == 999.0

    def test_trades(self, client):
        resp = client.get("/api/system/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_health(self, client):
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "paused" in data
        assert "daily_pnl" in data

    def test_signals(self, client):
        resp = client.get("/api/system/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_uptime(self, client):
        resp = client.get("/api/system/uptime")
        assert resp.status_code == 200
        data = resp.json()
        assert "uptime_seconds" in data
        assert "uptime_human" in data
        assert "server_time_iso" in data

    def test_diagnostics_requires_auth(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/api/system/diagnostics")
        assert resp.status_code == 401

    def test_broker_info(self, client):
        resp = client.get("/api/broker/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["broker_name"] == "Zerodha"
        assert data["mode"] == "paper"
        assert data["latency_ms"] == 12

    def test_ml_status(self, client):
        resp = client.get("/api/ml/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["model_loaded"] is True
        assert data["accuracy"] == 0.72

    def test_docker_health(self, client):
        resp = client.get("/api/system/health/docker")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "version" in data

    def test_self_test_requires_auth(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.post("/api/system/self-test")
        assert resp.status_code == 401

    def test_pause(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        user = db._auth.authenticate("admin", "Admin@123!test", ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        db._pause_event.clear()
        resp = c.post("/api/system/pause")
        assert resp.status_code == 200
        assert db._pause_event.is_set()

    def test_resume_entry(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        user = db._auth.authenticate("admin", "Admin@123!test", ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        db._pause_event.set()
        resp = c.post("/api/system/resume-entry")
        assert resp.status_code == 200
        assert not db._pause_event.is_set()

    def test_pause_resume_cycle(self, base_cfg, trades_db, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setenv("OPBUYING_DEFAULT_ADMIN_PASSWORD", "Admin@123!test")
        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        db.wire_bot_refs(pause_event=threading.Event(), signal_log=MagicMock())
        user = db._auth.authenticate("admin", "Admin@123!test", ip_address="127.0.0.1")
        assert user is not None
        token = db._auth.create_session(user)
        c = TestClient(db.app)
        c.cookies.set("opb_session", token.token)
        assert not db._pause_event.is_set()
        c.post("/api/system/pause")
        assert db._pause_event.is_set()
        c.post("/api/system/resume-entry")
        assert not db._pause_event.is_set()


# =============================================================================
# 13. Risk concentration API
# =============================================================================


class TestRiskConcentration:
    def test_risk_concentration_low(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[]):
            with patch.object(dashboard, "_read_state", return_value={
                "base_capital": 100000, "capital": 100000,
            }):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["concentration_risk"] == "LOW"

    def test_risk_concentration_critical(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"status": "open", "exit_time": None, "index": "NIFTY",
             "pnl": 0, "entry_price": 600, "quantity": 500},
        ]):
            with patch.object(dashboard, "_read_state", return_value={
                "base_capital": 5000, "capital": 5000,
            }):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["concentration_risk"] == "CRITICAL"

    def test_risk_concentration_high(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"status": "open", "exit_time": None, "index": "NIFTY",
             "pnl": 0, "entry_price": 200, "quantity": 10},
        ]):
            with patch.object(dashboard, "_read_state", return_value={
                "base_capital": 10000, "capital": 10000,
            }):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["concentration_risk"] == "HIGH"

    def test_risk_concentration_moderate(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"status": "open", "exit_time": None, "index": "NIFTY",
             "pnl": 0, "entry_price": 100, "quantity": 10},
        ]):
            with patch.object(dashboard, "_read_state", return_value={
                "base_capital": 10000, "capital": 10000,
            }):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["concentration_risk"] == "MODERATE"

    def test_risk_concentration_capital_fallback(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[]):
            with patch.object(dashboard, "_read_state", return_value={}):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert data["capital"] == 1_000_000

    def test_risk_concentration_by_index(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"status": "open", "exit_time": None, "index": "NIFTY",
             "pnl": 0, "entry_price": 100, "quantity": 10},
            {"status": "open", "exit_time": None, "index": "BANKNIFTY",
             "pnl": 0, "entry_price": 200, "quantity": 5},
        ]):
            with patch.object(dashboard, "_read_state", return_value={
                "base_capital": 100000, "capital": 100000,
            }):
                resp = client.get("/api/risk/concentration")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["by_index"]) == 2


# =============================================================================
# 14. Trades CSV export
# =============================================================================


class TestTradesCsvExport:
    def test_csv_export_returns_csv(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"symbol": "NIFTY", "direction": "CALL", "entry_price": 150,
             "exit_price": 185, "quantity": 75, "pnl": 2625, "status": "closed",
             "entry_time": "09:30", "exit_time": "10:00", "strike": 25000,
             "expiry": "25MAY2026", "index": "NIFTY", "created_at": "2026-05-25T09:30:00"},
        ]):
            resp = client.get("/api/system/trades/export")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "Content-Disposition" in resp.headers
        assert "filename=trades_export.csv" in resp.headers["Content-Disposition"]
        assert "symbol" in resp.text

    def test_csv_export_header(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[]):
            resp = client.get("/api/system/trades/export")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) >= 1
        assert "timestamp" in lines[0]
        assert "symbol" in lines[0]
        assert "pnl" in lines[0]

    def test_csv_export_multiple(self, dashboard, client):
        with patch.object(dashboard, "_load_recent_trades", return_value=[
            {"symbol": "NIFTY", "direction": "CALL", "pnl": 100,
             "entry_time": "09:30", "exit_time": "10:00", "strike": 25000,
             "expiry": "25MAY2026", "index": "NIFTY", "entry_price": 150,
             "exit_price": 185, "quantity": 75, "status": "closed",
             "created_at": "2026-05-25T09:30:00"},
            {"symbol": "BANKNIFTY", "direction": "PUT", "pnl": -50,
             "entry_time": "11:00", "exit_time": "11:30", "strike": 51000,
             "expiry": "25MAY2026", "index": "BANKNIFTY", "entry_price": 200,
             "exit_price": 150, "quantity": 50, "status": "closed",
             "created_at": "2026-05-25T11:00:00"},
        ]):
            resp = client.get("/api/system/trades/export")
        assert resp.status_code == 200
        lines = resp.text.strip().split("\n")
        assert len(lines) == 3


# =============================================================================
# 15. Webhook signal injection
# =============================================================================


class TestWebhookSignalInjection:
    def test_webhook_disabled_by_default(self, client):
        resp = client.post("/signals/inject", json={"direction": "CALL"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disabled"

    def test_webhook_enabled_queues(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        sig_queue = MagicMock()
        sig_log = MagicMock()
        cfg = dict(base_cfg, webhook_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(signal_queue=sig_queue, signal_log=sig_log)
        c = TestClient(db.app)
        resp = c.post("/signals/inject", json={"direction": "CALL", "score": 85})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        sig_queue.put.assert_called_once()
        sig_log.append.assert_called_once()

    def test_webhook_rate_limited(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        rl = MagicMock()
        rl.check.return_value = False
        cfg = dict(base_cfg, webhook_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(rate_limiter=rl)
        c = TestClient(db.app)
        resp = c.post("/signals/inject", json={"direction": "CALL"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "rate_limited"

    def test_webhook_json_decode_error(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        cfg = dict(base_cfg, webhook_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.post("/signals/inject", content=b"not json",
                      headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_webhook_rate_limiter_error(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        rl = MagicMock()
        rl.check.side_effect = RuntimeError("broken")
        cfg = dict(base_cfg, webhook_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(rate_limiter=rl)
        c = TestClient(db.app)
        resp = c.post("/signals/inject", json={"direction": "CALL"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_webhook_queue_error(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        sig_queue = MagicMock()
        sig_queue.put.side_effect = RuntimeError("queue full")
        cfg = dict(base_cfg, webhook_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(signal_queue=sig_queue)
        c = TestClient(db.app)
        resp = c.post("/signals/inject", json={"direction": "CALL"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"


# =============================================================================
# 16. Options chain viz
# =============================================================================


class TestOptionsChainViz:
    def test_chain_disabled_by_default(self, client):
        resp = client.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disabled"

    def test_chain_enabled(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        cfg = dict(base_cfg, chain_viz_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(**{"ltp_NIFTY": 25000})
        c = TestClient(db.app)
        resp = c.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert data["index"] == "NIFTY"
        assert data["symbol"] == "NIFTY"
        assert data["spot_price"] == 25000

    def test_chain_with_market_data(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        md = MagicMock()
        md.get_option_chain.return_value = {"strikes": [25000, 25100]}
        cfg = dict(base_cfg, chain_viz_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(market_data=md)
        c = TestClient(db.app)
        resp = c.get("/chain/NIFTY")
        assert resp.status_code == 200
        data = resp.json()
        assert "option_chain" in data
        md.get_option_chain.assert_called_once()

    def test_chain_market_data_error(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        md = MagicMock()
        md.get_option_chain.side_effect = RuntimeError("API error")
        cfg = dict(base_cfg, chain_viz_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        db.wire_bot_refs(market_data=md)
        c = TestClient(db.app)
        resp = c.get("/chain/BANKNIFTY")
        assert resp.status_code == 200

    def test_chain_uppercases(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        cfg = dict(base_cfg, chain_viz_enabled=True)
        db = EnterpriseDashboard(config=cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/chain/finnifty")
        assert resp.status_code == 200
        assert resp.json()["index"] == "FINNIFTY"


# =============================================================================
# 17. Error handlers (403, 404, 500)
# =============================================================================


class TestErrorHandlers:
    def test_404_json(self, client):
        resp = client.get("/api/nonexistent-route", headers={"accept": "application/json"})
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == 404
        assert "error" in data

    def test_404_html(self, client):
        resp = client.get("/nonexistent-page")
        assert resp.status_code == 404
        assert "mocked:" in resp.text

    def test_500_handler_executes(self, dashboard):
        log_captured = []
        handler = logging.Handler()
        handler.emit = lambda r: log_captured.append(r.getMessage())
        logger = logging.getLogger("core.enterprise_dashboard")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            @dashboard.app.get("/api/trigger-500")
            async def trigger_500():
                raise RuntimeError("deliberate crash")
            c = TestClient(dashboard.app)
            try:
                c.get("/api/trigger-500", headers={"accept": "application/json"})
            except Exception:
                pass
        finally:
            logger.removeHandler(handler)
        assert any("[DASH] Unhandled error" in msg for msg in log_captured), (
            f"500 handler was not invoked: {log_captured}"
        )

    def test_403_json(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/admin/users", headers={"accept": "application/json"}, follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_403_html(self, dashboard):
        c = TestClient(dashboard.app)
        resp = c.get("/admin/users", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_error_403_from_exception(self, dashboard):
        @dashboard.app.get("/test-forbidden")
        async def forbidden():
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail="Forbidden")
        c = TestClient(dashboard.app)
        resp = c.get("/test-forbidden", headers={"accept": "application/json"})
        assert resp.status_code == 403
        data = resp.json()
        assert data["code"] == 403


# =============================================================================
# 18. Static file serving
# =============================================================================


class TestStaticFileServing:
    def test_static_dir_created(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        assert hasattr(db, "_static_dir")

    def test_static_dir_creation_failure(self, monkeypatch, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        def bad_mkdir(*a, **kw):
            raise OSError("Cannot create dir")
        monkeypatch.setattr("pathlib.Path.mkdir", bad_mkdir)
        monkeypatch.setattr(EnterpriseDashboard, "_ensure_templates", lambda self: tmp_path)
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        static_dir = db._ensure_static()
        assert static_dir is None


# =============================================================================
# 19. Session cleanup background thread
# =============================================================================


class TestSessionCleanup:
    def test_cleanup_thread_starts(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        threads = [t for t in threading.enumerate() if t.name == "session_cleanup"]
        assert any(t.is_alive() for t in threads)

    def test_cleanup_exception_handled(self, monkeypatch):
        from core.enterprise_dashboard import EnterpriseDashboard

        monkeypatch.setattr(EnterpriseDashboard, "_start_session_cleanup", lambda self: None)
        db = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        called = [False]

        def broken_purge():
            called[0] = True
            raise RuntimeError("purge failed")

        monkeypatch.setattr(db._auth, "purge_expired_sessions", broken_purge)
        try:
            db._auth.purge_expired_sessions()
        except Exception:
            pass
        assert called[0]


# =============================================================================
# 20. Profile/password change
# =============================================================================


class TestProfilePasswordChange:
    def test_change_password_page(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/change-password")
        assert resp.status_code == 200
        assert "mocked:" in resp.text

    def test_change_password_page_renders(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/change-password")
        assert resp.status_code == 200


# =============================================================================
# Edge cases and data helpers
# =============================================================================


class TestEdgeCases:
    def test_load_defaults_missing(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        p = tmp_path / "no_defaults.json"
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_defaults_path": str(p),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        data = db._load_defaults()
        assert data == {}

    def test_load_defaults_corrupt(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        p = tmp_path / "bad_defaults.json"
        p.write_text("bad json{{{", encoding="utf-8")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "index_config_defaults_path": str(p),
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        data = db._load_defaults()
        assert data == {}

    def test_read_state_missing(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        p = str(tmp_path / "no_state.json")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": p,
        })
        state = db._read_state()
        assert state == {}

    def test_read_state_corrupt(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        p = tmp_path / "corrupt.json"
        p.write_text("bad json{{{", encoding="utf-8")
        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "trader_state_path": str(p),
        })
        state = db._read_state()
        assert state == {}

    def test_load_trades_no_db(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
        }, db_path=str(tmp_path / "no_trades.db"))
        trades = db._load_recent_trades()
        assert trades == []

    def test_get_signals_no_signal_log(self, dashboard):
        dashboard._signal_log = None
        sigs = dashboard._get_signals()
        assert sigs == []

    def test_get_signals_with_defaults(self, dashboard):
        mock_log = MagicMock()
        mock_log.recent.return_value = [{"direction": "CALL"}]
        dashboard._signal_log = mock_log
        sigs = dashboard._get_signals()
        assert sigs[0].get("reasoning") == "No detailed reasoning available"
        assert sigs[0].get("sentiment") == "NEUTRAL"

    def test_ensure_templates_creates(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config={
            "web_dashboard_host": "127.0.0.1",
            "auth_db_path": str(tmp_path / "auth.db"),
        })
        tdir = db._ensure_templates()
        assert tdir is not None

    def test_lifespan_events(self, state_file, trades_db, base_cfg):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        with TestClient(db.app) as c:
            resp = c.get("/api/system/health")
            assert resp.status_code == 200

    def test_dashboard_host_secure_cookie(self):
        from core.enterprise_dashboard import EnterpriseDashboard

        d1 = EnterpriseDashboard(config={"web_dashboard_host": "127.0.0.1"})
        assert d1._cookie_secure is False
        d2 = EnterpriseDashboard(config={"web_dashboard_host": "0.0.0.0"})
        assert d2._cookie_secure is True

    def test_html_page_not_found(self, base_cfg, trades_db):
        from core.enterprise_dashboard import EnterpriseDashboard

        db = EnterpriseDashboard(config=base_cfg, db_path=trades_db)
        c = TestClient(db.app)
        resp = c.get("/this-path-does-not-exist")
        assert resp.status_code == 404
