import pytest

from core.admin_portfolio_analyzer import (
    INDIAN_BROKERS,
    AdminPortfolioAnalyzer,
    PortfolioPosition,
    get_admin_portfolio_analyzer,
)

pytest.importorskip("fastapi")


def _admin_test_client():
    """Build a TestClient logged in as an admin.

    /admin/portfolio-analyzer now requires admin auth (it previously had no
    auth check at all - see docs/COMPLETE_USER_GUIDE_AND_MANUAL.md §8) so
    tests exercising it need a real authenticated session, same pattern as
    tests/test_all_ui_screens_and_navigation.py's dashboard_client fixture.
    """
    from fastapi.testclient import TestClient
    from core.enterprise_dashboard import EnterpriseDashboard

    d = EnterpriseDashboard()
    client = TestClient(d.app)
    auth = d._auth
    user = auth.get_user("admin")
    if not user:
        res = auth.create_user("admin", "AdminPassword123!", role="admin")
        user = auth.get_user_by_id(res["user_id"])
    session = auth.create_session(user)
    client.cookies.set("opb_session", session.token)
    return d, client


def test_indian_brokers_metadata() -> None:
    """Verify all major Indian brokers are supported in metadata registry."""
    analyzer = get_admin_portfolio_analyzer()
    assert "zerodha" in INDIAN_BROKERS
    assert "angelone" in INDIAN_BROKERS
    assert "iifl" in INDIAN_BROKERS
    assert "upstox" in INDIAN_BROKERS
    assert "groww" in INDIAN_BROKERS
    assert "icicidirect" in INDIAN_BROKERS
    assert "dhan" in INDIAN_BROKERS
    assert "fyers" in INDIAN_BROKERS
    assert "mstock" in INDIAN_BROKERS

    info = analyzer.get_broker_info("mstock")
    assert info["name"] == "m.Stock (Mirae Asset)"
    assert info["supports_oauth"] is True


def test_portfolio_parsing_and_sector_inference() -> None:
    """Test normalized portfolio parsing from raw broker holdings."""
    analyzer = AdminPortfolioAnalyzer()
    raw = [
        {"symbol": "RELIANCE", "quantity": 100, "buy_price": 2800.0, "current_price": 3000.0},
        {"symbol": "HDFCBANK", "quantity": 200, "buy_price": 1600.0, "current_price": 1400.0},
        {"symbol": "NIFTY 24200 CE", "quantity": 50, "buy_price": 150.0, "current_price": 120.0},
    ]

    positions = analyzer.parse_portfolio(raw)
    assert len(positions) == 3
    assert positions[0].symbol == "RELIANCE"
    assert positions[0].sector == "Energy & Oil"
    assert positions[1].symbol == "HDFCBANK"
    assert positions[1].sector == "Banking & Finance"
    assert positions[2].asset_class == "Option"


def test_16_strategy_deep_scan_and_guidance() -> None:
    """Test 16-strategy diagnostic scan and stock action decisions."""
    analyzer = AdminPortfolioAnalyzer()
    positions = [
        PortfolioPosition("RELIANCE", "Equity", 100, 2500.0, 3000.0, 300000.0, 50000.0, 20.0, "Energy & Oil"),
        PortfolioPosition("HDFCBANK", "Equity", 200, 1700.0, 1300.0, 260000.0, -80000.0, -23.5, "Banking & Finance"),
        PortfolioPosition("NIFTY 24200 CE", "Option", 100, 150.0, 100.0, 10000.0, -5000.0, -33.3, "Options"),
    ]

    report = analyzer.run_16_strategy_deep_scan("Gaurav Admin Test", "zerodha", positions)

    assert report["user_name"] == "Gaurav Admin Test"
    assert report["strategies_applied_count"] == 16
    assert "portfolio_health_score" in report
    assert len(report["stock_guidance"]) == 3

    # HDFCBANK (-23.5% loss drag) should trigger SELL_IMMEDIATELY
    hdfc_guidance = next(g for g in report["stock_guidance"] if g["symbol"] == "HDFCBANK")
    assert hdfc_guidance["action"] == "SELL_IMMEDIATELY"
    assert "Exit Today" in hdfc_guidance["holding_period"]
    assert len(hdfc_guidance["shap_attribution"]) > 0

    # Regression: stock_guidance previously had no real quantity/pnl_pct at
    # all - the admin_portfolio_analyzer.html frontend fell back to the
    # page-wide position count and two hardcoded -15.4%/+18.2% literals for
    # every row. These must now be the real per-position values.
    assert hdfc_guidance["quantity"] == 200
    assert hdfc_guidance["pnl_pct"] == -23.5

    # RELIANCE (+20.0% gain) should trigger SELL_FUTURE
    reliance_guidance = next(g for g in report["stock_guidance"] if g["symbol"] == "RELIANCE")
    assert reliance_guidance["action"] == "SELL_FUTURE"
    assert "STAGED" in reliance_guidance["action_label"]

    # Option position should trigger REBALANCE_HEDGE
    option_guidance = next(g for g in report["stock_guidance"] if "NIFTY" in g["symbol"])
    assert option_guidance["action"] == "REBALANCE_HEDGE"


def test_admin_portfolio_analyzer_page_renders_200() -> None:
    """End-to-end test that Portfolio Inspector HTML page renders cleanly with 200 OK
    for an authenticated admin (the route requires admin auth)."""
    _d, client = _admin_test_client()
    resp = client.get("/admin/portfolio-analyzer")
    assert resp.status_code == 200
    assert "Admin Multi-Broker Portfolio Inspector" in resp.text
    assert "Zerodha (Kite)" in resp.text
    assert "IIFL Markets" in resp.text
    assert "results-container" in resp.text


def test_admin_portfolio_analyzer_page_requires_admin_auth() -> None:
    """Regression: this page previously had no auth check at all."""
    from fastapi.testclient import TestClient
    from core.enterprise_dashboard import EnterpriseDashboard

    d = EnterpriseDashboard()
    client = TestClient(d.app, follow_redirects=False)
    resp = client.get("/admin/portfolio-analyzer")
    assert resp.status_code in (401, 403)


def test_admin_analyze_portfolio_api_with_csrf() -> None:
    """Test POST /api/v1/admin/analyze-portfolio endpoint with full CSRF lifecycle."""
    _d, client = _admin_test_client()

    # Establish session & CSRF cookie
    r_get = client.get("/admin/portfolio-analyzer")
    csrf_token = r_get.cookies.get("opb_csrf", "test_csrf_token")

    payload = {
        "user_name": "Gaurav Comprehensive Test",
        "broker_code": "iifl",
        "positions": [
            {"symbol": "RELIANCE", "quantity": 100, "buy_price": 2800.0, "current_price": 3050.0, "sector": "Energy & Oil"},
            {"symbol": "HDFCBANK", "quantity": 200, "buy_price": 1650.0, "current_price": 1400.0, "sector": "Banking & Finance"},
            {"symbol": "TCS", "quantity": 50, "buy_price": 3800.0, "current_price": 4200.0, "sector": "Information Technology"},
            {"symbol": "NIFTY 24200 CE", "quantity": 150, "buy_price": 180.0, "current_price": 130.0, "sector": "Options"},
        ]
    }

    resp = client.post(
        "/api/v1/admin/analyze-portfolio",
        json=payload,
        headers={"X-CSRF-Token": csrf_token},
        cookies={"opb_csrf": csrf_token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["portfolio_health_score"] > 0
    assert len(data["stock_guidance"]) == 4


def test_admin_auxiliary_apis() -> None:
    """Test HUD status, Auto-Hedge, Tax-Loss, and Report Generator APIs."""
    _d, client = _admin_test_client()

    r_get = client.get("/admin/portfolio-analyzer")
    csrf_token = r_get.cookies.get("opb_csrf", "test_csrf_token")
    headers = {"X-CSRF-Token": csrf_token}
    cookies = {"opb_csrf": csrf_token}

    # 1. HUD System Status
    r_hud = client.get("/api/v1/admin/system-status")
    assert r_hud.status_code == 200
    assert "redis_connected" in r_hud.json()

    # 2. Auto-Hedge Gate
    r_hedge = client.post(
        "/api/v1/admin/execute-hedge",
        json={"instrument": "NIFTY 24200 CE", "action": "BUY_PUT", "is_dry_run": True},
        headers=headers,
        cookies=cookies,
    )
    assert r_hedge.status_code == 200

    # 3. Tax Loss Harvest
    r_tax = client.post(
        "/api/v1/admin/tax-loss-harvest",
        json={"positions": []},
        headers=headers,
        cookies=cookies,
    )
    assert r_tax.status_code == 200

    # 4. Report Generator
    r_rep = client.post(
        "/api/v1/admin/generate-report",
        json={"portfolio_health_score": 88, "stock_guidance": []},
        headers=headers,
        cookies=cookies,
    )
    assert r_rep.status_code == 200


def test_broker_info_and_fetch_holdings_apis() -> None:
    """Test GET /api/v1/admin/broker/info/{code} and POST /api/v1/admin/broker/fetch-holdings."""
    _d, client = _admin_test_client()

    # 1. Broker Info API
    # NOTE: the CSRF cookie is only issued on the *first* GET in a fresh
    # client (ensure_cookie_set no-ops once a cookie already exists in the
    # jar, core/auth/csrf.py:61-63) - so it must be captured here, not from
    # a later GET, or csrf_token below silently falls back to a placeholder
    # that no longer matches the jar's real cookie and every POST 403s.
    r_info = client.get("/api/v1/admin/broker/info/iifl")
    assert r_info.status_code == 200
    info_data = r_info.json()
    assert info_data["name"] == "IIFL Markets"
    assert "auth_url" in info_data
    csrf_token = r_info.cookies.get("opb_csrf", "test_csrf_token")

    # 2. Fetch Holdings API

    r_fetch = client.post(
        "/api/v1/admin/broker/fetch-holdings",
        json={"broker_code": "iifl"},
        headers={"X-CSRF-Token": csrf_token},
        cookies={"opb_csrf": csrf_token},
    )
    assert r_fetch.status_code == 200
    fetch_data = r_fetch.json()
    assert fetch_data["status"] == "success"
    assert fetch_data["broker_code"] == "iifl"
    assert fetch_data["count"] > 0
    assert any(h["symbol"] == "IIFL" for h in fetch_data["holdings"])


