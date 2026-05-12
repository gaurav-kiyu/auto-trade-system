"""Tests for core/metrics_exporter.py (v2.45 Item 19)."""
import pytest
from core.metrics_exporter import (
    start_metrics_server, update_metrics, get_metrics_text,
    _init_prometheus,
)


def test_start_disabled_returns_false():
    result = start_metrics_server({"metrics_enabled": False})
    assert result is False


def test_start_default_disabled():
    result = start_metrics_server({})
    assert result is False


def test_update_metrics_no_crash_when_not_inited():
    # Should not raise even if prometheus not available
    update_metrics({"pnl_today": 1000.0, "active_positions": 2.0})


def test_update_metrics_unknown_key_no_crash():
    update_metrics({"nonexistent_key": 999.0})


def test_get_metrics_text_returns_string():
    out = get_metrics_text()
    assert isinstance(out, str)


def test_get_metrics_text_not_empty():
    out = get_metrics_text()
    assert len(out) > 0


def test_update_metrics_trades_inc_no_crash():
    update_metrics({"trades_total_inc": 1.0, "wins_total_inc": 1.0})


def test_start_with_port_override():
    # Should not raise; will fail to start without prometheus_client — returns False
    result = start_metrics_server({"metrics_enabled": True, "metrics_port": 9091})
    assert isinstance(result, bool)


def test_update_empty_dict_no_crash():
    update_metrics({})


def test_get_metrics_text_fallback_format():
    # Even without prometheus, should return some string
    out = get_metrics_text()
    assert isinstance(out, str)
