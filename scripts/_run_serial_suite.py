"""Serial full-suite runner — runs one contiguous slice of the test tree.

Usage:
    python scripts/_run_serial_suite.py <batch_index> <total_batches> [--timeout SECONDS]

All test files (root + subdirs) are sorted and split into total_batches
contiguous slices. Each batch runs ONE pytest process (no concurrency) and
appends its output to logs/final_suite.log. Results accumulate across batches,
giving a complete serial pass over the ~14.7k test suite.
"""
from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

idx = int(sys.argv[1])
total = int(sys.argv[2])
timeout_s = int(sys.argv[3]) if len(sys.argv) > 3 else 300

files = sorted(glob.glob(str(ROOT / "tests" / "test_*.py")))
files += sorted(glob.glob(str(ROOT / "tests" / "**" / "test_*.py"), recursive=True))
# Dedup (root glob already covers test_*.py at top level; recursive glob may repeat)
files = sorted(set(files))

n = len(files)
start = n * idx // total
end = n * (idx + 1) // total
mine = files[start:end]

if not mine:
    print(f"[batch{idx}/{total}] no files in slice")
    sys.exit(0)

cmd = [
    sys.executable, "-m", "pytest",
    *mine,
    "-q", "--tb=line", f"--timeout={timeout_s}", "-p", "no:cacheprovider",
]
log = LOGS / "final_suite.log"
with open(log, "a", encoding="utf-8") as out:
    print(f"\n===== BATCH {idx}/{total} ({len(mine)} files) =====", file=out)
    proc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT)

print(f"[batch{idx}/{total}] pytest exit code: {proc.returncode}  ({len(mine)} files)")
