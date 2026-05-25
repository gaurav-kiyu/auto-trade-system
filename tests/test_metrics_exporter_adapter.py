"""Tests for MetricsAdapter in core.metrics_exporter."""
from __future__ import annotations

from unittest.mock import patch

from core.metrics_exporter import MetricsAdapter


class TestMetricsAdapter:
    def test_increment_counter(self) -> None:
        adapter = MetricsAdapter()
        with patch("core.metrics_exporter.update_metrics") as mock_update:
            adapter.increment_counter("test_counter", 5)
            mock_update.assert_called_once_with({"test_counter_inc": 5.0})

    def test_set_gauge(self) -> None:
        adapter = MetricsAdapter()
        with patch("core.metrics_exporter.update_metrics") as mock_update:
            adapter.set_gauge("test_gauge", 42.5)
            mock_update.assert_called_once_with({"test_gauge": 42.5})

    def test_record_timer(self) -> None:
        adapter = MetricsAdapter()
        with patch("core.metrics_exporter.update_metrics") as mock_update:
            adapter.record_timer("exec_time", 0.15)
            mock_update.assert_called_once_with({"exec_time_timer": 0.15})

    def test_record_histogram(self) -> None:
        adapter = MetricsAdapter()
        with patch("core.metrics_exporter.update_metrics") as mock_update:
            adapter.record_histogram("latency", 0.05)
            mock_update.assert_called_once_with({"latency_hist": 0.05})

    def test_tags_accepted_but_ignored(self) -> None:
        adapter = MetricsAdapter()
        with patch("core.metrics_exporter.update_metrics") as mock_update:
            adapter.increment_counter("test", 1, {"env": "test"})
            adapter.set_gauge("g", 1.0, {"env": "test"})
            assert mock_update.call_count == 2

    def test_all_methods_noop_without_prometheus(self) -> None:
        adapter = MetricsAdapter()
        adapter.increment_counter("x")
        adapter.set_gauge("y", 1.0)
        adapter.record_timer("z", 0.1)
        adapter.record_histogram("w", 0.2)
