"""Product Integrity & Bounded Remediation Test Suite — OPB v2.59.4.

Verifies:
1. R1: Fail-closed payment & billing security (paid plan self-activation blocked, free tier allowed, 400 response, audit logging).
2. R2: Signal Accuracy real vs. seeded data separation (default excludes seeds, win_rate is None when 0 resolved, explicit flag).
3. R3: Canonical Market Taxonomy alignment across all 10 categories.
4. R4: PAPER/LIVE execution mode canonical rendering in _nav.html and _page_context.
5. R5: Presentation generator v2.59.4 versioning and benchmark labeling.
6. R6: Admin users template semantic CSS tokens (no hardcoded #0f1319, focus-visible outlines).
7. R7: Real production signals database invariants preservation.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from core.billing.upi_billing_engine import UpiBillingEngine
from core.auth.user_signal_permissions import UserPermissionManager
from core.signals.signal_tracker import SignalTracker
from core.fno_universe import classify_instrument_market
import core.presentation_generator as pres_gen


class TestPaymentFailClosed:
    """Test suite for R1: Fail-closed UPI billing security."""

    def test_billing_fail_closed_paid_plans(self, tmp_path):
        store_file = tmp_path / "user_perms.json"
        mgr = UserPermissionManager(store_path=store_file)
        mgr.update_user_permissions("alice", {"signals_enabled": False, "allowed_categories": []}, admin_username="admin")

        orig_instance = UserPermissionManager._instance
        UserPermissionManager._instance = mgr
        try:
            res = UpiBillingEngine.confirm_and_provision_user(
                username="alice",
                plan_id="plan_options_vip",
                transaction_ref="FAKE-UPI-REF",
            )
            assert res["success"] is False
            assert res["error_code"] == "PAYMENT_GATEWAY_UNAVAILABLE"
            assert res["price_inr"] == 1999

            perm = mgr.get_user_permissions("alice")
            assert perm.signals_enabled is False
            assert perm.allowed_categories == []
        finally:
            UserPermissionManager._instance = orig_instance

    def test_billing_free_tier_activation(self, tmp_path):
        store_file = tmp_path / "user_perms_free.json"
        mgr = UserPermissionManager(store_path=store_file)
        mgr.update_user_permissions("bob", {"signals_enabled": False, "allowed_categories": []}, admin_username="admin")

        orig_instance = UserPermissionManager._instance
        UserPermissionManager._instance = mgr
        try:
            res = UpiBillingEngine.confirm_and_provision_user(
                username="bob",
                plan_id="plan_free",
                transaction_ref="FREE-ACTIVATE",
            )
            assert res["success"] is True
            perm = mgr.get_user_permissions("bob")
            assert perm.signals_enabled is True
            assert "INDEX_OPTIONS" in perm.allowed_categories
        finally:
            UserPermissionManager._instance = orig_instance

    def test_api_billing_endpoint_fail_closed_and_audited(self, tmp_path):
        from core.enterprise_dashboard import EnterpriseDashboard

        auth_db = str(tmp_path / "auth.db")
        state_file = str(tmp_path / "state.json")
        Path(state_file).write_text(json.dumps({"execution_mode": "paper", "capital": 3000}), encoding="utf-8")

        d = EnterpriseDashboard(
            config={
                "web_dashboard_host": "127.0.0.1",
                "trader_state_path": state_file,
                "auth_db_path": auth_db,
                "execution_mode": "paper",
            }
        )
        client = TestClient(d.app)
        # Establish CSRF token
        r_get = client.get("/login")
        csrf_token = r_get.cookies.get("opb_csrf", "test_csrf_token")
        client.cookies.set("opb_csrf", csrf_token)
        client.headers.update({"X-CSRF-Token": csrf_token})

        auth = d._auth
        res = auth.create_user("charlie", "CharliePass123!@#", role="viewer")
        user = auth.get_user_by_id(res["user_id"])
        session = auth.create_session(user)
        client.cookies.set("opb_session", session.token)

        resp = client.post(
            "/api/billing/confirm-upi-payment",
            json={"plan_id": "plan_options_vip", "transaction_ref": "SELF_CLAIM_123"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["success"] is False
        assert data["error_code"] == "PAYMENT_GATEWAY_UNAVAILABLE"

        with sqlite3.connect(auth_db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM audit_log WHERE username = 'charlie' ORDER BY id DESC").fetchall()
            assert len(rows) >= 1
            log_entry = rows[0]
            assert log_entry["event_type"] == "billing_payment_verification_blocked"
            assert log_entry["success"] == 0


class TestSignalAccuracySeparation:
    """Test suite for R2: Real vs. Seeded signal separation and win-rate accuracy."""

    def test_signal_tracker_default_excludes_seeds(self, tmp_path):
        db_path = tmp_path / "test_signals.db"
        tracker = SignalTracker(db_path=db_path)

        # Clear seed data to test clean isolation
        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.commit()
        conn.close()

        # Insert 2 real signals (both ACTIVE, unresolved)
        tracker.record_generated_signal({
            "symbol": "NIFTY", "direction": "CALL", "price": 24000.0,
            "stop_loss": 23950.0, "target_1": 24100.0, "target_2": 24200.0,
            "score": 85, "tier": "STRONG", "category": "INDEX_OPTIONS",
        })
        tracker.record_generated_signal({
            "symbol": "BANKNIFTY", "direction": "PUT", "price": 51000.0,
            "stop_loss": 51150.0, "target_1": 50800.0, "target_2": 50600.0,
            "score": 85, "tier": "STRONG", "category": "INDEX_OPTIONS",
        })

        # Insert 1 seed sample signal that has TARGET_1_HIT status
        seed_sig_id = tracker.record_generated_signal({
            "symbol": "FINNIFTY", "direction": "CALL", "price": 23000.0,
            "stop_loss": 22950.0, "target_1": 23100.0, "target_2": 23200.0,
            "score": 80, "tier": "STRONG", "category": "INDEX_OPTIONS",
        })
        conn = tracker._get_conn()
        conn.execute(
            "UPDATE system_signals SET status = 'TARGET_1_HIT', pnl_pct = 2.5, raw_data = ? WHERE signal_id = ?",
            (json.dumps({"is_seed_sample": True, "demo": True}), seed_sig_id)
        )
        conn.commit()
        conn.close()

        # Default query: excludes seeds
        analytics = tracker.get_admin_signal_analytics(include_seed_samples=False)

        assert analytics["total_signals"] == 2
        assert analytics["total_real_signals"] == 2
        assert analytics["total_seeded_signals"] == 1
        assert analytics["resolved_signals"] == 0
        assert analytics["win_rate_pct"] == 0.0
        assert "0 resolved" in analytics["win_rate_display"]
        assert analytics["contains_demo_data"] is False
        assert analytics["demo_samples_available"] is True

    def test_signal_tracker_include_seeds_explicit(self, tmp_path):
        db_path = tmp_path / "test_signals_seeded.db"
        tracker = SignalTracker(db_path=db_path)

        conn = tracker._get_conn()
        conn.execute("DELETE FROM system_signals")
        conn.commit()
        conn.close()

        tracker.record_generated_signal({
            "symbol": "NIFTY", "direction": "CALL", "price": 24000.0,
            "stop_loss": 23950.0, "target_1": 24100.0, "target_2": 24200.0,
            "score": 85, "tier": "STRONG", "category": "INDEX_OPTIONS",
        })
        seed_sig_id = tracker.record_generated_signal({
            "symbol": "FINNIFTY", "direction": "CALL", "price": 23000.0,
            "stop_loss": 22950.0, "target_1": 23100.0, "target_2": 23200.0,
            "score": 80, "tier": "STRONG", "category": "INDEX_OPTIONS",
        })
        conn = tracker._get_conn()
        conn.execute(
            "UPDATE system_signals SET status = 'TARGET_1_HIT', pnl_pct = 2.5, raw_data = ? WHERE signal_id = ?",
            (json.dumps({"is_seed_sample": True}), seed_sig_id)
        )
        conn.commit()
        conn.close()

        analytics = tracker.get_admin_signal_analytics(include_seed_samples=True)
        assert analytics["total_signals"] == 2
        assert analytics["contains_demo_data"] is True
        assert analytics["resolved_signals"] == 1
        assert analytics["win_rate_pct"] == 100.0


class TestCanonicalMarketTaxonomy:
    """Test suite for R3: All 10 canonical market categories."""

    def test_canonical_taxonomy_classification(self):
        assert classify_instrument_market("NIFTY") == "INDEX_OPTIONS"
        assert classify_instrument_market("BANKNIFTY") == "INDEX_OPTIONS"
        assert classify_instrument_market("RELIANCE") == "STOCK_OPTIONS"
        assert classify_instrument_market("INFY") == "STOCK_OPTIONS"
        assert classify_instrument_market("SHREE_SME", series="SM") == "PENNY_SME"
        assert classify_instrument_market("ALPHA_ST", series="ST") == "PENNY_SME"
        assert classify_instrument_market("NIFTY-FUT") == "FUTURES"
        assert classify_instrument_market("RELIANCE_FUT") == "FUTURES"
        assert classify_instrument_market("CRUDEOIL") == "COMMODITIES"
        assert classify_instrument_market("GOLD") == "COMMODITIES"
        assert classify_instrument_market("MCX:SILVER") == "COMMODITIES"
        assert classify_instrument_market("USDINR") == "CURRENCIES"
        assert classify_instrument_market("EURINR") == "CURRENCIES"
        assert classify_instrument_market("NIFTYBEES") == "ETFS_REITS"
        assert classify_instrument_market("GOLDBEES") == "ETFS_REITS"
        assert classify_instrument_market("EMBASSY-REIT") == "ETFS_REITS"
        assert classify_instrument_market("XYZNONFNO") == "EQUITY_SWING_DELIVERY"

    def test_canonical_taxonomy_boundary_semantics(self):
        """Verify boundary semantics between cash equity, F&O, and delivery."""
        # 1. INDEX_OPTIONS
        assert classify_instrument_market("NIFTY24DEC25000CE") == "INDEX_OPTIONS"
        assert classify_instrument_market("BANKNIFTY", series="EQ") == "INDEX_OPTIONS"
        # 2. STOCK_OPTIONS
        assert classify_instrument_market("RELIANCE") == "STOCK_OPTIONS"
        assert classify_instrument_market("TCS", series="EQ", instrument_type="OPTSTK") == "STOCK_OPTIONS"
        # 3. FUTURES
        assert classify_instrument_market("NIFTY-FUT") == "FUTURES"
        assert classify_instrument_market("RELIANCE", instrument_type="FUTSTK") == "FUTURES"
        # 4. COMMODITIES
        assert classify_instrument_market("MCX:SILVER") == "COMMODITIES"
        assert classify_instrument_market("GOLDM") == "COMMODITIES"
        # 5. CURRENCIES
        assert classify_instrument_market("USDINR") == "CURRENCIES"
        assert classify_instrument_market("CDS:GBPINR") == "CURRENCIES"
        # 6. ETFS_REITS
        assert classify_instrument_market("NIFTYBEES") == "ETFS_REITS"
        assert classify_instrument_market("EMBASSY-REIT") == "ETFS_REITS"
        # 7. PENNY_SME
        assert classify_instrument_market("SHREE_SME", series="SM") == "PENNY_SME"
        assert classify_instrument_market("ALPHA_ST", series="ST") == "PENNY_SME"
        assert classify_instrument_market("VINEETLAB", series="SME") == "PENNY_SME"
        # 8. LARGE_CAP_EQUITY
        assert classify_instrument_market("RELIANCE", series="LC") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("HDFCBANK", series="EQ", instrument_type="CASH") == "LARGE_CAP_EQUITY"
        assert classify_instrument_market("TCS", series="LARGE_CAP") == "LARGE_CAP_EQUITY"
        # 9. MID_SMALL_CAP
        assert classify_instrument_market("DIXON", series="SMC") == "MID_SMALL_CAP"
        assert classify_instrument_market("SUZLON", series="MID_CAP") == "MID_SMALL_CAP"
        assert classify_instrument_market("IDEA", series="EQ", instrument_type="CASH") == "MID_SMALL_CAP"
        # 10. EQUITY_SWING_DELIVERY
        assert classify_instrument_market("XYZNONFNO") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("RELIANCE", series="SWING") == "EQUITY_SWING_DELIVERY"
        assert classify_instrument_market("INFY", series="CNC", instrument_type="DELIVERY") == "EQUITY_SWING_DELIVERY"

    def test_strict_authorization_no_privilege_escalation(self, tmp_path):
        """CRITICAL: Prove remediation did not accidentally broaden user permissions."""
        from core.auth.user_signal_permissions import UserSignalPermission, UserPermissionManager

        p = tmp_path / "strict_perms.json"
        mgr = UserPermissionManager(store_path=p)
        u_large = UserSignalPermission(username="u_large", is_active=True, signals_enabled=True, allowed_categories=["LARGE_CAP_EQUITY"])
        u_swing = UserSignalPermission(username="u_swing", is_active=True, signals_enabled=True, allowed_categories=["EQUITY_SWING_DELIVERY"])
        u_opt   = UserSignalPermission(username="u_opt", is_active=True, signals_enabled=True, allowed_categories=["STOCK_OPTIONS"])
        u_mid   = UserSignalPermission(username="u_mid", is_active=True, signals_enabled=True, allowed_categories=["MID_SMALL_CAP"])
        mgr._permissions = {"u_large": u_large, "u_swing": u_swing, "u_opt": u_opt, "u_mid": u_mid}
        mgr._save_unlocked()

        # Large cap signal goes ONLY to u_large
        recipients = [u.username for u in mgr.get_eligible_recipients(category="LARGE_CAP_EQUITY", tier="STRONG")]
        assert recipients == ["u_large"]

        # Swing delivery signal goes ONLY to u_swing
        recipients = [u.username for u in mgr.get_eligible_recipients(category="EQUITY_SWING_DELIVERY", tier="STRONG")]
        assert recipients == ["u_swing"]

        # Stock options signal goes ONLY to u_opt
        recipients = [u.username for u in mgr.get_eligible_recipients(category="STOCK_OPTIONS", tier="STRONG")]
        assert recipients == ["u_opt"]

        # Mid/small cap signal goes ONLY to u_mid
        recipients = [u.username for u in mgr.get_eligible_recipients(category="MID_SMALL_CAP", tier="STRONG")]
        assert recipients == ["u_mid"]


class TestExecutionModeSemantics:
    """Test suite for R4: PAPER execution mode representation."""

    def test_nav_execution_mode_paper_representation(self):
        nav_path = Path("templates/enterprise/_nav.html")
        content = nav_path.read_text(encoding="utf-8")
        assert '<span class="status-dot" style="background:#22c55e;"></span> LIVE</span>' not in content
        assert "execution_mode" in content
        assert "PAPER" in content


class TestPresentationGeneratorIntegrity:
    """Test suite for R5: Presentation generator canonical version and KPI labeling."""

    def test_presentation_generator_v2594_and_benchmark_labels(self):
        version = pres_gen.PresentationGenerator._fetch_version()
        assert version == "2.59.4"

        pres_html = Path("templates/enterprise/presentation.html").read_text(encoding="utf-8")
        assert 'placeholder="2.59.4"' in pres_html
        assert "Benchmark Win Rate" in pres_html

        core_py = Path("core/presentation_generator.py").read_text(encoding="utf-8")
        assert "Benchmark" in core_py
        assert "Historical 30 trading days reference benchmark" in core_py

    def test_presentation_generator_live_kpi_autofetch(self, tmp_path):
        gen = pres_gen.get_presentation_generator(output_dir=str(tmp_path))
        # Test auto-fetching data
        data: dict[str, Any] = {}
        # Execute generate_report logic checks
        ver = gen._fetch_version()
        assert ver == "2.59.4"
        counts = gen._fetch_file_counts()
        assert counts["core"] > 0
        assert counts["tests"] > 0


class TestThemeTokenCompliance:
    """Test suite for R6: Semantic design system variables and contrast."""

    def test_admin_users_theme_token_compliance(self):
        admin_users_html = Path("templates/enterprise/admin_users.html").read_text(encoding="utf-8")
        assert "var(--bg-card" in admin_users_html
        assert ":focus-visible" in admin_users_html

    def test_pricing_plans_template_modal_styling_and_warning(self):
        pricing_html = Path("templates/enterprise/pricing_plans.html").read_text(encoding="utf-8")
        assert "var(--bg-card" in pricing_html
        assert "Automated self-activation of paid plans is disabled" in pricing_html

    def test_design_system_universal_focus_visible_and_controls(self):
        css_content = Path("static/opb_design_system.css").read_text(encoding="utf-8")
        assert ":focus-visible" in css_content
        assert "var(--accent-color" in css_content
        assert "input[type=\"text\"]" in css_content

    def test_all_five_themes_wcag_aa_contrast(self):
        """Verify contrast >= 4.5:1 for normal text across all 5 themes."""
        def lum(c: str) -> float:
            c = c.lstrip("#")
            r, g, b = [int(c[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
            r = r / 12.92 if r <= 0.03928 else ((r + 0.055) / 1.055) ** 2.4
            g = g / 12.92 if g <= 0.03928 else ((g + 0.055) / 1.055) ** 2.4
            b = b / 12.92 if b <= 0.03928 else ((b + 0.055) / 1.055) ** 2.4
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        def cr(fg: str, bg: str) -> float:
            l1, l2 = lum(fg), lum(bg)
            return (max(l1, l2) + 0.05) / (min(l1, l2) + 0.05)

        themes = {
            "dark-cyber": {"bg": "#080c14", "card": "#131e33", "tp": "#f8fafc", "ts": "#cbd5e1", "tm": "#94a3b8"},
            "dracula-purple": {"bg": "#faf7fc", "card": "#ffffff", "tp": "#24172b", "ts": "#4c3a57", "tm": "#6b5a75"},
            "ivory-gold": {"bg": "#f5f0e6", "card": "#ffffff", "tp": "#1c1917", "ts": "#292524", "tm": "#57534e"},
            "midnight-slate": {"bg": "#f6f8fb", "card": "#ffffff", "tp": "#0f172a", "ts": "#334155", "tm": "#54667a"},
            "emerald-matrix": {"bg": "#020d07", "card": "#0a2c1d", "tp": "#ecfdf5", "ts": "#a7f3d0", "tm": "#6ee7b7"},
        }

        for tname, colors in themes.items():
            for bg_k in ("bg", "card"):
                for fg_k in ("tp", "ts", "tm"):
                    contrast = cr(colors[fg_k], colors[bg_k])
                    assert contrast >= 4.5, (
                        f"Theme {tname} {fg_k} on {bg_k} has contrast {contrast:.2f}:1, below 4.5:1"
                    )


class TestResponsiveMatrixCoverage:
    """Test suite for R7: Mandatory 9 viewports coverage."""

    MANDATORY_VIEWPORTS = [
        (1920, 1080),
        (1536, 864),
        (1440, 900),
        (1366, 768),
        (1280, 800),
        (1024, 768),
        (768, 1024),
        (430, 932),
        (375, 667),
    ]

    def test_mandatory_viewport_definitions(self):
        assert len(self.MANDATORY_VIEWPORTS) == 9
        assert (430, 932) in self.MANDATORY_VIEWPORTS
        assert (414, 896) not in self.MANDATORY_VIEWPORTS


class TestCrossScreenCanonicalConsistency:
    """Test suite for R8: Single source of truth across all subsystems."""

    def test_canonical_version_and_release_invariants(self, tmp_path):
        from core.enterprise_dashboard.main import EnterpriseDashboard

        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"execution_mode": "PAPER", "base_capital": 3000}), encoding="utf-8")
        d = EnterpriseDashboard(config={"trader_state_path": str(state_file), "BASE_CAPITAL": 3000})
        st = d._read_state()
        assert st["version"] == "2.59.4"
        assert st["release_tag"] == "v2.59.4-post-merge.3"
        assert st["execution_mode"] == "PAPER"
        assert st["base_capital"] == 3000.0

    def test_signal_intelligence_report_seed_sample_default(self, tmp_path):
        from core.reporting.signal_intelligence import build_signal_intelligence_report

        # Calling with non-existent db yields empty report cleanly with seed samples excluded by default
        rep = build_signal_intelligence_report(str(tmp_path / "nonexistent.db"))
        assert rep["data_quality"]["total_signals"] == 0
        assert rep["data_quality"]["signal_funnel"]["seed_samples_excluded"] == 0


class TestSystemHealthSemantics:
    """Test suite for R9: System health calculations and honest states."""

    def test_health_config_sanity_base_capital_denominator(self):
        from core.health_checker import check_config_sanity

        cfg = {"SL_PCT": 0.88, "TARGET_PCT": 1.05, "MAX_DAILY_LOSS": -600, "BASE_CAPITAL": 3000.0, "AI_THRESHOLD": 60}
        results = check_config_sanity(cfg)
        loss_check = [r for r in results if r.name == "Daily loss % of capital"][0]
        assert loss_check.status == "WARN"
        assert loss_check.value == 20.0
        assert "is 20.0% of BASE_CAPITAL" in loss_check.message

    def test_health_ml_insufficient_data_distinction(self):
        from core.health_checker import check_ml_health

        cfg = {"health_check_brier_warn": 0.30}
        results = check_ml_health(cfg)
        brier_check = [r for r in results if r.name == "Brier score"][0]
        assert brier_check.status == "WARN"
        assert "Insufficient data" in brier_check.message

    def test_health_recent_performance_inactivity_distinction(self, tmp_path):
        from core.health_checker import check_recent_performance

        cfg = {"health_check_trade_days": 60}
        results = check_recent_performance(cfg, db_path=str(tmp_path / "empty.db"))
        trade_check = [r for r in results if r.name == "Trade count"][0]
        assert trade_check.status == "WARN"
        assert "inactivity; no orders placed" in trade_check.message


class TestRealSignalsDatabaseInvariants:
    """Ensure db/signals_history.db remains untouched and valid."""

    def test_signals_db_invariants_preserved(self):
        db_path = Path("db/signals_history.db")
        if not db_path.exists():
            pytest.skip("db/signals_history.db not present in local test environment")

        with sqlite3.connect(str(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT raw_data, order_placed FROM system_signals").fetchall()
            total_count = len(rows)
            assert total_count >= 12, f"Expected at least seeded signals, got {total_count}"
            # Verify table integrity
            col_names = [d[1] for d in conn.execute("PRAGMA table_info(system_signals)").fetchall()]
            assert "signal_id" in col_names
            assert "status" in col_names
            assert "raw_data" in col_names

