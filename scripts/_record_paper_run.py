"""Appends one run record to reports/paper_trading/run_history.json.

Extracted out of scripts/run_paper_trading.bat's old inline `python -c
"..."` block, which was a multi-line quoted string a Windows batch file
can't actually execute correctly - each line past the first was being
interpreted as its own separate batch command (see CHANGELOG.md v2.59.0),
so this tracking file was silently never updated by that scheduled task.

Usage: python scripts/_record_paper_run.py <tracking_file> <exit_code>
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: _record_paper_run.py <tracking_file> <exit_code>", file=sys.stderr)
        return 1

    tracking_file = Path(sys.argv[1])
    try:
        exit_code = int(sys.argv[2])
    except ValueError:
        exit_code = -1

    try:
        history = json.loads(tracking_file.read_text(encoding="utf-8"))
        if not isinstance(history, list):
            history = []
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        history = []

    history.append({
        "timestamp": datetime.datetime.now().isoformat(),
        "exit_code": exit_code,
        "mode": "PAPER",
        "certification_gate_passed": exit_code == 0,
    })

    tracking_file.write_text(json.dumps(history, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
