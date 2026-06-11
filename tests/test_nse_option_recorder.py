"""
Tests for ``core.nse_option_recorder`` — NSE Option Chain Recorder.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from core.nse_option_recorder import (
    _aggregate_oi_data,
    get_oi_summary,
    record_oi_snapshots_for_indices,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_option_chain() -> list[dict]:
    """A realistic sample of NSE option chain contracts."""
    return [
        {"strike": 22000, "optionType": "CALL", "lastPrice": 150.0, "openInterest": 500000, "volume": 10000},
        {"strike": 22100, "optionType": "CALL", "lastPrice": 100.0, "openInterest": 300000, "volume": 5000},
        {"strike": 22200, "optionType": "CALL", "lastPrice": 60.0, "openInterest": 200000, "volume": 2000},
        {"strike": 22000, "optionType": "PUT", "lastPrice": 120.0, "openInterest": 600000, "volume": 12000},
        {"strike": 22100, "optionType": "PUT", "lastPrice": 180.0, "openInterest": 400000, "volume": 8000},
        {"strike": 22200, "optionType": "PUT", "lastPrice": 250.0, "openInterest": 100000, "volume": 3000},
    ]


@pytest.fixture
def sample_one_sided_chain() -> list[dict]:
    """Option chain with only CALLs (edge case)."""
    return [
        {"strike": 22000, "optionType": "CALL", "lastPrice": 150.0, "openInterest": 500000, "volume": 10000},
        {"strike": 22100, "optionType": "CALL", "lastPrice": 100.0, "openInterest": 300000, "volume": 5000},
    ]


@pytest.fixture
def empty_chain() -> list[dict]:
    return []


@pytest.fixture
def minimal_config() -> dict:
    return {
        "oi_snapshot_enabled": True,
        "OI_SNAPSHOT_ENABLED": True,
        "oi_snapshot_db_path": ":memory:",
        "OI_SNAPSHOT_MIN_INTERVAL": 60,
        "OI_SNAPSHOT_ARCHIVE_DAYS": 90,
    }


# ── Tests for _aggregate_oi_data ─────────────────────────────────────────────


class TestAggregateOiData:
    def test_basic_aggregation(self, sample_option_chain: list[dict]) -> None:
        result = _aggregate_oi_data(sample_option_chain)
        assert result["call_oi"] == 1_000_000  # 500k + 300k + 200k
        assert result["put_oi"] == 1_100_000  # 600k + 400k + 100k
        assert result["call_volume"] == 17_000  # 10k + 5k + 2k
        assert result["put_volume"] == 23_000  # 12k + 8k + 3k
        assert result["total_oi"] == 2_100_000
        # PCR = put_oi / call_oi = 1_100_000 / 1_000_000 = 1.1
        assert result["pcr_ratio"] == pytest.approx(1.1, rel=1e-4)
        assert result["snapshot_source"] == "nse_recorder"

    def test_one_sided_chain(self, sample_one_sided_chain: list[dict]) -> None:
        result = _aggregate_oi_data(sample_one_sided_chain)
        assert result["call_oi"] == 800_000
        assert result["put_oi"] == 0
        assert result["total_oi"] == 800_000
        # No PUT data means PCR = 0 / call_oi = 0.0
        assert result["pcr_ratio"] == 0.0

    def test_empty_chain(self, empty_chain: list[dict]) -> None:
        result = _aggregate_oi_data(empty_chain)
        assert result["call_oi"] == 0
        assert result["put_oi"] == 0
        assert result["total_oi"] == 0
        assert result["pcr_ratio"] == 1.0  # fallback when call_oi == 0

    def test_zero_oi_contracts(self) -> None:
        chain = [
            {"strike": 22000, "optionType": "CALL", "openInterest": 0, "volume": 0},
            {"strike": 22100, "optionType": "PUT", "openInterest": 0, "volume": 0},
        ]
        result = _aggregate_oi_data(chain)
        assert result["call_oi"] == 0
        assert result["put_oi"] == 0
        assert result["pcr_ratio"] == 1.0

    def test_missing_fields(self) -> None:
        chain = [
            {"strike": 22000, "optionType": "CALL"},  # no OI or volume
            {"strike": 22100, "optionType": "PUT", "openInterest": None, "volume": None},
        ]
        result = _aggregate_oi_data(chain)
        assert result["call_oi"] == 0
        assert result["put_oi"] == 0
        assert result["pcr_ratio"] == 1.0

    def test_case_insensitive_option_type(self) -> None:
        chain = [
            {"strike": 22000, "optionType": "call", "openInterest": 100, "volume": 10},
            {"strike": 22100, "optionType": "Put", "openInterest": 200, "volume": 20},
        ]
        result = _aggregate_oi_data(chain)
        assert result["call_oi"] == 100
        assert result["put_oi"] == 200
        assert result["pcr_ratio"] == pytest.approx(2.0)


# ── Tests for record_oi_snapshots_for_indices ────────────────────────────────


class TestRecordOiSnapshotsForIndices:
    def setup_method(self) -> None:
        """Reset the NSE adapter cache for test isolation."""
        from core.nse_option_recorder import reset_nse_adapter_cache
        reset_nse_adapter_cache()

    def test_empty_index_list(self) -> None:
        result = record_oi_snapshots_for_indices([], {})
        assert result == {}

    def test_returns_false_when_disabled(self) -> None:
        result = record_oi_snapshots_for_indices(
            ["NIFTY"], {"oi_snapshot_enabled": False}
        )
        assert result == {"NIFTY": False}

    @patch("core.nse_option_recorder.record_snapshot")
    def test_successful_recording(self, mock_record: MagicMock) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = [
            {"strike": 22000, "optionType": "CALL", "openInterest": 100, "volume": 10},
            {"strike": 22000, "optionType": "PUT", "openInterest": 200, "volume": 20},
        ]
        mock_record.return_value = True

        result = record_oi_snapshots_for_indices(
            ["NIFTY"], {"oi_snapshot_enabled": True, "OI_SNAPSHOT_DB_PATH": ":memory:"},
            nse_adapter=mock_adapter,
        )
        assert result["NIFTY"] is True
        mock_adapter.get_option_chain.assert_called_once_with("NIFTY")
        mock_record.assert_called_once()

    @patch("core.nse_option_recorder.record_snapshot")
    def test_recording_with_multiple_indices(
        self, mock_record: MagicMock
    ) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = [
            {"strike": 22000, "optionType": "CALL", "openInterest": 100, "volume": 10},
            {"strike": 22000, "optionType": "PUT", "openInterest": 200, "volume": 20},
        ]
        mock_record.return_value = True

        result = record_oi_snapshots_for_indices(
            ["NIFTY", "BANKNIFTY"],
            {"oi_snapshot_enabled": True, "OI_SNAPSHOT_DB_PATH": ":memory:"},
            nse_adapter=mock_adapter,
        )
        assert len(result) == 2
        assert all(v is True for v in result.values())
        assert mock_adapter.get_option_chain.call_count == 2

    def test_graceful_failure_on_adapter_error(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.side_effect = ConnectionError("NSE API down")

        result = record_oi_snapshots_for_indices(
            ["NIFTY"],
            {"oi_snapshot_enabled": True, "OI_SNAPSHOT_DB_PATH": ":memory:"},
            nse_adapter=mock_adapter,
        )
        assert result["NIFTY"] is False

    def test_graceful_failure_when_no_nse_adapter(self, caplog: pytest.LogCaptureFixture) -> None:
        """Should handle missing NSE adapter gracefully."""
        with patch(
            "core.nse_option_recorder.record_snapshot", return_value=True
        ):
            with patch(
                "infrastructure.adapters.market_data.nse.adapter.NSEAdapter",
                side_effect=ImportError("nsepython not installed"),
            ):
                with caplog.at_level(logging.WARNING):
                    result = record_oi_snapshots_for_indices(
                        ["NIFTY"],
                        {"oi_snapshot_enabled": True},
                    )
                    assert result["NIFTY"] is False

    def test_empty_option_chain(self) -> None:
        """Should not record when no chain data returned."""
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = []

        with patch("core.nse_option_recorder.record_snapshot") as mock_record:
            result = record_oi_snapshots_for_indices(
                ["NIFTY"],
                {"oi_snapshot_enabled": True},
                nse_adapter=mock_adapter,
            )
            assert result["NIFTY"] is False
            mock_record.assert_not_called()


# ── Tests for get_oi_summary ──────────────────────────────────────────────────


class TestGetOiSummary:
    def setup_method(self) -> None:
        """Reset the NSE adapter cache before each test for isolation."""
        from core.nse_option_recorder import reset_nse_adapter_cache
        reset_nse_adapter_cache()

    def test_successful_summary(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = [
            {"strike": 22000, "optionType": "CALL", "openInterest": 500, "volume": 50},
            {"strike": 22000, "optionType": "PUT", "openInterest": 800, "volume": 80},
        ]

        with patch(
            "infrastructure.adapters.market_data.nse.adapter.NSEAdapter",
            return_value=mock_adapter,
        ):
            result = get_oi_summary(["NIFTY"], {})
        assert "NIFTY" in result
        assert result["NIFTY"]["pcr_ratio"] == pytest.approx(1.6)
        assert result["NIFTY"]["call_oi"] == 500
        assert result["NIFTY"]["put_oi"] == 800

    def test_summary_with_multiple_indices(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = [
            {"strike": 22000, "optionType": "CALL", "openInterest": 100, "volume": 10},
            {"strike": 22000, "optionType": "PUT", "openInterest": 150, "volume": 15},
        ]

        with patch(
            "infrastructure.adapters.market_data.nse.adapter.NSEAdapter",
            return_value=mock_adapter,
        ):
            result = get_oi_summary(["NIFTY", "BANKNIFTY", "FINNIFTY"], {})
        assert len(result) == 3
        for idx in ("NIFTY", "BANKNIFTY", "FINNIFTY"):
            assert idx in result

    def test_summary_error_handling(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.side_effect = RuntimeError("API failure")

        with patch(
            "infrastructure.adapters.market_data.nse.adapter.NSEAdapter",
            return_value=mock_adapter,
        ):
            result = get_oi_summary(["NIFTY"], {})
        assert "NIFTY" in result
        assert "error" in result["NIFTY"]

    def test_summary_empty_chain(self) -> None:
        mock_adapter = MagicMock()
        mock_adapter.get_option_chain.return_value = []

        with patch(
            "infrastructure.adapters.market_data.nse.adapter.NSEAdapter",
            return_value=mock_adapter,
        ):
            result = get_oi_summary(["NIFTY"], {})
        assert "NIFTY" in result
        assert result["NIFTY"].get("error") == "No data"
