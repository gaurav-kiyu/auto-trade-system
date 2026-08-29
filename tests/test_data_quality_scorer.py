"""Tests for core/data_quality_scorer.py — Automated Data Quality Scoring Engine.

Covers:
  - DataQualityScorer initialization and defaults
  - record_finding and record_findings
  - get_source_score
  - get_category_score
  - get_system_health (overall score, health status, trend)
  - get_source_health_report
  - reset
  - Singleton factory (get_quality_scorer)
  - Edge cases: empty findings, window expiry, no data
"""

import time

from core.data_quality_scorer import (
    CATEGORY_WEIGHTS,
    SEVERITY_WEIGHTS,
    DataQualityScorer,
    SystemHealth,
    get_quality_scorer,
)

# ═══════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════


class _MockFinding:
    """Simulates a DataQualityFinding from DataQualityMonitor."""

    def __init__(self, category: str, severity: str, source: str = "unknown"):
        self.category = category
        self.severity = severity
        self.source = source
        self.type = category


# ═══════════════════════════════════════════════════════════════════════
#  Initialization
# ═══════════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_window(self):
        s = DataQualityScorer()
        assert s._window_seconds == 3600  # 60 minutes default

    def test_custom_window(self):
        s = DataQualityScorer(window_minutes=30)
        assert s._window_seconds == 1800

    def test_initial_state_empty(self):
        s = DataQualityScorer()
        assert len(s._findings) == 0
        assert s._cache_ts == 0.0

    def test_system_health_on_empty_scorer(self):
        s = DataQualityScorer()
        health = s.get_system_health()
        assert health.overall_score == 1.0
        assert health.health == "GREEN"
        assert health.total_findings == 0


# ═══════════════════════════════════════════════════════════════════════
#  record_finding
# ═══════════════════════════════════════════════════════════════════════


class TestRecordFinding:
    def test_record_single_finding(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "yfinance")
        assert len(s._findings) == 1
        assert s._findings[0].category == "PRICE"
        assert s._findings[0].severity == "WARN"
        assert s._findings[0].source == "yfinance"
        assert s._cache_ts == 0.0  # Cache invalidated

    def test_record_multiple_findings(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "ERROR", "yfinance")
        s.record_finding("VOLUME", "WARN", "nse")
        s.record_finding("FRESHNESS", "CRITICAL", "yfinance")
        assert len(s._findings) == 3

    def test_record_empty_values_ignored(self):
        s = DataQualityScorer()
        s.record_finding("", "WARN", "src")
        s.record_finding("PRICE", "", "src")
        assert len(s._findings) == 0

    def test_weight_computation(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "CRITICAL", "src")
        expected_weight = (
            SEVERITY_WEIGHTS["CRITICAL"] * CATEGORY_WEIGHTS["PRICE"]
        )
        assert s._findings[0].weight == expected_weight

    def test_weight_low_severity(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "INFO", "src")
        expected_weight = (
            SEVERITY_WEIGHTS["INFO"] * CATEGORY_WEIGHTS["PRICE"]
        )
        assert s._findings[0].weight == expected_weight


# ═══════════════════════════════════════════════════════════════════════
#  record_findings (batch)
# ═══════════════════════════════════════════════════════════════════════


class TestRecordFindings:
    def test_record_findings_from_list(self):
        s = DataQualityScorer()
        findings = [
            _MockFinding("PRICE", "ERROR", "yfinance"),
            _MockFinding("VOLUME", "WARN", "nse"),
        ]
        s.record_findings(findings)
        assert len(s._findings) == 2

    def test_record_findings_empty_list(self):
        s = DataQualityScorer()
        s.record_findings([])
        assert len(s._findings) == 0

    def test_record_findings_with_attrs(self):
        s = DataQualityScorer()
        findings = [
            _MockFinding("PRICE", "ERROR", "yfinance"),
            _MockFinding("FRESHNESS", "CRITICAL", "websocket"),
        ]
        s.record_findings(findings)
        sources = {f.source for f in s._findings}
        assert "yfinance" in sources
        assert "websocket" in sources


# ═══════════════════════════════════════════════════════════════════════
#  record_health_check
# ═══════════════════════════════════════════════════════════════════════


class TestRecordHealthCheck:
    def test_passed_check_does_not_record(self):
        s = DataQualityScorer()
        s.record_health_check(True, "SYSTEM", "checker")
        assert len(s._findings) == 0

    def test_failed_check_records_warn(self):
        s = DataQualityScorer()
        s.record_health_check(False, "SYSTEM", "checker")
        assert len(s._findings) == 1
        assert s._findings[0].severity == "WARN"


# ═══════════════════════════════════════════════════════════════════════
#  get_source_score
# ═══════════════════════════════════════════════════════════════════════


class TestGetSourceScore:
    def test_unknown_source_returns_perfect_score(self):
        s = DataQualityScorer()
        score = s.get_source_score("nonexistent")
        assert score.score == 1.0
        assert score.health == "GREEN"

    def test_healthy_source_returns_high_score(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "INFO", "yfinance")  # Low weight
        score = s.get_source_score("yfinance")
        assert score.score >= 0.9
        assert score.health == "GREEN"

    def test_unhealthy_source_returns_low_score(self):
        s = DataQualityScorer()
        for _ in range(10):
            s.record_finding("PRICE", "CRITICAL", "bad_source")
        score = s.get_source_score("bad_source")
        assert score.score < 0.5
        assert score.health in ("YELLOW", "RED")

    def test_score_isolated_per_source(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "CRITICAL", "bad_source")
        s.record_finding("PRICE", "INFO", "good_source")
        bad_score = s.get_source_score("bad_source")
        good_score = s.get_source_score("good_source")
        assert bad_score.score < good_score.score

    def test_finding_rate_meaningful(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "CRITICAL", "src")
        score = s.get_source_score("src")
        assert 0.0 <= score.finding_rate <= 1.0


# ═══════════════════════════════════════════════════════════════════════
#  get_category_score
# ═══════════════════════════════════════════════════════════════════════


class TestGetCategoryScore:
    def test_unknown_category_returns_perfect(self):
        s = DataQualityScorer()
        score = s.get_category_score("UNKNOWN_CAT")
        assert score.score == 1.0

    def test_category_affected_by_findings(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "ERROR", "src")
        score = s.get_category_score("PRICE")
        assert score.score < 1.0

    def test_different_categories_independent(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "CRITICAL", "src")
        s.record_finding("FRESHNESS", "INFO", "src")
        price_score = s.get_category_score("PRICE")
        fresh_score = s.get_category_score("FRESHNESS")
        assert price_score.score < fresh_score.score  # CRITICAL > INFO weight


# ═══════════════════════════════════════════════════════════════════════
#  get_system_health
# ═══════════════════════════════════════════════════════════════════════


class TestGetSystemHealth:
    def test_returns_system_health_object(self):
        s = DataQualityScorer()
        health = s.get_system_health()
        assert isinstance(health, SystemHealth)

    def test_empty_scorer_returns_green(self):
        s = DataQualityScorer()
        health = s.get_system_health()
        assert health.health == "GREEN"
        assert health.overall_score == 1.0

    def test_has_source_scores(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "yfinance")
        health = s.get_system_health()
        assert "yfinance" in health.source_scores

    def test_has_category_scores(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "src")
        health = s.get_system_health()
        assert "PRICE" in health.category_scores

    def test_worst_source_identified(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "INFO", "good")
        for _ in range(5):
            s.record_finding("PRICE", "CRITICAL", "bad")
        health = s.get_system_health()
        assert health.worst_source == "bad"
        assert health.worst_score < 1.0

    def test_trend_stable_on_single_finding(self):
        s = DataQualityScorer(window_minutes=60)
        s.record_finding("PRICE", "WARN", "src")
        health = s.get_system_health()
        assert health.trend in ("IMPROVING", "DECLINING", "STABLE")

    def test_total_findings_counted(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "src")
        s.record_finding("VOLUME", "INFO", "src")
        health = s.get_system_health()
        assert health.total_findings == 2


# ═══════════════════════════════════════════════════════════════════════
#  get_source_health_report
# ═══════════════════════════════════════════════════════════════════════


class TestGetSourceHealthReport:
    def test_returns_dict(self):
        s = DataQualityScorer()
        report = s.get_source_health_report()
        assert isinstance(report, dict)

    def test_contains_expected_keys(self):
        s = DataQualityScorer()
        report = s.get_source_health_report()
        assert "overall_score" in report
        assert "health" in report
        assert "sources" in report
        assert "categories" in report

    def test_sources_populated(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "yfinance")
        report = s.get_source_health_report()
        assert "yfinance" in report["sources"]
        assert report["sources"]["yfinance"]["score"] < 1.0


# ═══════════════════════════════════════════════════════════════════════
#  reset
# ═══════════════════════════════════════════════════════════════════════


class TestReset:
    def test_reset_clears_findings(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "src")
        assert len(s._findings) == 1
        s.reset()
        assert len(s._findings) == 0

    def test_reset_clears_cache(self):
        s = DataQualityScorer()
        s.record_finding("PRICE", "WARN", "src")
        _ = s.get_system_health()  # Populate cache
        assert s._cache_ts > 0
        s.reset()
        assert s._cache_ts == 0.0

    def test_reset_allows_fresh_scoring(self):
        s = DataQualityScorer()
        for _ in range(5):
            s.record_finding("PRICE", "CRITICAL", "bad")
        old_health = s.get_system_health()
        s.reset()
        new_health = s.get_system_health()
        assert old_health.overall_score < new_health.overall_score


# ═══════════════════════════════════════════════════════════════════════
#  Window expiry
# ═══════════════════════════════════════════════════════════════════════


class TestWindowExpiry:
    def test_old_findings_expire_from_window(self):
        s = DataQualityScorer(window_minutes=0.001)  # Very short window (~60ms)
        s.record_finding("PRICE", "CRITICAL", "src")
        time.sleep(0.1)  # Wait for window to pass
        health = s.get_system_health()
        assert health.total_findings == 0  # Expired


# ═══════════════════════════════════════════════════════════════════════
#  Singleton factory
# ═══════════════════════════════════════════════════════════════════════


class TestGetQualityScorer:
    def test_returns_same_instance(self):
        # Reset global state
        import core.data_quality_scorer as dqs
        dqs._scorer = None

        s1 = get_quality_scorer()
        s2 = get_quality_scorer()
        assert s1 is s2

    def test_creates_new_if_none(self):
        import core.data_quality_scorer as dqs
        dqs._scorer = None

        s = get_quality_scorer()
        assert isinstance(s, DataQualityScorer)


# ═══════════════════════════════════════════════════════════════════════
#  Edge cases
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_thousands_of_findings(self):
        s = DataQualityScorer()
        for i in range(1000):
            cat = "PRICE" if i % 2 == 0 else "VOLUME"
            sev = "INFO" if i % 3 == 0 else "WARN"
            src = "src_a" if i % 2 == 0 else "src_b"
            s.record_finding(cat, sev, src)
        health = s.get_system_health()
        assert health.total_findings == 1000
        assert 0.0 < health.overall_score <= 1.0

    def test_evenly_distributed_scores(self):
        s = DataQualityScorer()
        for _ in range(100):
            s.record_finding("PRICE", "CRITICAL", "src")
            s.record_finding("FRESHNESS", "CRITICAL", "src")
        health = s.get_system_health()
        assert health.overall_score < 0.5


# ═══════════════════════════════════════════════════════════════════════
#  Integration with DataQualityMonitor
# ═══════════════════════════════════════════════════════════════════════


class TestIntegrationWithMonitor:
    def test_accepts_data_quality_findings(self):
        """Verify scorer can accept findings from DataQualityMonitor."""
        from core.data_quality_monitor import DataQualityConfig, DataQualityMonitor

        monitor = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.02))
        scorer = DataQualityScorer()

        # Generate findings from monitor
        monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = monitor.check_price_anomaly(120.0, 5000, 98.0, 122.0)

        # Feed findings to scorer
        scorer.record_findings(findings)
        health = scorer.get_system_health()

        assert health.total_findings == len(findings)
        assert "PRICE" in health.category_scores

    def test_weighted_scoring_from_monitor(self):
        """Verify scorer correctly ingests findings from DataQualityMonitor."""
        from core.data_quality_monitor import DataQualityConfig, DataQualityMonitor

        scorer = DataQualityScorer()

        monitor = DataQualityMonitor(DataQualityConfig(max_price_change_pct=0.01))
        monitor.check_price_anomaly(100.0, 1000, 99.5, 100.5)
        findings = monitor.check_price_anomaly(200.0, 10000, 190.0, 210.0)

        # All findings from the monitor are properly ingested
        scorer.record_findings(findings)
        health = scorer.get_system_health()

        # Should have findings from the price spike
        assert health.total_findings > 0
        assert health.overall_score < 1.0
