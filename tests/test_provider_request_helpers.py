"""Unit tests for the provider request tracking helper functions.

Tests _record_provider_request() and _get_provider_error_info()
from core.enterprise_dashboard - these are module-level utility
functions used by the /api/system/data-providers/health endpoint.

Note: _record_provider_request modifies a module-level global
(_PROVIDER_REQUESTS). Tests that exercise it verify basic behavior
without depending on exact list lengths across calls.
"""

from __future__ import annotations

import time



# ── Tests for _record_provider_request ────────────────────────────────────────


class TestRecordProviderRequest:
    """Tests for the _record_provider_request() helper."""

    @property
    def _mod(self):
        """Re-import module each time to get fresh global references."""
        import importlib
        import core.enterprise_dashboard as m
        importlib.reload(m)
        return m

    def test_record_adds_timestamp(self):
        """Calling _record_provider_request adds a recent timestamp."""
        mod = self._mod
        with mod._LOCK:
            before = len(mod._PROVIDER_REQUESTS)

        mod._record_provider_request()

        with mod._LOCK:
            assert len(mod._PROVIDER_REQUESTS) == before + 1

    def test_record_timestamp_is_recent(self):
        """The recorded timestamp is within a reasonable window."""
        mod = self._mod
        before_ts = time.time()
        mod._record_provider_request()
        after_ts = time.time()

        with mod._LOCK:
            last = mod._PROVIDER_REQUESTS[-1]
        assert before_ts <= last <= after_ts

    def test_record_prunes_old_entries(self):
        """Calling _record_provider_request prunes entries older than 300s."""
        mod = self._mod
        with mod._LOCK:
            old_ts = time.time() - 600
            mod._PROVIDER_REQUESTS.append(old_ts)
            count_before = len(mod._PROVIDER_REQUESTS)

        mod._record_provider_request()

        with mod._LOCK:
            assert old_ts not in mod._PROVIDER_REQUESTS
            assert len(mod._PROVIDER_REQUESTS) <= count_before + 1


# ── Tests for _get_provider_error_info ────────────────────────────────────────


class TestGetProviderErrorInfo:
    """Tests for the _get_provider_error_info() helper (pure function)."""

    def test_empty_details(self):
        """Empty details dict returns empty error_info."""
        from core.enterprise_dashboard import _get_provider_error_info

        result = _get_provider_error_info({})
        assert result == {}

    def test_single_adapter_no_errors(self):
        """Adapter with no error data returns defaults."""
        from core.enterprise_dashboard import _get_provider_error_info

        details = {
            "yfinance": {
                "adapter_type": "YFinanceAdapter",
                "connected": True,
            },
        }
        result = _get_provider_error_info(details)
        assert result["yfinance"]["error_rate"] == 0.0
        assert result["yfinance"]["last_error"] is None
        assert result["yfinance"]["last_error_ts"] is None
        assert result["yfinance"]["error_age"] is None

    def test_single_adapter_with_error(self):
        """Adapter with error data returns it correctly."""
        from core.enterprise_dashboard import _get_provider_error_info

        ts = time.time() - 60
        details = {
            "websocket": {
                "adapter_type": "NseIndexWebSocketAdapter",
                "connected": False,
                "error_rate": 0.15,
                "last_error": "Connection timeout",
                "last_error_ts": ts,
            },
        }
        result = _get_provider_error_info(details)
        assert result["websocket"]["error_rate"] == 0.15
        assert result["websocket"]["last_error"] == "Connection timeout"
        assert result["websocket"]["last_error_ts"] == ts
        assert result["websocket"]["error_age"] is not None
        assert 55 <= result["websocket"]["error_age"] <= 65

    def test_multiple_adapters(self):
        """Multiple adapters are all present in the result."""
        from core.enterprise_dashboard import _get_provider_error_info

        details = {
            "yfinance": {"adapter_type": "YFinanceAdapter", "connected": True},
            "websocket": {
                "adapter_type": "NseIndexWebSocketAdapter",
                "connected": False,
                "error_rate": 0.5,
                "last_error": "Disconnected",
            },
            "broker": {"adapter_type": "BrokerAdapter", "connected": True},
        }
        result = _get_provider_error_info(details)
        assert set(result.keys()) == {"yfinance", "websocket", "broker"}

    def test_non_dict_detail_skipped(self):
        """If a detail entry is not a dict, it's skipped gracefully."""
        from core.enterprise_dashboard import _get_provider_error_info

        details = {
            "yfinance": "not_a_dict",
            "websocket": {"adapter_type": "WS", "connected": True},
        }
        result = _get_provider_error_info(details)
        assert "yfinance" not in result
        assert "websocket" in result

    def test_partial_error_data(self):
        """Partial error data (only some fields) is handled."""
        from core.enterprise_dashboard import _get_provider_error_info

        details = {
            "yfinance": {
                "adapter_type": "YFinanceAdapter",
                "connected": False,
                "error_rate": 0.05,
            },
        }
        result = _get_provider_error_info(details)
        assert result["yfinance"]["error_rate"] == 0.05
        assert result["yfinance"]["last_error"] is None
        assert result["yfinance"]["last_error_ts"] is None
        assert result["yfinance"]["error_age"] is None

    def test_error_age_is_rounded(self):
        """error_age is a float rounded to 2 decimal places."""
        from core.enterprise_dashboard import _get_provider_error_info

        ts = time.time() - 123.456
        details = {
            "adapter": {
                "adapter_type": "A",
                "connected": False,
                "last_error_ts": ts,
            },
        }
        result = _get_provider_error_info(details)
        assert isinstance(result["adapter"]["error_age"], float)
        # Should be ~123.46, within reasonable tolerance
        assert 122 <= result["adapter"]["error_age"] <= 125
