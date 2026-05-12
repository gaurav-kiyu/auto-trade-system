"""
Index option trading application package.

Prefer running ``python INDEX_OPTION_BUYING_APP_1.0.py`` or
``python -m index_app.index_trader`` from the repo root.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["VERSION", "main", "build_index_orchestrator"]


def __getattr__(name: str) -> Any:
    if name == "VERSION":
        return importlib.import_module("index_app.index_trader").VERSION
    if name == "main":
        return importlib.import_module("index_app.index_trader").main
    if name == "build_index_orchestrator":
        from index_app.orchestrator_facade import build_index_orchestrator as _b

        return _b
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
