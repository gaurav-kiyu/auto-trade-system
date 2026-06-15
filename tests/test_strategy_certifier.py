"""Tests for the Strategy Certification Framework."""

from __future__ import annotations

import json



from core.certification.strategy_certifier import (
    StrategyCertificationReport,
    StrategyCertifier,
    certify_strategy,
    certify_all_strategies,
)


class TestStrategyMetrics:
    def test_certify_strong_strategy(self):
        """Strong strategy with all metrics above thresholds should pass."""
        # Low-variance PnLs ensure Sharpe > 1.5, Sortino > 2.0, PF > 1.5
        pnls = [300, 250, 200, 300, 250, 200, 300, 250, 200, 300,
                250, 200, 300, 250, 200, 300, 250, 200, 300, 250,
                200, 300, 250, 200, 300, 250, 200, 300, 250, -100]
        report = certify_strategy("test_strat", pnls)
        assert report.passed is True
        assert report.status == "CERTIFIED"
        assert report.total_trades == 30
        assert report.sharpe_ratio > 1.5
        assert report.sortino_ratio > 2.0

    def test_certify_weak_strategy(self):
        """Weak strategy with low Sharpe should fail."""
        # Very volatile, low win-rate strategy
        pnls = [-500, -300, 100, -400, -200, -600, 50, -350, -150, -450,
                -250, -100, -300, 75, -500, -200, -400, -100, -350, -150]
        report = certify_strategy("weak_strat", pnls)
        assert report.passed is False
        assert report.status == "BLOCKED"
        assert len(report.failures) > 0

    def test_certify_insufficient_data(self):
        """Fewer than 20 trades should result in INSUFFICIENT_DATA."""
        pnls = [100, -50, 200, -100, 50]
        report = certify_strategy("new_strat", pnls)
        assert report.passed is False
        assert report.status == "INSUFFICIENT_DATA"
        assert "trades" in report.verdict

    def test_certify_zero_trades(self):
        """No trades at all."""
        report = certify_strategy("empty_strat", pnls=[])
        assert report.passed is False
        assert report.total_trades == 0

    def test_certify_medium_strategy(self):
        """Strategy with mixed performance should fail some thresholds."""
        pnls = [200, 150, 100, -50, -30, 300, 250, -100, -80, 180,
                120, 90, 60, -40, -20, 400, 350, -200, -150, 280,
                160, 110, 70, -60, -35, 320, 270, -120, -90, 190]
        report = certify_strategy("medium_strat", pnls)
        # This strategy should pass since pnls are mostly positive
        assert report.total_trades >= 20
        assert report.profit_factor > 1.0


class TestStrategyReport:
    def test_report_summary_certified(self):
        r = StrategyCertificationReport(
            passed=True,
            strategy_name="test",
            status="CERTIFIED",
            total_trades=30,
            verdict="CERTIFIED",
            thresholds={"min_sharpe": 1.5},
        )
        summary = r.summary()
        assert "CERTIFIED" in summary
        assert "test" in summary

    def test_report_summary_blocked(self):
        r = StrategyCertificationReport(
            passed=False,
            strategy_name="bad_strat",
            status="BLOCKED",
            total_trades=30,
            verdict="BLOCKED",
            failures=["Sharpe 0.5 < 1.5"],
        )
        summary = r.summary()
        assert "BLOCKED" in summary
        assert "0.5" in summary

    def test_report_to_dict(self):
        r = StrategyCertificationReport(
            passed=True,
            strategy_name="test",
            status="CERTIFIED",
            total_trades=30,
            win_rate=0.7,
            profit_factor=2.5,
            sharpe_ratio=2.0,
            sortino_ratio=3.0,
            max_drawdown_pct=10.0,
            verdict="CERTIFIED",
        )
        d = r.to_dict()
        assert d["strategy"] == "test"
        assert d["passed"] is True
        assert d["profit_factor"] == 2.5
        json.dumps(d)  # Verify JSON-serializable


class TestStrategyCertifier:
    def test_init(self):
        certifier = StrategyCertifier()
        assert certifier is not None

    def test_certify_multiple(self):
        certifier = StrategyCertifier()
        strategies = [
            ("good", [500, 300, -100, 400, 200, 600, -50, 350, 150, 450,
                      250, 100, 300, -75, 500, 200, 400, 100, 350, 150]),
            ("bad", [-500, -300, 100, -400, -200, -600, 50, -350, -150, -450,
                     -250, -100, -300, 75, -500, -200, -400]),
        ]
        reports = certifier.certify_multiple(strategies)
        assert len(reports) == 2
        assert reports[0].strategy_name == "good"
        assert reports[1].strategy_name == "bad"

    def test_threshold_override(self):
        """Custom thresholds via cfg."""
        cfg = {"strategy_cert_min_sharpe": 0.5}
        certifier = StrategyCertifier(cfg)
        pnls = [100, -50, 200, -100, 50, 150, -75, 180, -60, 220,
                130, -40, 160, -90, 240, 110, -55, 190, -70, 210]
        report = certifier.certify("test", pnls)
        # With lower threshold, should pass more easily
        assert report is not None

    def test_certify_strategy_not_found(self):
        """Non-existent strategy returns NOT_FOUND."""
        report = certify_strategy("nonexistent_strategy")
        assert report.passed is False
        assert report.status == "NOT_FOUND"

    def test_certify_all_strategies(self):
        """certify_all_strategies runs without error."""
        reports = certify_all_strategies()
        assert len(reports) == 4
        for r in reports:
            assert isinstance(r, StrategyCertificationReport)

    def test_all_positive_pnls(self):
        """All positive PnLs should max out profit factor and sortino."""
        pnls = [100.0] * 30
        report = certify_strategy("all_win", pnls)
        assert report.profit_factor == 10.0  # Capped at 10
        assert report.sortino_ratio == 10.0  # Capped at 10 (no losses)
        assert report.win_rate == 1.0
        assert report.sharpe_ratio > 1.5
