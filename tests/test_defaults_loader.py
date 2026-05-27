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


def test_load_defaults_file_non_dict_raises(tmp_path: Path):
    """Top-level non-dict JSON raises ValueError."""
    p = tmp_path / "list.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_defaults_file(tmp_path, "list.json")


def test_load_defaults_file_not_a_file_raises(tmp_path: Path):
    """Subdir (not a file) raises FileNotFoundError."""
    (tmp_path / "mydir").mkdir()
    with pytest.raises(FileNotFoundError):
        load_defaults_file(tmp_path, "mydir")


def test_repo_bundled_stock_defaults_exist():
    root = Path(__file__).resolve().parent.parent
    d = load_defaults_file(root, "stock_config.defaults.json")
    assert "BOT_TOKEN" in d
    assert "LEARNING_SCORE_ADJ_CLAMP" in d
