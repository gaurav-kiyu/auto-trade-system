"""Tests for core/signal_importer.py (v2.46 Sprint 1F)."""
import pytest
from unittest.mock import MagicMock
from core.signal_importer import (
    parse_signal_text, import_from_csv, import_from_csv_text,
    import_from_text, ImportResult,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _mock_queue():
    q = MagicMock()
    sig = MagicMock()
    sig.signal_id = "MSQ_1_0001"
    q.submit.return_value = sig
    return q


# ── ImportResult ───────────────────────────────────────────────────────────────

def test_import_result_ok_property():
    r = ImportResult(total=2, accepted=2, rejected=0)
    assert r.ok

def test_import_result_not_ok_with_rejections():
    r = ImportResult(total=2, accepted=1, rejected=1)
    assert not r.ok

def test_import_result_not_ok_zero_accepted():
    r = ImportResult(total=1, accepted=0, rejected=1)
    assert not r.ok

def test_import_result_summary():
    r = ImportResult(total=3, accepted=2, rejected=1)
    s = r.summary()
    assert "3" in s
    assert "2" in s
    assert "1" in s


# ── parse_signal_text ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("NIFTY CALL 80", {"index_name": "NIFTY", "direction": "CALL", "score": 80, "reason": ""}),
    ("BANKNIFTY PUT 75 gap fill breakout",
     {"index_name": "BANKNIFTY", "direction": "PUT", "score": 75, "reason": "gap fill breakout"}),
    ("banknifty call 82 gap_fill_setup",
     {"index_name": "BANKNIFTY", "direction": "CALL", "score": 82, "reason": "gap_fill_setup"}),
    ("FINNIFTY CALL 60", {"index_name": "FINNIFTY", "direction": "CALL", "score": 60, "reason": ""}),
    ("nifty put 78", {"index_name": "NIFTY", "direction": "PUT", "score": 78, "reason": ""}),
])
def test_parse_signal_text_valid(text, expected):
    result = parse_signal_text(text)
    assert result == expected


@pytest.mark.parametrize("text", [
    "",                          # empty
    "   ",                       # whitespace
    "NIFTY CALL",               # missing score
    "NIFTY CALL abc",           # non-numeric score
    "SENSEX CALL 80",           # invalid index
    "NIFTY STRADDLE 80",        # invalid direction
    "NIFTY CALL -1",            # score out of range
    "NIFTY CALL 101",           # score out of range
    "CALL 80",                  # missing index
])
def test_parse_signal_text_invalid(text):
    assert parse_signal_text(text) is None


def test_parse_signal_text_score_boundary():
    assert parse_signal_text("NIFTY CALL 0") is not None
    assert parse_signal_text("NIFTY CALL 100") is not None
    assert parse_signal_text("NIFTY CALL 101") is None


def test_parse_signal_text_reason_with_spaces():
    result = parse_signal_text("NIFTY CALL 80 reason with multiple words")
    assert result["reason"] == "reason with multiple words"


# ── import_from_csv_text ───────────────────────────────────────────────────────

VALID_CSV = """index_name,direction,score,reason
NIFTY,CALL,80,gap fill
BANKNIFTY,PUT,75,trend
"""

def test_import_csv_text_basic():
    q = _mock_queue()
    r = import_from_csv_text(VALID_CSV, q)
    assert r.total == 2
    assert r.accepted == 2
    assert r.rejected == 0
    assert len(r.signal_ids) == 2


def test_import_csv_text_no_queue():
    r = import_from_csv_text(VALID_CSV, None)
    assert r.rejected == 2
    assert "not initialized" in r.errors[0]


def test_import_csv_text_invalid_index():
    csv = "index_name,direction,score\nSENSEX,CALL,80\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.rejected == 1
    assert "index_name" in r.errors[0]


def test_import_csv_text_invalid_direction():
    csv = "index_name,direction,score\nNIFTY,STRADDLE,80\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.rejected == 1
    assert "direction" in r.errors[0]


def test_import_csv_text_invalid_score():
    csv = "index_name,direction,score\nNIFTY,CALL,abc\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.rejected == 1
    assert "score" in r.errors[0]


def test_import_csv_text_score_out_of_range():
    csv = "index_name,direction,score\nNIFTY,CALL,150\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.rejected == 1
    assert "out of range" in r.errors[0]


def test_import_csv_text_optional_columns():
    csv = "index_name,direction,score,reason,lots_override,sl_override,target_override\n"
    csv += "NIFTY,CALL,80,test,2,45.5,90.0\n"
    q = _mock_queue()
    r = import_from_csv_text(csv, q)
    assert r.accepted == 1
    call_kwargs = q.submit.call_args[1]
    assert call_kwargs["lots_override"] == 2
    assert call_kwargs["sl_override"] == 45.5
    assert call_kwargs["target_override"] == 90.0


def test_import_csv_text_column_alias_index():
    csv = "index,direction,score\nNIFTY,CALL,80\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.accepted == 1


def test_import_csv_text_analyst_override():
    csv = "index_name,direction,score,analyst_name\nNIFTY,CALL,80,Alice\n"
    q = _mock_queue()
    import_from_csv_text(csv, q, analyst="DefaultBot")
    call_kwargs = q.submit.call_args[1]
    assert call_kwargs["analyst_name"] == "Alice"


def test_import_csv_text_default_analyst():
    csv = "index_name,direction,score\nNIFTY,CALL,80\n"
    q = _mock_queue()
    import_from_csv_text(csv, q, analyst="MyBot")
    call_kwargs = q.submit.call_args[1]
    assert call_kwargs["analyst_name"] == "MyBot"


def test_import_csv_text_mixed_valid_invalid():
    csv = "index_name,direction,score\nNIFTY,CALL,80\nBAD,CALL,80\nBANKNIFTY,PUT,70\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.total == 3
    assert r.accepted == 2
    assert r.rejected == 1


def test_import_csv_text_submit_exception():
    q = MagicMock()
    q.submit.side_effect = RuntimeError("DB error")
    csv = "index_name,direction,score\nNIFTY,CALL,80\n"
    r = import_from_csv_text(csv, q)
    assert r.rejected == 1
    assert "submit failed" in r.errors[0]


def test_import_csv_text_bom_header():
    csv = "﻿index_name,direction,score\nNIFTY,CALL,80\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.accepted == 1


def test_import_csv_text_whitespace_normalisation():
    csv = "index_name , direction , score\n  NIFTY , CALL , 80\n"
    r = import_from_csv_text(csv, _mock_queue())
    assert r.accepted == 1


# ── import_from_csv (file) ─────────────────────────────────────────────────────

def test_import_from_csv_file_not_found():
    r = import_from_csv("/nonexistent/path/signals.csv", None)
    assert r.rejected == 0
    assert len(r.errors) == 1
    assert "not found" in r.errors[0].lower()


def test_import_from_csv_valid_file(tmp_path):
    f = tmp_path / "signals.csv"
    f.write_text("index_name,direction,score\nNIFTY,CALL,80\n", encoding="utf-8")
    r = import_from_csv(str(f), _mock_queue())
    assert r.accepted == 1


def test_import_from_csv_bom_file(tmp_path):
    f = tmp_path / "bom.csv"
    f.write_bytes(b"\xef\xbb\xbfindex_name,direction,score\r\nNIFTY,CALL,80\r\n")
    r = import_from_csv(str(f), _mock_queue())
    assert r.accepted == 1


# ── import_from_text ───────────────────────────────────────────────────────────

def test_import_from_text_basic():
    text = "NIFTY CALL 80 gap fill\nBANKNIFTY PUT 75\n"
    r = import_from_text(text, _mock_queue())
    assert r.total == 2
    assert r.accepted == 2


def test_import_from_text_skips_blank_lines():
    text = "NIFTY CALL 80\n\n\nBANKNIFTY PUT 75\n"
    r = import_from_text(text, _mock_queue())
    assert r.total == 2


def test_import_from_text_skips_comment_lines():
    text = "# this is a comment\nNIFTY CALL 80\n# another comment\n"
    r = import_from_text(text, _mock_queue())
    assert r.total == 1
    assert r.accepted == 1


def test_import_from_text_invalid_line():
    text = "NIFTY CALL 80\nBOGUS LINE\n"
    r = import_from_text(text, _mock_queue())
    assert r.total == 2
    assert r.accepted == 1
    assert r.rejected == 1
    assert "cannot parse" in r.errors[0]


def test_import_from_text_no_queue():
    r = import_from_text("NIFTY CALL 80\n", None)
    assert r.rejected == 1
    assert "not initialized" in r.errors[0]


def test_import_from_text_empty():
    r = import_from_text("", _mock_queue())
    assert r.total == 0
    assert r.accepted == 0


def test_import_from_text_analyst_tag():
    text = "NIFTY CALL 80\n"
    q = _mock_queue()
    import_from_text(text, q, analyst="RajBot")
    call_kwargs = q.submit.call_args[1]
    assert call_kwargs["analyst_name"] == "RajBot"
