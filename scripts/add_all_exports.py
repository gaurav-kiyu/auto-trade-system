"""Auto-generate __all__ exports for core modules missing them.

Scans all Python files under core/ (excluding __init__.py and __pycache__),
parses public top-level symbols (classes, functions, constants),
and prepends an __all__ list if one is missing.

Safe: skips files that already have __all__, files with syntax errors,
and files whose AST cannot be parsed.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts._add_exports_common import scan_and_add  # noqa: E402

CORE_DIR = PROJECT_ROOT / "core"


def main() -> int:
    """Scan core/ and add __all__ to all modules missing it."""
    return scan_and_add(
        CORE_DIR,
        skip_init=True,
        skip_private=False,
    )


if __name__ == "__main__":
    sys.exit(main())
