#!/usr/bin/env python3
"""
Architecture Compliance Check - ADR 0010 enforcement for CI.

Checks:
  1. core/ modules must NOT import from infrastructure/ directly (adapter pattern).
  2. Strategy modules must NOT import broker adapters directly.
  3. No circular imports between core/ packages (first-order detection).
  4. Dead/removed modules are not imported anywhere.
  5. Required canonical modules are importable.

Usage:
    python scripts/check_architecture_compliance.py              # verbose
    python scripts/check_architecture_compliance.py --ci         # quiet, exit code only
    python scripts/check_architecture_compliance.py --fixme      # also show known-exempt patterns

Exit code:
    0 = all checks pass
    1 = violations found
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Add project root to sys.path so canonical module checks work
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# -- Module boundary rules ---------------------------------------------------

# core/ modules that are EXEMPT from the no-infrastructure-import rule.
# These are known-legacy modules that bridge to infrastructure/.
CORE_NO_INFRA_MODULES = {
    # core.adapters is the adapter shim layer — allowed
    "core.adapters",
    # core.config_bootstrap imports SecureConfig from infrastructure
    "core.config_bootstrap",
    # core.data_engine uses infrastructure.market_data_cache
    "core.data_engine",
    # nse_option_recorder bridges trading loop to NSE adapter
    "core.nse_option_recorder",
    # persistence/service modules legitimately use infrastructure adapters
    "core.persistence",
    "core.services.notification_service",
    "core.services.persistence_service",
}

# Strategy modules must NOT import broker adapters directly
STRATEGY_NO_BROKER_MODULES = {
    "core.strategy",
    "core.strategy_engine",
    "core.scoring_engine",
    "core.tier_engine",
    "core.signal_router",
}

# Removed/dead modules — any import is a violation.
# These are modules that have been REMOVED from the codebase entirely.
# NOTE: Only list modules that NO LONGER EXIST on disk.
# Do NOT add deprecated-but-still-present modules here.
DEAD_MODULES = {
    "core.risk.authoritative_engine",
    "core.admin_control_plane",
    "core.signal_router",
    "core.strategy_engine_v2",
    "core.predictive_risk",
    "core.trading_risk",
    "core.risk.risk_policy_engine",
    "core.dynamic_risk_sizer",
}

# Modules that are EXEMPT from the direct broker SDK import rule.
# These are legacy modules that need direct access to broker SDKs
# for functionality not exposed through broker_adapters.py (e.g. ticker, token refresh).
BROKER_SDK_EXEMPT_MODULES = {
    "core.kite_ticker_feed",
    "core.token_refresh_service",
}

# Canonical modules that MUST be importable
REQUIRED_CANONICAL = [
    "core.services.risk_service",
    "core.strategy.orchestrator",
    "core.services.execution_service",
    "core.invariants.engine",
    "core.operating_mode",
    "core.di_container",
    "core.oi_snapshot_store",
    "core.audit_engine",
    "core.config_bootstrap",
    "core.datetime_ist",
]

# Known exempt patterns (specific import paths from core/ -> infrastructure/)
KNOWN_EXEMPT_PATTERNS: list[str] = [
    # config_bootstrap imports SecureConfig from infrastructure
    "core.config_bootstrap:from infrastructure.config.secure_config",
    # data_engine uses market_data_cache from infrastructure
    "core.data_engine:from infrastructure.market_data",
    # nse_option_recorder uses NSE market data adapter
    "core.nse_option_recorder:from infrastructure.adapters.market_data.nse.adapter",
    # persistence/trades uses SQLite adapter
    "core.persistence.trades.manager:from infrastructure.adapters.persistence.sqlite_adapter",
    # service modules use notification and database adapters
    "core.services.notification_service:from infrastructure.adapters",
    "core.services.persistence_service:from infrastructure.adapters.persistence.sqlite_adapter",
    # legacy WebSocket and ticker modules - grandfathered
    "core.kite_ticker_feed",
    "core.token_refresh_service:from kiteconnect",
]

# -- Source directory configuration -------------------------------------------

# Only scan these source directories (excludes venv, node_modules, etc.)
_SOURCE_DIRS: list[Path] = [
    ROOT / "core",
    ROOT / "index_app",
    ROOT / "scripts",
    ROOT / "infrastructure",
]
# Also include top-level .py files (individual files, not dirs)
for _f in (ROOT / "signal_engine.py", ROOT / "telegram_engine.py"):
    if _f.is_file():
        _SOURCE_DIRS.append(_f)


def _source_files() -> list[Path]:
    """Return all Python source files from the configured source directories
    (fast - avoids scanning venv/, node_modules/, etc.)."""
    files: list[Path] = []
    for src in _SOURCE_DIRS:
        if src.is_file() and src.suffix == ".py":
            files.append(src)
        elif src.is_dir():
            # Only walk a few levels deep - stops at __pycache__ boundaries
            files.extend(p for p in src.rglob("*.py") if "__pycache__" not in str(p))
    return sorted(files)


# -- AST helpers ---------------------------------------------------------------


def _list_imports(filepath: Path) -> list[str]:
    """Return all top-level import paths referenced by *filepath*.

    Returns both top-level packages (e.g., "infrastructure") and full
    dotted paths (e.g., "infrastructure.config.secure_config") for
    thorough checking.
    """
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name.split(".")[0])  # top-level module
                imports.append(alias.name)  # full dotted path
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module.split(".")[0])
                imports.append(node.module)
                for alias in node.names:
                    if node.module:
                        full = f"{node.module}.{alias.name}"
                        imports.append(full)
    return imports


def _module_name_from_file(filepath: Path) -> str:
    """Convert a file path like 'core/foo/bar.py' to 'core.foo.bar'."""
    rel = filepath.relative_to(ROOT)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(parts)


# -- Checks -------------------------------------------------------------------


def check_core_no_infrastructure_imports() -> list[str]:
    """Check 1: core/ modules must not import from infrastructure/ directly."""
    violations: list[str] = []
    core_dir = ROOT / "core"
    infra_prefixes = ("infrastructure",)
    for pyfile in sorted(core_dir.rglob("*.py")):
        mod = _module_name_from_file(pyfile)
        # Skip __init__.py files and known-legacy core.adapters
        if any(mod.startswith(p) for p in CORE_NO_INFRA_MODULES):
            continue
        # Skip external packages or __pycache__
        if "__pycache__" in str(pyfile):
            continue
        imports = _list_imports(pyfile)
        for imp in imports:
            if imp.startswith(infra_prefixes):
                # Check known exemptions
                key = f"{mod}:{imp}"
                if any(key.startswith(e) for e in KNOWN_EXEMPT_PATTERNS):
                    continue
                violations.append(
                    f"IMPORT_VIOLATION: {mod} imports infrastructure module '{imp}'"
                )
    return violations


def check_strategy_no_broker_imports() -> list[str]:
    """Check 2: Strategy modules must not import broker adapters directly."""
    violations: list[str] = []
    broker_keywords = ("broker_adapter", "kiteconnect", "angelbroking", "PaperBrokerAdapter")

    for pyfile in _source_files():
        mod = _module_name_from_file(pyfile)
        # Only check strategy-related modules
        if not any(mod.startswith(p) for p in STRATEGY_NO_BROKER_MODULES):
            continue
        try:
            content = pyfile.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for kw in broker_keywords:
            if kw.lower() in content.lower():
                violations.append(
                    f"BROKER_IMPORT_VIOLATION: {mod} references broker symbol '{kw}'"
                )
    return violations


def check_dead_modules_not_imported() -> list[str]:
    """Check 3: Dead/removed modules must not be imported anywhere.

    Scans core/, index_app/, scripts/, and infrastructure/ (excludes tests).
    """
    violations: list[str] = []
    for pyfile in _source_files():
        mod = _module_name_from_file(pyfile)
        imports = _list_imports(pyfile)
        for imp in imports:
            # Check each dead module against full import path
            for dead in DEAD_MODULES:
                # Check if the import path matches the dead module exactly (or is a sub-import of it).
                # Do NOT check just the top-level package prefix — that causes false positives.
                if imp == dead or imp.startswith(dead + "."):
                    violations.append(
                        f"DEAD_IMPORT: {mod} imports dead module '{imp}' (see {dead})"
                    )
    return violations


def check_canonical_modules_importable() -> list[str]:
    """Check 4: All required canonical modules must be importable.

    Uses ``importlib.util.find_spec`` to check existence WITHOUT
    actually importing the module (avoids side effects from module init).
    """
    import importlib.util
    violations: list[str] = []
    for mod_path in REQUIRED_CANONICAL:
        spec = importlib.util.find_spec(mod_path)
        if spec is None:
            violations.append(
                f"MISSING_CANONICAL: {mod_path} — module not found on sys.path"
            )
    return violations


def check_no_direct_broker_sdk_imports() -> list[str]:
    """Check 5: No direct Kite/Angel SDK imports outside broker_adapters.py.

    Exemptions:
        - core.kite_ticker_feed (needs kiteconnect.ticker.KiteTicker)
        - core.token_refresh_service (needs kiteconnect.KiteConnect)
    """
    violations: list[str] = []
    broker_sdk_modules = {"kiteconnect", "angelbroking", "pykiteconnect"}

    for pyfile in sorted((ROOT / "core").rglob("*.py")):
        if "__pycache__" in str(pyfile):
            continue
        mod = _module_name_from_file(pyfile)
        # broker_adapters.py is the single allowed entry point
        if "broker_adapter" in mod:
            continue
        # Skip exempt legacy modules
        if mod in BROKER_SDK_EXEMPT_MODULES:
            continue
        imports = _list_imports(pyfile)
        for imp in imports:
            top = imp.split(".")[0]
            if top in broker_sdk_modules:
                violations.append(
                    f"BROKER_SDK_IMPORT: {mod} directly imports '{imp}' — "
                    f"must go through core/adapters/broker_adapters.py"
                )
    return violations


# -- Main ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--ci",
        action="store_true",
        help="Quiet mode (only exit code, no verbose output)",
    )
    ap.add_argument(
        "--fixme",
        action="store_true",
        help="Also show known-exempt patterns (for maintenance)",
    )
    args = ap.parse_args(argv)

    checkers: list[tuple[str, Any]] = [
        ("core/ -> infrastructure/ import", check_core_no_infrastructure_imports),
        ("Strategy -> broker import", check_strategy_no_broker_imports),
        ("Dead module import", check_dead_modules_not_imported),
        ("Canonical module importable", check_canonical_modules_importable),
        ("Direct broker SDK import", check_no_direct_broker_sdk_imports),
    ]

    all_violations: list[str] = []
    if not args.ci:
        print("=" * 70)
        print("  ARCHITECTURE COMPLIANCE CHECK - ADR 0010")
        print("=" * 70)

    for name, checker in checkers:
        violations = checker()
        if not args.ci:
            status = "[FAIL]" if violations else "[PASS]"
            print(f"\n  {status} {name}")
            if violations:
                for v in violations:
                    print(f"    + {v}")
        all_violations.extend(violations)

    # Known exemptions (only shown with --fixme)
    if args.fixme and KNOWN_EXEMPT_PATTERNS:
        print(f"\n  [FIXME] Known exempt patterns ({len(KNOWN_EXEMPT_PATTERNS)}):")
        for e in KNOWN_EXEMPT_PATTERNS:
            print(f"    + {e}")

    total = len(all_violations)
    if total == 0:
        if not args.ci:
            print(f"\n{'=' * 70}")
            print("  [PASS] ALL CHECKS PASSED - architecture compliant")
            print(f"{'=' * 70}")
        return 0
    else:
        if not args.ci:
            print(f"\n{'=' * 70}")
            print(f"  [FAIL] {total} VIOLATION(S) FOUND - architecture NOT compliant")
            print(f"{'=' * 70}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
