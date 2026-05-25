"""
Cleanup test artifacts and runtime DB files.

Run this before creating release builds to remove:
- test_recon_*.db files
- test_*.db files
- temporary DB files
- __pycache__ directories
- .pyc files
"""

import shutil
from pathlib import Path


def cleanup_test_dbs(root_dir: str) -> int:
    """Remove test DB files."""
    removed = 0
    root = Path(root_dir)

    for db_file in root.glob("test_recon_*.db"):
        db_file.unlink()
        removed += 1

    for db_file in root.glob("test_execution_state.db"):
        db_file.unlink()
        removed += 1

    test_db = root / "test_execution_state.db"
    if test_db.exists():
        test_db.unlink()
        removed += 1

    execution_db = root / "execution_state.db"
    if execution_db.exists() and execution_db.stat().st_size < 1000:
        execution_db.unlink()
        removed += 1

    order_db = root / "order_state.db"
    if order_db.exists() and order_db.stat().st_size < 1000:
        order_db.unlink()
        removed += 1

    return removed


def cleanup_pycache(root_dir: str) -> int:
    """Remove __pycache__ directories."""
    removed = 0
    root = Path(root_dir)

    for pycache in root.rglob("__pycache__"):
        try:
            shutil.rmtree(pycache)
            removed += 1
        except Exception:
            pass

    return removed


def cleanup_pyc_files(root_dir: str) -> int:
    """Remove .pyc files."""
    removed = 0
    root = Path(root_dir)

    for pyc in root.rglob("*.pyc"):
        pyc.unlink()
        removed += 1

    return removed


def cleanup_logs(root_dir: str) -> int:
    """Clean old log files."""
    removed = 0
    root = Path(root_dir)
    logs_dir = root / "logs"

    if not logs_dir.exists():
        return 0

    for log_file in logs_dir.glob("*.log.*"):
        if log_file.stat().st_size > 10 * 1024 * 1024:
            log_file.unlink()
            removed += 1

    return removed


def main():
    import sys
    root_dir = sys.argv[1] if len(sys.argv) > 1 else "."

    print(f"Cleaning up test artifacts in: {root_dir}")

    dbs = cleanup_test_dbs(root_dir)
    print(f"Removed {dbs} test DB files")

    pycache = cleanup_pycache(root_dir)
    print(f"Removed {pycache} __pycache__ directories")

    pyc = cleanup_pyc_files(root_dir)
    print(f"Removed {pyc} .pyc files")

    logs = cleanup_logs(root_dir)
    print(f"Removed {logs} large log files")

    print("\nCleanup complete!")


if __name__ == "__main__":
    main()
