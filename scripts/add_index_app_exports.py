"""Add __all__ exports to index_app modules missing them.

Skips __init__.py, __pycache__, and private modules (starting with _).
Handles index_trader.py specially by excluding ALL_CAPS constants.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._add_exports_common import scan_and_add  # noqa: E402

INDEX_DIR = PROJECT_ROOT / "index_app"


def _is_not_all_caps(name: str) -> bool:
    """Filter out ALL_CAPS constants (config keys, etc.)."""
    return not name.isupper()


def main() -> int:
    """Scan index_app/ and add __all__ to all modules missing it."""
    return scan_and_add(
        INDEX_DIR,
        skip_init=True,
        skip_private=True,
        symbol_filter=_is_not_all_caps,
    )


if __name__ == "__main__":
    sys.exit(main())
