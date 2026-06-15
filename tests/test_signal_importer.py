"""Tests for SignalImporter — import signals from CSV, text, and parse lines."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.signal_importer import (
    ImportResult,
    parse_signal_text,
    import_from_csv,
    import_from_csv_text,
    import_from_text,
)


class TestImportResult:
    """ImportResult dataclass."""

    def test_ok_property_true(self):
        r = ImportResult(total=5, accepted=5, rejected=0)
        assert r.ok is True

    def test_ok_property_false(self):
        r = ImportResult(total=5, accepted=3, rejected=2)
        assert r.ok is False

    def test_summary_format(self):
        r = ImportResult(total=10, accepted=8, rejected=2)
        assert "8 accepted" in r.summary()
        assert "2 rejected" in r.summary()


class TestParseSignalText:
    """parse_signal_text — free-text signal parsing."""

    def test_valid_minimal(self):
        result = parse_signal_text("NIFTY CALL 82")
        assert result == {"index_name": "NIFTY", "direction": "CALL", "score": 82, "reason": ""}

    def test_valid_with_reason(self):
        result = parse_signal_text("BANKNIFTY PUT 75 gap_fill_setup")
        assert result["index_name"] == "BANKNIFTY"
        assert result["direction"] == "PUT"
        assert result["score"] == 75
        assert result["reason"] == "gap_fill_setup"

    def test_valid_multi_word_reason(self):
        result = parse_signal_text("FINNIFTY CALL 85 strong breakout above resistance")
        assert result["score"] == 85
        assert "strong breakout" in result["reason"]

    def test_case_insensitive(self):
        result = parse_signal_text("banknifty call 82")
        assert result["index_name"] == "BANKNIFTY"
        assert result["direction"] == "CALL"

    def test_empty_text(self):
        result = parse_signal_text("")
        assert result is None

    def test_whitespace_text(self):
        result = parse_signal_text("   ")
        assert result is None

    def test_invalid_index(self):
        result = parse_signal_text("INVALID CALL 82")
        assert result is None

    def test_invalid_direction(self):
        result = parse_signal_text("NIFTY SELL 82")
        assert result is None

    def test_non_numeric_score(self):
        result = parse_signal_text("NIFTY CALL abc")
        assert result is None

    def test_score_out_of_range(self):
        result = parse_signal_text("NIFTY CALL 150")
        assert result is None

    def test_score_negative(self):
        result = parse_signal_text("NIFTY CALL -5")
        assert result is None

    def test_score_zero(self):
        result = parse_signal_text("NIFTY CALL 0")
        assert result is not None
        assert result["score"] == 0

    def test_score_one_hundred(self):
        result = parse_signal_text("NIFTY CALL 100")
        assert result is not None
        assert result["score"] == 100

    def test_too_few_tokens(self):
        result = parse_signal_text("NIFTY CALL")
        assert result is None


class TestImportFromText:
    """import_from_text — import signals from newline-separated text."""

    def test_import_single(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_text("NIFTY CALL 82 test", queue)
        assert result.total == 1
        assert result.accepted == 1
        assert result.rejected == 0

    def test_import_multiple(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_text("NIFTY CALL 82 a\nBANKNIFTY PUT 75 b", queue)
        assert result.total == 2
        assert result.accepted == 2

    def test_skips_blank_lines(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_text("NIFTY CALL 82\n\n\nBANKNIFTY PUT 75", queue)
        assert result.total == 2
        assert result.accepted == 2

    def test_skips_comments(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_text("# comment\nNIFTY CALL 82", queue)
        assert result.total == 1
        assert result.accepted == 1

    def test_rejects_unparsable(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_text("INVALID CALL 82", queue)
        assert result.total == 1
        assert result.rejected == 1

    def test_no_queue(self):
        result = import_from_text("NIFTY CALL 82", None)
        assert result.rejected == 1
        assert result.total == 1

    def test_submit_error(self):
        queue = MagicMock()
        queue.submit.side_effect = ValueError("Queue full")
        result = import_from_text("NIFTY CALL 82", queue)
        assert result.rejected == 1


class TestImportFromCSV:
    """import_from_csv and import_from_csv_text."""

    CSV_HEADER = "index_name,direction,score,reason\n"
    CSV_VALID = CSV_HEADER + "NIFTY,CALL,82,gap fill setup\nBANKNIFTY,PUT,75,\n"

    def test_import_valid_csv(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_csv_text(self.CSV_VALID, queue)
        assert result.total == 2
        assert result.accepted == 2
        assert result.rejected == 0

    def test_import_invalid_index(self):
        queue = MagicMock()
        csv_text = "index_name,direction,score,reason\nINVALID,CALL,82,test\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.total == 1
        assert result.rejected == 1

    def test_import_invalid_direction(self):
        queue = MagicMock()
        csv_text = "index_name,direction,score,reason\nNIFTY,SELL,82,test\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.total == 1
        assert result.rejected == 1

    def test_import_invalid_score(self):
        queue = MagicMock()
        csv_text = "index_name,direction,score,reason\nNIFTY,CALL,abc,test\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.total == 1
        assert result.rejected == 1

    def test_import_score_out_of_range(self):
        queue = MagicMock()
        csv_text = "index_name,direction,score,reason\nNIFTY,CALL,200,test\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.total == 1
        assert result.rejected == 1

    def test_signal_ids_collected(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        result = import_from_csv_text("index_name,direction,score,reason\nNIFTY,CALL,82,test\n", queue)
        assert "SIG-001" in result.signal_ids

    def test_import_no_queue(self):
        result = import_from_csv_text("index_name,direction,score,reason\nNIFTY,CALL,82,test\n", None)
        assert result.rejected == 1

    def test_import_file_not_found(self):
        result = import_from_csv("nonexistent.csv", MagicMock())
        assert len(result.errors) > 0
        assert "not found" in result.errors[0]

    def test_import_with_optional_fields(self):
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        csv_text = "index_name,direction,score,reason,lots_override,analyst_name\nNIFTY,CALL,82,test,2,Alice\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.accepted == 1
        # Verify submit was called with lots_override=2
        _, kwargs = queue.submit.call_args
        assert kwargs.get("lots_override") == 2

    def test_bom_handling(self):
        """Should handle UTF-8 BOM."""
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        csv_text = "\ufeffindex_name,direction,score\nNIFTY,CALL,82\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.accepted == 1

    def test_alias_columns(self):
        """Should accept 'index' as alias for 'index_name'."""
        queue = MagicMock()
        queue.submit.return_value.signal_id = "SIG-001"
        csv_text = "index,direction,score,reason\nNIFTY,CALL,82,test\n"
        result = import_from_csv_text(csv_text, queue)
        assert result.accepted == 1
