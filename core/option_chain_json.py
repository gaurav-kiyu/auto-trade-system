"""
NSE option-chain JSON helpers (indices + equities).

NSE may return ``\"records\": null``; ``dict.get(\"records\", {})`` yields ``None`` when the
key exists, which broke callers that assumed a mapping. Centralize parsing here.
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)


def option_chain_records(data: Any) -> dict:
    if not isinstance(data, dict):
        return {}
    rec = data.get("records")
    if rec is None and "records" in data:
        _log.warning("[OC] NSE returned records=null - option chain unavailable")
        return {}
    return rec if isinstance(rec, dict) else {}


def option_chain_has_rows(data: Any) -> bool:
    rows = option_chain_records(data).get("data")
    return isinstance(rows, list) and len(rows) > 0
