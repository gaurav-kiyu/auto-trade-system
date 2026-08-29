#!/usr/bin/env python3
"""Fix stale documentation references to missing core modules.

Scans all .md files (excluding docs/archive/) and replaces backtick-wrapped
`core/xxx.py` references where the module file no longer exists, replacing
them with either the correct replacement path or a [removed] marker.

Usage:
    python scripts/fix_stale_doc_refs.py          # dry-run (preview)
    python scripts/fix_stale_doc_refs.py --apply   # apply fixes
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

# ── Replacement mapping ──────────────────────────────────────────────────────
# Maps missing module paths to their modern replacements
# None = remove backticks and add [removed] marker

_REPLACEMENTS: dict[str, str | None] = {
    # Refactored into packages
    "core/di_container.py": "core/di_container/__init__.py",
    "core/enterprise_dashboard.py": "core/enterprise_dashboard/__init__.py",
    "core/constitution.py": "core/constitution/__init__.py",
    "core/auto_tuner.py": "core/auto_tuner/__init__.py",

    # Renamed modules (verified on disk)
    "core/rbac.py": "core/auth/permissions.py",
    "core/mfa.py": "core/auth/mfa.py",
    "core/sso.py": "core/auth/sso.py",
    "core/iv_skew.py": "core/iv_rank.py",
    "core/corp_action_calendar.py": "core/event_calendar.py",
    "core/timeframe_divergence.py": "core/adaptive_signal.py",
    "core/paper_fill_simulation.py": "core/limit_order_engine.py",
    "core/heatmap.py": "core/signal_autopsy.py",
    "core/execution_engine.py": "core/services/execution_service.py",
    "core/risk_engine.py": "core/services/risk_service.py",
    "core/strategy_engine.py": "core/strategy/orchestrator.py",
    "core/orchestrator.py": "core/services/use_cases/trading_orchestrator.py",
    "core/portfolio_optimizer.py": "core/kelly_sizer.py",
    "core/config_audit.py": "core/config_audit_log.py",
    "core/self_healing_orchestrator.py": "core/invariants/engine.py",
    "core/opentelemetry.py": "core/telemetry/metrics.py",
    "core/secure_config.py": "core/config_bootstrap.py",
    "core/rate_limiting_service.py": "core/ports/rate_limiting/rate_limiting_port.py",
    "core/query_bus.py": None,
    "core/futures_trader.py": None,
    "core/domain_equity.py": None,
    "core/domain_fixed_income.py": None,
    "core/domain_sme.py": None,
    "core/execution_stack.py": None,
    "core/trading_orchestrator.py": None,
    "core/iv_rank.py": "core/iv_rank.py",
}

# Files to skip entirely (historical snapshots)
_SKIP_PREFIXES = ["docs/archive/", "docs\\archive\\"]

# Regex matching backtick-wrapped core/xxx.py references
_MODULE_REF_RE = re.compile(r"`(core/[a-z_]+\.py)`")

# Stats
_stats = {"files_scanned": 0, "files_modified": 0, "refs_fixed": 0, "errors": 0}


def fix_file(path: Path, dry_run: bool) -> bool:
    """Fix stale references in a single .md file. Returns True if modified."""
    path_str = path.as_posix()
    for prefix in _SKIP_PREFIXES:
        if path_str.startswith(prefix):
            return False

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError) as e:
        print(f"  [ERR] Cannot read {path}: {e}")
        _stats["errors"] += 1
        return False

    original = content
    modified = False

    for match in _MODULE_REF_RE.finditer(content):
        ref = match.group(1)
        module_path = Path(ref)

        # Skip if module exists on disk
        if module_path.exists():
            continue

        # Determine replacement
        replacement = _REPLACEMENTS.get(ref)
        if replacement is None:
            # No known replacement => remove backticks, add [removed]
            new_text = f"{ref} [removed]"
        elif replacement == ref:
            # Same ref (shouldn't happen for missing modules, but safety)
            continue
        else:
            # Has known replacement => keep backticks with new path
            new_text = f"`{replacement}`"

        # Build the replacement string (remove backticks from original)
        old_text = match.group(0)
        content = content.replace(old_text, new_text, 1)
        modified = True
        _stats["refs_fixed"] += 1

        if dry_run:
            print(f"  [DRY-RUN] {path.name}:{_line_num(original, match.start())}: "
                  f"`{ref}` -> {new_text}")
        else:
            print(f"  [FIX] {path.name}:{_line_num(original, match.start())}: "
                  f"`{ref}` -> {new_text}")

    if modified and not dry_run:
        path.write_text(content, encoding="utf-8")
        _stats["files_modified"] += 1

    return modified


def _line_num(content: str, pos: int) -> int:
    return content[:pos].count("\n") + 1


def main() -> int:
    dry_run = "--apply" not in sys.argv

    print("=" * 60)
    print(f"  {'DRY-RUN: ' if dry_run else ''}Fixing stale doc references")
    print("=" * 60)

    md_files = sorted(glob.glob("**/*.md", recursive=True))
    for f in md_files:
        p = Path(f)
        # Skip hidden dirs, node_modules, archive
        if "/." in f or f.startswith("node_modules/"):
            continue
        if any(f.startswith(pre) for pre in _SKIP_PREFIXES):
            continue
        fix_file(p, dry_run=dry_run)
        _stats["files_scanned"] += 1

    print()
    print(f"  Scanned: {_stats['files_scanned']} files")
    print(f"  Fixed:   {_stats['refs_fixed']} references across {_stats['files_modified']} files")
    print(f"  Errors:  {_stats['errors']}")

    if dry_run:
        print("\n  Run with --apply to apply these changes.")

    return 0 if _stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
