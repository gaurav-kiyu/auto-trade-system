from __future__ import annotations

from pathlib import Path

from core.index_map_loader import load_index_map, normalize_index_map_entry


ROOT = Path(__file__).resolve().parent.parent


def test_load_index_map_from_repo_defaults():
    m = load_index_map(ROOT)
    assert "NIFTY" in m
    assert m["NIFTY"]["yf"]
    assert m["NIFTY"]["sector"] == "INDEX"


def test_normalize_rejects_incomplete():
    assert normalize_index_map_entry("X", {"yf": "^NSEI"}) is None
