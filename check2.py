"""Quick check"""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import inspect
from core import stress_tester
print(inspect.signature(stress_tester.run_stress_test))
print(inspect.signature(stress_tester.StressResult))
