"""Fix `e.__name__` → `type(e).__name__` across all affected files.

Exception instances do not have __name__. Only exception classes do.
This script replaces `e.__name__` with `type(e).__name__` and fixes
duplicate strings like `(type: ...) (type: ...)`.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FILES = [
    "core/ai/rollback_controller.py",
    "core/anomaly_detector.py",
    "core/audit_journal.py",
    "core/circuit_breaker_monitor.py",
    "core/cognitive_sentiment.py",
    "core/execution/deterministic_state_machine.py",
    "core/execution/order_submission/manager.py",
    "core/execution/retry_policy/manager.py",
    "core/hmm_regime_detector.py",
    "core/incident_alerting.py",
    "core/lot_size_validator.py",
    "core/ml_exit_classifier.py",
    "core/ml_regime_router.py",
    "core/observability.py",
    "core/realtime_performance_monitor.py",
    "core/rl_exit_optimizer.py",
    "core/state_manager.py",
    "core/services/persistence_service.py",
    "core/system_mode.py",
    "core/strategy/strategy_versioning.py",
    "core/strategy/sandbox.py",
]

total_fixes = 0

for rel_path in FILES:
    path = ROOT / rel_path
    if not path.exists():
        print(f"SKIP {rel_path} (not found)")
        continue

    content = path.read_text(encoding="utf-8", errors="replace")
    original = content

    # Fix 1: Remove duplicate "(type: ...) (type: ...)" → single "(type: ...)"
    content = re.sub(
        r'\(type: \{e\.__name__\}\)\s*\(type: \{e\.__name__\}\)',
        '(type: {type(e).__name__})',
        content
    )

    # Fix 2: Replace remaining `{e.__name__}` → `{type(e).__name__}`
    content = content.replace("{e.__name__}", "{type(e).__name__}")

    if content != original:
        path.write_text(content, encoding="utf-8")
        # Count changes
        changes = sum(1 for a, b in zip(original.splitlines(), content.splitlines()) if a != b)
        total_fixes += changes
        print(f"FIXED {rel_path} ({changes} changes)")
    else:
        print(f"OK   {rel_path} (no changes needed)")

print(f"\nTotal: {total_fixes} fixes across {len(FILES)} files")
