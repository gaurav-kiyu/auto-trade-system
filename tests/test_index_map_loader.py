from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.defaults_loader import load_defaults_file
from core.index_map_loader import load_index_map, normalize_index_map_entry

ROOT = Path(__file__).resolve().parent.parent


def test_load_index_map_from_repo_defaults():
    m = load_index_map(ROOT)
    assert "NIFTY" in m
    assert m["NIFTY"]["yf"]
    assert m["NIFTY"]["sector"] == "INDEX"


def test_normalize_rejects_incomplete():
    assert normalize_index_map_entry("X", {"yf": "^NSEI"}) is None


def test_normalize_rejects_non_dict():
    assert normalize_index_map_entry("X", None) is None
    assert normalize_index_map_entry("X", "not_a_dict") is None
    assert normalize_index_map_entry("X", ["list"]) is None


def test_load_index_map_returns_empty_on_oserror():
    with patch("core.index_map_loader.load_defaults_file") as mock_load:
        mock_load.side_effect = OSError("mock file error")
        assert load_index_map(ROOT) == {}


def test_load_index_map_returns_empty_on_valueerror():
    with patch("core.index_map_loader.load_defaults_file") as mock_load:
        mock_load.side_effect = ValueError("mock json error")
        assert load_index_map(ROOT) == {}


def test_load_index_map_returns_empty_when_index_map_not_dict():
    with patch("core.index_map_loader.load_defaults_file") as mock_load:
        mock_load.return_value = {"INDEX_MAP": "not_a_dict"}
        assert load_index_map(ROOT) == {}


def test_load_index_map_returns_empty_when_index_map_missing():
    with patch("core.index_map_loader.load_defaults_file") as mock_load:
        mock_load.return_value = {"OTHER_KEY": [1, 2, 3]}
        assert load_index_map(ROOT) == {}
