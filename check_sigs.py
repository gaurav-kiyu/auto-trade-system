"""Signature check for full_sim_test.py imports."""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import inspect

checks = [
    ("core.var_calculator", "compute_var"),
    ("core.kelly_sizer", "compute_kelly_lots"),
    ("core.implied_move", "ImpliedMoveCalculator"),
    ("core.health_checker", "run_full_health_check"),
]

for mod_name, func_name in checks:
    mod = __import__(mod_name, fromlist=[func_name])
    fn = getattr(mod, func_name)
    try:
        sig = inspect.signature(fn)
        print(f"  OK  {mod_name}.{func_name}{sig}")
    except TypeError:
        print(f"  OK  {mod_name}.{func_name} [class]")
