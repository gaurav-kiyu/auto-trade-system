"""Comprehensive regression tests for OPB v2.59.4 Final Master Forensic Pass (UX-05 through UX-20)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


class TestUX05EmptyInfoToastElimination:
    """UX-05: Toast notification engine must never render an empty body or duplicate badge/title."""

    def test_theme_engine_has_default_title_and_message_for_all_severities(self) -> None:
        for rel in ("static/theme_engine.js", "core/static/theme_engine.js"):
            content = (ROOT / rel).read_text(encoding="utf-8")
            assert "defaultTitle:" in content, f"{rel} missing defaultTitle in CANONICAL_SEVERITY_UI"
            assert "defaultMessage:" in content, f"{rel} missing defaultMessage in CANONICAL_SEVERITY_UI"
            assert "function normalizeToastOptions(" in content
            assert "typeof Event !== 'undefined' && optionsOrMessage instanceof Event" in content
            assert "ui.defaultMessage" in content

    def test_admin_config_initial_load_does_not_fire_unsolicited_toast(self) -> None:
        html = (ROOT / "templates/enterprise/admin_config.html").read_text(encoding="utf-8")
        assert "async function loadConfig(showNotice = false)" in html
        assert "if (showNotice === true)" in html
        assert "showToast('Configuration reloaded from disk.'" in html


class TestUX06GlobalSaveAndActionFeedback:
    """UX-06: Interactive pages must use canonical toast/modal feedback instead of raw blocking alert()."""

    def test_no_raw_alert_calls_in_updated_enterprise_templates(self) -> None:
        target_templates = [
            "templates/enterprise/admin_portfolio_analyzer.html",
            "templates/enterprise/admin_config.html",
            "templates/enterprise/pricing_plans.html",
            "templates/enterprise/admin_signals.html",
            "templates/enterprise/intelligence.html",
            "templates/enterprise/presentation.html",
            "templates/enterprise/strategy_sandbox.html",
        ]
        raw_alert_re = re.compile(r"(?<![.\w])alert\s*\(")
        for rel in target_templates:
            text = (ROOT / rel).read_text(encoding="utf-8")
            matches = raw_alert_re.findall(text)
            assert not matches, f"Found raw alert() in {rel}: {matches}"


class TestUX08AndUX09PortfolioAnalyzerAndBrokers:
    """UX-08 & UX-09: Portfolio Analyzer truthfulness, distinct Buy/Current/Target prices, and 14 Indian brokers."""

    def test_all_14_indian_brokers_have_valid_https_urls_and_truthful_metadata(self) -> None:
        from core.admin_portfolio_analyzer import INDIAN_BROKERS, get_admin_portfolio_analyzer

        analyzer = get_admin_portfolio_analyzer()
        assert len(INDIAN_BROKERS) == 14
        expected_ids = {
            "zerodha", "angelone", "iifl", "upstox", "groww", "icicidirect",
            "hdfcsecurities", "kotak", "dhan", "fyers", "motilaloswal", "sharekhan",
            "paytmmoney", "mstock",
        }
        assert set(INDIAN_BROKERS.keys()) == expected_ids
        for bid, b in INDIAN_BROKERS.items():
            info = analyzer.get_broker_info(bid)
            assert info["auth_url"].startswith("https://"), f"Invalid auth_url for {bid}: {info['auth_url']}"
            assert "adapter_implemented" in info
            assert info["live_oauth_sync"] is False
            assert info["supports_iframe"] is False
            assert info["capability_state"] in (
                "ADAPTER_READY_NOT_LIVE_CREDENTIAL_VERIFIED",
                "PORTAL_PARTNER_SAMPLE_WORKFLOW",
            )
            assert info["capability_label"]
        # Verify dead domains are gone
        assert "ttweb.indiainfoline.com" not in INDIAN_BROKERS["iifl"]["auth_url"]
        assert "ntrade.kotaksecurities.com" not in INDIAN_BROKERS["kotak"]["auth_url"]

    def test_portfolio_guidance_populates_distinct_buy_current_and_target_prices(self) -> None:
        from core.admin_portfolio_analyzer import PortfolioPosition, get_admin_portfolio_analyzer

        analyzer = get_admin_portfolio_analyzer()
        positions = [
            PortfolioPosition("RELIANCE", "Equity", 100, 2500.0, 3000.0, 300000.0, 50000.0, 20.0, "Energy & Oil"),
            PortfolioPosition("HDFCBANK", "Equity", 200, 1700.0, 1300.0, 260000.0, -80000.0, -23.5, "Banking & Finance"),
        ]
        d = analyzer.run_16_strategy_deep_scan("Gaurav Admin Test", "zerodha", positions)
        assert len(d["stock_guidance"]) == 2
        for item in d["stock_guidance"]:
            assert item["buy_price"] > 0
            assert item["current_price"] > 0
            assert item["target_price"] > 0
            assert item["buy_price"] != item["current_price"]
            assert item["current_price"] != item["target_price"]

    def test_portfolio_analyzer_template_renders_buy_and_current_price_columns(self) -> None:
        html = (ROOT / "templates/enterprise/admin_portfolio_analyzer.html").read_text(encoding="utf-8")
        assert "item.buy_price" in html
        assert "item.current_price" in html
        assert "item.target_price" in html
        assert "Simulate Paper Hedge Order" in html


class TestUX10CommandCenterCoherence:
    """UX-10: Command Center header, mobile status strip, and tabs must stay coherent with market telemetry."""

    def test_dashboard_template_has_no_hardcoded_live_intraday_or_fake_profit_factor(self) -> None:
        html = (ROOT / "templates/enterprise/dashboard.html").read_text(encoding="utf-8")
        assert "LIVE INTRADAY" not in html
        assert "PAPER SIMULATED" in html
        assert "PAPER BASELINE" in html
        assert 'id="profitFactorDisplay"' in html
        assert 'id="mobileNseSessionItem"' in html
        assert 'id="healthNseFeedValue"' in html
        assert 'id="execGatewayValue"' in html


class TestUX11PresentationGeneratorTheming:
    """UX-11: Presentation Generator must use OPB theme variables instead of hardcoded dark Tailwind classes."""

    def test_presentation_template_uses_theme_aware_classes(self) -> None:
        html = (ROOT / "templates/enterprise/presentation.html").read_text(encoding="utf-8")
        assert ".pg-card" in html
        assert ".pg-subcard" in html
        assert ".pg-input" in html
        assert "var(--bg-card" in html
        assert "var(--text-primary" in html
        for forbidden in ("bg-gray-900", "bg-gray-800", "bg-gray-700"):
            assert forbidden not in html, f"Found hardcoded {forbidden} in presentation.html"


class TestUX12AndUX13AndUX15IntelligenceCoherence:
    """UX-12, UX-13, UX-15: Security Auditor risk/score coherence, BI quality history, and ML provenance."""

    def test_security_auditor_risk_respects_finding_severity_floor(self) -> None:
        from core.security_auditor import SecretFinding, SecurityAuditor, SecurityReport

        auditor = SecurityAuditor()
        rep_low = SecurityReport(score=8.0)
        assert auditor._compute_risk(8.0, rep_low) == "LOW"
        rep_crit = SecurityReport(
            score=8.5,
            secrets_found=[
                SecretFinding(
                    file_path="dummy.py",
                    line_number=1,
                    pattern_name="AWS Key",
                    severity="CRITICAL",
                    snippet="AKIA***",
                )
            ],
        )
        assert auditor._compute_risk(8.5, rep_crit) == "HIGH"

    def test_bi_report_to_dict_includes_quality_history_and_aligned_security_score(self) -> None:
        from core.bi_dashboard import BIDashboard

        bi = BIDashboard()
        report = bi.generate_bi_report()
        d = report.to_dict()
        assert "quality_history" in d
        assert isinstance(d["quality_history"], list)
        assert len(d["quality_history"]) >= 1
        assert d["current_health"]["security_score"] == pytest.approx(8.0, abs=2.0)

    def test_intelligence_template_renders_insecure_imports_and_ml_provenance(self) -> None:
        html = (ROOT / "templates/enterprise/intelligence.html").read_text(encoding="utf-8")
        assert "r.insecure_imports" in html
        assert "mlProvenanceBadge" in html
        assert "BENCHMARK CALIBRATION" in html


class TestUX14MetricsTrendAndDockerignore:
    """UX-14: Register consistency check, trend direction, and .dockerignore inclusion of docs/*.md."""

    def test_dockerignore_includes_governance_register_markdown_files(self) -> None:
        dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
        assert "!docs/" in dockerignore
        assert "!docs/*.md" in dockerignore
        assert "!CONSTITUTION.md" in dockerignore

    def test_live_registers_are_consistent_and_trends_pass(self) -> None:
        from core.success_metrics_trend import check_register_consistency, get_metrics_trend, reset_metrics_trend

        res = check_register_consistency()
        assert res["ok"] is True, f"Register consistency failed: {res}"
        reset_metrics_trend()
        trend = get_metrics_trend()
        v7 = trend.validate_metric("MET-07")
        v8 = trend.validate_metric("MET-08")
        assert v7["passed"] is True, f"MET-07 failed: {v7}"
        assert v8["passed"] is True, f"MET-08 failed: {v8}"


class TestUX16PasswordUpdateButtonContrast:
    """UX-16: Update Password button must use semantic primary accent styling with high contrast."""

    def test_profile_change_password_button_uses_accent_color_and_btn_primary_text(self) -> None:
        html = (ROOT / "templates/enterprise/profile.html").read_text(encoding="utf-8")
        assert 'id="changePasswordBtn"' in html
        assert "var(--btn-primary-text, #ffffff)" in html
        assert "var(--accent-color, #0284c7)" in html
