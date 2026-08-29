"""Temporary helper: run 1 of 4 fast-suite chunks (or the slow-marked suite).

Usage:
    python scripts/_run_test_chunk.py <chunk_index>   # 0..3 => fast chunks
    python scripts/_run_test_chunk.py slow            # slow-marked suite
"""
from __future__ import annotations

import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs"
LOGS.mkdir(exist_ok=True)

which = sys.argv[1] if len(sys.argv) > 1 else "0"

if which == "slow":
    paths = ["tests/"]
    extra = ["-m", "slow"]
    label = "slow"
elif which == "slowfile":
    # python scripts/_run_test_chunk.py slowfile <basename|glob>
    pat = sys.argv[2]
    paths = sorted(glob.glob(str(ROOT / f"tests/{pat}")))
    extra = []
    label = pat.replace("*", "_").replace("?", "_")
elif which == "sub3":
    # python scripts/_run_test_chunk.py sub3 <k>   (k=0..2): one third of chunk3
    k = int(sys.argv[2])
    files = sorted(glob.glob(str(ROOT / "tests/test_*.py")))
    mine = [f for i, f in enumerate(files) if i % 4 == 3]
    paths = mine[k::3]
    extra = ["-m", "not slow"]
    label = f"chunk3-{k}"
else:
    idx = int(which)
    files = sorted(glob.glob(str(ROOT / "tests/test_*.py")))
    mine = [f for i, f in enumerate(files) if i % 4 == idx]
    paths = mine
    extra = ["-m", "not slow"]
    label = f"chunk{idx}"

cmd = [
    sys.executable, "-m", "pytest",
    *paths,
    *extra,
    "-q", "--tb=line", "--timeout=180", "-p", "no:cacheprovider",
]
log = LOGS / f"test_{label}.log"
with open(log, "w", encoding="utf-8") as out:
    proc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, timeout=3600)
print(f"[{label}] pytest exit code: {proc.returncode}")
print(f"[{label}] log: {log}")
with open(log, encoding="utf-8", errors="replace") as fh:
    tail = fh.readlines()[-15:]
print("".join(tail))
