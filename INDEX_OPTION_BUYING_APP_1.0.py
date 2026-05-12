"""
DEPRECATED — Compatibility shim for INDEX_OPTION_BUYING_APP_1.0.py

This script exists only to provide backward compatibility for scripts or
workflows that import from the old monolithic ``INDEX_OPTION_BUYING_APP_1.0``
module name.

New code should import directly from ``index_app.index_trader`` or use
the DI container wired services in ``core/``.

Will be removed in v3.0.
"""
from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path

warnings.warn(
    "INDEX_OPTION_BUYING_APP_1.0 is deprecated. "
    "Use `from index_app.index_trader import ...` instead.",
    DeprecationWarning,
    stacklevel=2,
)

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_mod = importlib.import_module("index_app.index_trader")
for _name in dir(_mod):
    if _name.startswith("__") and _name.endswith("__"):
        continue
    globals()[_name] = getattr(_mod, _name)


def main() -> None:
    _mod.main()


if __name__ == "__main__":
    _mod.main()
