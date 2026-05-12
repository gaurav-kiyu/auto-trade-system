from __future__ import annotations

from core.option_chain_json import option_chain_has_rows, option_chain_records


def test_records_null_returns_empty_dict():
    assert option_chain_records({"records": None}) == {}
    assert option_chain_has_rows({"records": None}) is False


def test_valid_chain_has_rows():
    payload = {"records": {"data": [{"strikePrice": 100}], "expiryDates": ["25APR"]}}
    rec = option_chain_records(payload)
    assert option_chain_has_rows(payload) is True
    assert (rec.get("data") or [])[0]["strikePrice"] == 100
