"""Tests for the Prometheus monitoring module."""

from __future__ import annotations

from realestate.prometheus_monitoring import (
    BusinessMetrics,
    PrometheusMetrics,
    get_health_status,
)


class TestPrometheusMetrics:
    def setup_method(self):
        self.metrics = PrometheusMetrics()

    def test_counter_inc(self):
        self.metrics.inc_counter("test_requests", 1.0, {"method": "GET", "endpoint": "/test"})
        assert self.metrics.get_counter("test_requests", {"method": "GET", "endpoint": "/test"}) == 1.0

    def test_counter_default_zero(self):
        assert self.metrics.get_counter("nonexistent") == 0.0

    def test_gauge_set(self):
        self.metrics.set_gauge("active_users", 42.0)
        assert self.metrics.get_gauge("active_users") == 42.0

    def test_gauge_inc_dec(self):
        self.metrics.set_gauge("connections", 10.0)
        self.metrics.inc_gauge("connections", 5.0)
        assert self.metrics.get_gauge("connections") == 15.0
        self.metrics.dec_gauge("connections", 3.0)
        assert self.metrics.get_gauge("connections") == 12.0

    def test_histogram(self):
        for v in [0.1, 0.2, 0.05, 0.3, 0.15]:
            self.metrics.observe_histogram("request_latency", v)
        stats = self.metrics.get_histogram("request_latency")
        assert stats["count"] == 5
        assert stats["sum"] > 0.0

    def test_export_text_contains_counters(self):
        self.metrics.inc_counter("test_counter")
        text = self.metrics.export_text()
        assert "test_counter" in text
        assert "counter" in text

    def test_export_text_contains_gauges(self):
        self.metrics.set_gauge("test_gauge", 99.0)
        text = self.metrics.export_text()
        assert "test_gauge" in text
        assert "gauge" in text

    def test_export_text_contains_histograms(self):
        self.metrics.observe_histogram("test_histo", 0.5)
        text = self.metrics.export_text()
        assert "test_histo" in text
        assert "histogram" in text
        assert "_bucket" in text


class TestBusinessMetrics:
    def setup_method(self):
        self.bm = BusinessMetrics()
        self.metrics = PrometheusMetrics()

    def test_record_property_view(self):
        self.bm.record_property_view("RE-001", "Mumbai")
        # Check via the internal metrics
        assert self.bm._metrics.get_counter("re_property_views_total", {"city": "Mumbai"}) >= 1.0

    def test_record_enquiry(self):
        self.bm.record_enquiry("Pune")
        assert self.bm._metrics.get_counter("re_enquiries_total", {"city": "Pune"}) >= 1.0

    def test_record_lead_conversion(self):
        self.bm.record_lead_conversion("website")
        assert self.bm._metrics.get_counter("re_lead_conversions_total", {"source": "website"}) >= 1.0

    def test_active_users_gauge(self):
        self.bm.set_active_users(150)
        assert self.bm._metrics.get_gauge("re_active_users") == 150.0

    def test_user_registration(self):
        self.bm.record_user_registration()
        assert self.bm._metrics.get_counter("re_user_registrations_total") >= 1.0

    def test_user_login(self):
        self.bm.record_user_login()
        assert self.bm._metrics.get_counter("re_user_logins_total") >= 1.0

    def test_payment_metrics(self):
        self.bm.record_payment(50000.0, "success")
        assert self.bm._metrics.get_counter("re_payments_total", {"status": "success"}) >= 1.0

    def test_revenue_metrics(self):
        self.bm.record_revenue(100000.0)
        assert self.bm._metrics.get_counter("re_revenue_total") >= 100000.0

    def test_notification_metrics(self):
        self.bm.record_notification_sent("email")
        assert self.bm._metrics.get_counter("re_notifications_sent_total", {"channel": "email"}) >= 1.0

    def test_fraud_metrics(self):
        self.bm.record_fraud_check("blocked")
        assert self.bm._metrics.get_counter("re_fraud_checks_total", {"result": "blocked"}) >= 1.0

    def test_get_stats(self):
        self.bm.record_property_view("RE-001")
        self.bm.record_enquiry("Delhi")
        stats = self.bm.get_stats()
        assert "property_views" in stats
        assert "enquiries" in stats
        assert "active_users" in stats
        assert "latency" in stats


class TestHealthCheck:
    def test_health_status(self):
        health = get_health_status()
        assert health["service"] == "realestate-platform"
        assert "status" in health
        assert "checks" in health
        assert "system" in health["checks"]
