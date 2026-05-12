"""
Minimal log helpers for logging service.
"""

import os
import time
from typing import Dict, Any


def cleanup_old_prefixed_logs(
    logs_dir: str,
    filename_prefix: str,
    *,
    retain_days: int = 30,
    delete_rotated_variants: bool = True,
) -> None:
    """Remove ``{prefix}*.log`` and optional ``{prefix}*.log.*`` older than ``retain_days`` (best-effort, silent)."""
    try:
        cutoff = time.time() - retain_days * 86400
        if not os.path.isdir(logs_dir):
            return
        for fn in os.listdir(logs_dir):
            if not fn.startswith(filename_prefix):
                continue
            fp = os.path.join(logs_dir, fn)
            if not os.path.isfile(fp):
                continue
            if os.path.getmtime(fp) >= cutoff:
                continue
            if fn.endswith(".log") or fn.endswith(".jsonl"):
                try:
                    os.remove(fp)
                except OSError:
                    pass
            elif delete_rotated_variants and (".log." in fn or ".jsonl." in fn):
                try:
                    os.remove(fp)
                except OSError:
                    pass
    except Exception:
        # Best effort - ignore cleanup errors
        pass


def format_weekday_bias_str(weekday_bias: dict) -> str:
    """Stub function for compatibility."""
    return ""