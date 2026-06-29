"""Tests for the MTTR tracker module."""

from __future__ import annotations

import time

import pytest
from core.mttr_tracker import MTTRTracker


class TestMTTRTracker:
    """Tests for the MTTR tracker."""

    def test_record_incident(self):
        """Recording an incident should return an ID."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("broker_outage", severity="CRITICAL")
        assert iid.startswith("inc_")
        assert tracker.open_count == 1

    def test_resolve_incident(self):
        """Resolving an incident should update its status."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("market_data", severity="ERROR")
        time.sleep(0.01)
        ok = tracker.resolve_incident(iid)
        assert ok is True
        assert tracker.open_count == 0
        assert tracker.resolved_count == 1

    def test_resolve_nonexistent(self):
        """Resolving a nonexistent incident should return False."""
        tracker = MTTRTracker()
        ok = tracker.resolve_incident("nonexistent")
        assert ok is False

    def test_is_open(self):
        """is_open should return correct status."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("test")
        assert tracker.is_open(iid) is True
        tracker.resolve_incident(iid)
        assert tracker.is_open(iid) is False

    def test_mttr_computation(self):
        """MTTR should be computed from resolution times."""
        tracker = MTTRTracker()
        iid1 = tracker.record_incident("cat1", severity="CRITICAL")
        time.sleep(0.02)
        tracker.resolve_incident(iid1)

        iid2 = tracker.record_incident("cat1", severity="WARNING")
        time.sleep(0.01)
        tracker.resolve_incident(iid2)

        report = tracker.get_report()
        assert report.resolved_incidents == 2
        assert report.overall_mttr > 0
        assert "cat1" in report.by_category
        assert report.by_category["cat1"] > 0

    def test_mttr_by_severity(self):
        """MTTR should be broken down by severity."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("test", severity="CRITICAL")
        time.sleep(0.01)
        tracker.resolve_incident(iid)
        report = tracker.get_report()
        assert "CRITICAL" in report.by_severity
        assert report.by_severity["CRITICAL"] > 0

    def test_empty_report(self):
        """A new tracker should produce a zeroed report."""
        tracker = MTTRTracker()
        report = tracker.get_report()
        assert report.total_incidents == 0
        assert report.overall_mttr == 0.0

    def test_clear(self):
        """Clear should reset all state."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("test")
        tracker.resolve_incident(iid)
        assert tracker.resolved_count == 1
        tracker.clear()
        assert tracker.open_count == 0
        assert tracker.resolved_count == 0

    def test_report_to_dict(self):
        """Report should be serializable to dict."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("test")
        time.sleep(0.01)
        tracker.resolve_incident(iid)
        report = tracker.get_report()
        d = report.to_dict()
        assert "overall_mttr_seconds" in d
        assert "mtbf_hours" in d
        assert d["total_incidents"] == 1

    def test_report_summary(self):
        """Summary should produce a formatted string."""
        tracker = MTTRTracker()
        iid = tracker.record_incident("test")
        time.sleep(0.01)
        tracker.resolve_incident(iid)
        report = tracker.get_report()
        summary = report.summary()
        assert "MTTR / MTBF" in summary
        assert isinstance(summary, str)

    def test_multiple_categories(self):
        """Multiple categories should produce per-category breakdown."""
        tracker = MTTRTracker()
        for cat in ["broker", "market", "execution"]:
            iid = tracker.record_incident(cat)
            time.sleep(0.005)
            tracker.resolve_incident(iid)
        report = tracker.get_report()
        assert len(report.by_category) == 3
        for cat in ["broker", "market", "execution"]:
            assert cat in report.by_category

    def test_merge(self):
        """Merging two trackers should combine incidents."""
        t1 = MTTRTracker()
        t2 = MTTRTracker()
        iid = t1.record_incident("cat1")
        time.sleep(0.01)
        t1.resolve_incident(iid)
        iid2 = t2.record_incident("cat2")
        time.sleep(0.01)
        t2.resolve_incident(iid2)
        t1.merge(t2)
        assert t1.resolved_count == 2
        assert t1.open_count == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
