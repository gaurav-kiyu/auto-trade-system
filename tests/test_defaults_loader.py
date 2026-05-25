from __future__ import annotations

import json
from pathlib import Path

import pytest
from core.defaults_loader import load_defaults_file


def test_load_defaults_file_round_trip(tmp_path: Path):
    d = {"A": 1, "B": {"x": True}}
    p = tmp_path / "x.defaults.json"
    p.write_text(json.dumps(d), encoding="utf-8")
    assert load_defaults_file(tmp_path, "x.defaults.json") == d


def test_load_defaults_file_missing(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_defaults_file(tmp_path, "nope.json")


def test_repo_bundled_index_defaults_exist():
    root = Path(__file__).resolve().parent.parent
    d = load_defaults_file(root, "index_config.defaults.json")
    assert "BOT_TOKEN" in d
    assert "LEARNING_SCORE_ADJ_CLAMP" in d


def test_repo_bundled_stock_defaults_exist():
    root = Path(__file__).resolve().parent.parent
    d = load_defaults_file(root, "stock_config.defaults.json")
    assert "BOT_TOKEN" in d
    assert "LEARNING_SCORE_ADJ_CLAMP" in d
