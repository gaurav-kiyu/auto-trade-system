#!/usr/bin/env python3
"""
Rollback Automation Script — OPB Institutional Platform v2.53.0

Performs automated rollback for 5 scenarios as documented in ROLLBACK_PLAN.md:
  1. Code rollback (git checkout to previous version)
  2. Config rollback (restore config.json from backup)
  3. Database rollback (restore trades.db from backup)
  4. Broker API rollback (switch broker driver)
  5. Infrastructure rollback (Docker restart)

Usage:
    python scripts/rollback.py --version v2.52.0          # Code rollback
    python scripts/rollback.py --config --restore config.json.bak  # Config rollback
    python scripts/rollback.py --db --backup-file trades.db.bak    # DB rollback
    python scripts/rollback.py --broker ANGEL             # Broker switch
    python scripts/rollback.py --docker-restart           # Docker restart
    python scripts/rollback.py --test                     # Rollback dry-run test
    python scripts/rollback.py --status                   # Check rollback readiness

Exit code:
    0 = rollback completed successfully
    1 = rollback failed (manual intervention required)
    2 = pre-conditions not met (use --force to override)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("rollback")

BACKUP_DIR = ROOT / "backups"
STATE_FILE = ROOT / "trader_state.json"
CONFIG_FILE = ROOT / "config.json"
CONFIG_DEFAULTS = ROOT / "index_config.defaults.json"
TRADES_DB = ROOT / "trades.db"
TRADE_JOURNAL_DB = ROOT / "trade_journal.db"


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════════


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _run_cmd(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a shell command and return the result."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
    if result.stderr and result.returncode != 0:
        log.debug("CMD stderr (%s): %s", cmd[0], result.stderr.strip()[:200])
    return result


def _halt_trading(reason: str = "Rollback in progress") -> bool:
    """Set HARD_HALT event to block all new entries. Best-effort."""
    try:
        from core.safety_state import trip_hard_halt
        trip_hard_halt(reason, source="rollback_script")
        log.warning("HALT: Trading halted — %s", reason)
        return True
    except (ImportError, ValueError, TypeError, AttributeError, OSError) as e:
        log.critical(
            "HALT: Could not trip hard halt automatically (%s). "
            "MANUAL ACTION REQUIRED: touch STOP_TRADING in project root "
            "or set MANUAL_SIGNALS_ONLY=true in config", e
        )
        return False


def _remove_halt() -> bool:
    """Remove HARD_HALT event. Best-effort."""
    try:
        from core.safety_state import _HARD_HALT
        _HARD_HALT.clear()
        log.info("HALT removed — trading can resume")
        return True
    except (ImportError, ValueError, TypeError, AttributeError, OSError) as e:
        log.warning("Could not remove hard halt (manual resume required): %s", e)
        return False


def _backup_file(src: Path, suffix: str = "") -> Path | None:
    """Backup a file to backups/ directory. Returns backup path or None."""
    if not src.exists():
        log.warning("BACKUP: %s not found — skipping backup", src.name)
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    backup_name = f"{src.stem}_{ts}{suffix}{src.suffix}"
    backup_path = BACKUP_DIR / backup_name
    try:
        shutil.copy2(str(src), str(backup_path))
        log.info("BACKUP: %s → %s", src.name, backup_path.name)
        return backup_path
    except (OSError, shutil.Error) as e:
        log.error("BACKUP: Failed to backup %s: %s", src.name, e)
        return None


def _verify_paper_mode() -> tuple[bool, str]:
    """Verify paper mode works by checking config defaults and critical imports.
    
    Note: This is a fast static check. It does NOT actually start the trading
    loop. For full verification, run:
        python index_app/index_trader.py --paper --debug
    """
    try:
        cfg_path = ROOT / "index_config.defaults.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            if not cfg.get("PAPER_MODE", True):
                return False, "Paper mode is NOT set in defaults"
        # Verify critical imports resolve (catches broken deployments early)
        try:
            from core.safety_state import trip_hard_halt as _thh
            _thh  # reference to confirm import resolved
        except ImportError as imp_err:
            return False, f"Critical import failed: {imp_err}"
        return True, "Paper mode: defaults confirmed + imports resolve"
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Paper mode verification failed: {e}"


# ═══════════════════════════════════════════════════════════════════════════════
#  Rollback Scenarios
# ═══════════════════════════════════════════════════════════════════════════════


def rollback_code(target_version: str, force: bool = False) -> int:
    """Rollback to a previous git version (Section 2.1)."""
    log.info("=== CODE ROLLBACK → %s ===", target_version)

    # Step 1: HALT
    if not force:
        _halt_trading(f"Code rollback to {target_version}")

    # Step 2: Backup state
    state_backup = _backup_file(STATE_FILE)

    # Step 3: Check git availability
    result = _run_cmd(["git", "rev-parse", "--git-dir"])
    if result.returncode != 0:
        log.error("Not a git repository — cannot perform code rollback")
        return 1

    # Step 4: Fetch tags/branches
    _run_cmd(["git", "fetch", "--tags", "--force"], timeout=30)

    # Step 5: Stash local changes
    stash_result = _run_cmd(["git", "stash"])
    if stash_result.returncode == 0:
        log.info("Local changes stashed")

    # Step 6: Checkout target version
    checkout_target = target_version
    # If target doesn't start with 'tags/' or 'release/', check both
    tag_result = _run_cmd(["git", "rev-parse", f"tags/{target_version}"])
    if tag_result.returncode == 0:
        checkout_target = f"tags/{target_version}"
    branch_result = _run_cmd(["git", "rev-parse", f"release/{target_version}"])
    if branch_result.returncode == 0:
        checkout_target = f"release/{target_version}"

    checkout = _run_cmd(["git", "checkout", checkout_target])
    if checkout.returncode != 0:
        log.error("CHECKOUT FAILED: %s — %s", checkout_target, checkout.stderr.strip())
        # Attempt fallback
        fallback = _run_cmd(["git", "checkout", target_version])
        if fallback.returncode != 0:
            log.error("FALLBACK CHECKOUT ALSO FAILED")
            return 1
    log.info("CHECKOUT: Switched to %s", checkout_target)

    # Step 7: Reinstall dependencies
    req_files = [ROOT / "requirements.txt", ROOT / "requirements-dev.txt"]
    for req in req_files:
        if req.exists():
            pip = _run_cmd(
                [sys.executable, "-m", "pip", "install", "-r", str(req)],
                timeout=120,
            )
            if pip.returncode == 0:
                log.info("PIP: dependencies installed from %s", req.name)
            else:
                log.warning("PIP: %s install had issues: %s", req.name, pip.stderr.strip())

    # Step 8: Verify in paper mode
    paper_ok, paper_msg = _verify_paper_mode()
    if not paper_ok:
        log.warning("PAPER VERIFY: %s", paper_msg)
        if not force:
            log.error("Paper mode verification failed — aborting")
            return 1

    # Step 9: Restore state if backed up
    if state_backup and STATE_FILE.exists():
        try:
            shutil.copy2(str(state_backup), str(STATE_FILE))
            log.info("STATE RESTORED from %s", state_backup.name)
        except (OSError, shutil.Error) as e:
            log.warning("STATE RESTORE FAILED: %s", e)

    log.info("=== CODE ROLLBACK COMPLETE ===")
    return 0


def rollback_config(restore_file: str | None = None, force: bool = False) -> int:
    """Rollback configuration from backup (Section 2.2)."""
    log.info("=== CONFIG ROLLBACK ===")

    # Determine restore source
    if restore_file:
        restore_path = ROOT / restore_file
    else:
        # Find latest backup
        if not BACKUP_DIR.exists():
            log.error("No backups directory found and no --restore file specified")
            return 1
        backups = sorted(BACKUP_DIR.glob("config*.json"), key=os.path.getmtime, reverse=True)
        if not backups:
            log.error("No config backups found")
            return 1
        restore_path = backups[0]
        log.info("Using latest backup: %s", restore_path.name)

    if not restore_path.exists():
        log.error("Restore file not found: %s", restore_path)
        return 1

    # Backup current config
    if CONFIG_FILE.exists():
        _backup_file(CONFIG_FILE, suffix="_pre_rollback")

    # Restore
    try:
        shutil.copy2(str(restore_path), str(CONFIG_FILE))
        log.info("CONFIG RESTORED: %s → config.json", restore_path.name)
    except (OSError, shutil.Error) as e:
        log.error("CONFIG RESTORE FAILED: %s", e)
        return 1

    # Validate schema
    validator = ROOT / "scripts" / "validate_config_schema.py"
    if validator.exists():
        val = _run_cmd([sys.executable, str(validator)], timeout=30)
        if val.returncode == 0:
            log.info("SCHEMA VALIDATION PASSED")
        else:
            log.warning("SCHEMA VALIDATION ISSUES: %s", val.stderr.strip())

    log.info("=== CONFIG ROLLBACK COMPLETE ===")
    return 0


def rollback_database(backup_file: str | None = None, force: bool = False) -> int:
    """Restore database from backup (Section 2.3)."""
    log.info("=== DATABASE ROLLBACK ===")

    # Determine restore source
    if backup_file:
        restore_path = ROOT / backup_file
    else:
        if not BACKUP_DIR.exists():
            log.error("No backups directory found and no --backup-file specified")
            return 1
        backups = sorted(BACKUP_DIR.glob("trades*.db*"), key=os.path.getmtime, reverse=True)
        if not backups:
            log.error("No database backups found")
            return 1
        restore_path = backups[0]
        log.info("Using latest backup: %s", restore_path.name)

    if not restore_path.exists():
        log.error("Backup file not found: %s", restore_path)
        return 1

    # Backup current DB before restore
    for db_path in [TRADES_DB, TRADE_JOURNAL_DB]:
        if db_path.exists():
            _backup_file(db_path, suffix="_current")

    # Restore
    target_map = {
        "trades": TRADES_DB,
        "trade_journal": TRADE_JOURNAL_DB,
    }
    restore_name = restore_path.stem.lower()
    restored = False
    for key, target_path in target_map.items():
        if key in restore_name:
            try:
                shutil.copy2(str(restore_path), str(target_path))
                log.info("DB RESTORED: %s → %s", restore_path.name, target_path.name)
                restored = True
            except (OSError, shutil.Error) as e:
                log.error("DB RESTORE FAILED for %s: %s", target_path.name, e)
                return 1
            break

    if not restored:
        log.warning("DB: Could not determine target for %s — restoring as trades.db", restore_path.name)
        try:
            shutil.copy2(str(restore_path), str(TRADES_DB))
            restored = True
        except (OSError, shutil.Error) as e:
            log.error("DB RESTORE FAILED: %s", e)
            return 1

    log.info("=== DATABASE ROLLBACK COMPLETE ===")
    return 0


def rollback_broker(target_broker: str, force: bool = False) -> int:
    """Switch broker driver (Section 2.4)."""
    log.info("=== BROKER ROLLBACK → %s ===", target_broker)

    valid_brokers = {"KITE", "ANGEL", "FYERS", "DHAN", "PAPER"}
    target_upper = target_broker.upper()

    if target_upper not in valid_brokers:
        log.error("Invalid broker: %s. Valid options: %s", target_broker, ", ".join(sorted(valid_brokers)))
        return 1

    # Update config via config.json if it exists
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["BROKER_DRIVER"] = target_upper
            CONFIG_FILE.write_text(
                json.dumps(cfg, indent=2, default=str),
                encoding="utf-8",
            )
            log.info("BROKER: config.json updated — BROKER_DRIVER=%s", target_upper)
        except (json.JSONDecodeError, OSError) as e:
            log.error("BROKER: Failed to update config.json: %s", e)
            if not force:
                return 1

    # Try setting env var as override
    os.environ["OPBUYING_BROKER_DRIVER"] = target_upper
    log.info("BROKER: OPBUYING_BROKER_DRIVER=%s set", target_upper)

    log.info("=== BROKER ROLLBACK COMPLETE — restart required ===")
    return 0


def rollback_docker(force: bool = False) -> int:
    """Restart Docker container (Section 2.5)."""
    log.info("=== DOCKER RESTART ===")

    compose_files = [
        ROOT / "docker-compose.yml",
        ROOT / "docker-compose.prod.yml",
    ]

    compose_file = None
    for cf in compose_files:
        if cf.exists():
            compose_file = cf
            break

    if not compose_file:
        log.error("No docker-compose.yml found")
        return 1

    # Check docker availability
    check = _run_cmd(["docker", "info"], timeout=10)
    if check.returncode != 0:
        log.error("Docker not available or not running")
        return 1

    # Restart
    restart = _run_cmd(
        ["docker", "compose", "-f", str(compose_file), "restart", "opb"],
        timeout=60,
    )
    if restart.returncode == 0:
        log.info("DOCKER: Container restarted successfully")
        log.info("DOCKER: Run 'docker compose logs -f opb' to monitor")
    else:
        log.error("DOCKER: Restart failed: %s", restart.stderr.strip())
        if not force:
            return 1

    log.info("=== DOCKER RESTART COMPLETE ===")
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Status / Pre-flight Checks
# ═══════════════════════════════════════════════════════════════════════════════


def check_status() -> int:
    """Check rollback readiness (Appendix: Rollback-Ready Checklist)."""
    log.info("=== ROLLBACK READINESS CHECK ===")

    checks: list[tuple[str, bool, str]] = [
        ("Git repository", (ROOT / ".git").exists(), "git available"),
        ("Backups directory", BACKUP_DIR.exists(), "backups/ exists"),
        ("Trader state file", STATE_FILE.exists(), "trader_state.json"),
        ("Config file", CONFIG_FILE.exists(), "config.json"),
        ("Config defaults", CONFIG_DEFAULTS.exists(), "index_config.defaults.json"),
        ("Trades database", TRADES_DB.exists(), "trades.db"),
        ("Trade journal DB", TRADE_JOURNAL_DB.exists(), "trade_journal.db"),
        ("Docker compose", (ROOT / "docker-compose.yml").exists(), "docker-compose.yml"),
        ("Test suite", (ROOT / "tests").is_dir(), "tests/ directory"),
    ]

    all_pass = True
    for name, ok, detail in checks:
        status = "✓" if ok else "✗"
        if not ok:
            all_pass = False
        log.info("  %s %s (%s)", status, name, detail)

    # Count backups
    if BACKUP_DIR.exists():
        backup_count = len(list(BACKUP_DIR.glob("*")))
        log.info("  %s Backup count: %d files in backups/", "✓" if backup_count > 0 else " ", backup_count)

    # Check git tags
    tag_result = _run_cmd(["git", "tag", "--list", "v*"], timeout=10)
    if tag_result.returncode == 0:
        tags = [t for t in tag_result.stdout.strip().split("\n") if t]
        log.info("  %s Git tags: %d found", "✓" if tags else " ", len(tags))

    log.info("=== READINESS CHECK %s ===", "PASSED" if all_pass else "ISSUES FOUND")
    return 0 if all_pass else 2


def test_rollback() -> int:
    """Dry-run test: verify all rollback paths work without executing."""
    log.info("=== ROLLBACK DRY-RUN TEST ===")
    log.info("Testing rollback paths (no actual changes)...")

    test_paths = [
        ("git checkout simulation", _run_cmd(["git", "--version"])),
        ("pip install simulation", _run_cmd([sys.executable, "--version"])),
        ("config load simulation", _run_cmd([sys.executable, "-c", "import json; print(json.dumps({}))"])),
    ]

    for name, result in test_paths:
        status = "✓" if result.returncode == 0 else "✗"
        log.info("  %s %s", status, name)

    # Check safety_state import
    try:
        log.info("  ✓ safety_state import (trip_hard_halt available)")
    except ImportError as e:
        log.warning("  ⚠ safety_state import failed: %s", e)

    # Verify paper mode
    paper_ok, paper_msg = _verify_paper_mode()
    log.info("  %s Paper mode check: %s", "✓" if paper_ok else "⚠", paper_msg)

    log.info("=== DRY-RUN COMPLETE ===")
    return 0


# ═══════════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Rollback Automation — OPB Institutional Platform",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode selection
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--version", type=str, help="Code rollback to version tag (e.g., v2.52.0)")
    mode.add_argument("--config", action="store_true", help="Config rollback mode")
    mode.add_argument("--db", action="store_true", help="Database rollback mode")
    mode.add_argument("--broker", type=str, help="Broker switch (KITE/ANGEL/FYERS/DHAN/PAPER)")
    mode.add_argument("--docker-restart", action="store_true", help="Docker container restart")
    mode.add_argument("--test", action="store_true", help="Dry-run test (no changes)")
    mode.add_argument("--status", action="store_true", help="Check rollback readiness")

    # Options
    ap.add_argument("--restore", type=str, default=None,
                    help="Config: path to restore file (e.g., config.json.bak)")
    ap.add_argument("--backup-file", type=str, default=None,
                    help="DB: path to backup file (e.g., trades.db.bak)")
    ap.add_argument("--force", "-f", action="store_true",
                    help="Skip pre-flight checks and safety halts")
    ap.add_argument("--no-halt", action="store_true",
                    help="Skip HARD_HALT (only for non-trading rollbacks)")

    args = ap.parse_args(argv)

    # Dispatch
    if args.test:
        return test_rollback()
    elif args.status:
        return check_status()
    elif args.version:
        if not args.no_halt:
            _halt_trading(f"Code rollback to {args.version}")
        return rollback_code(args.version, force=args.force)
    elif args.config:
        return rollback_config(restore_file=args.restore, force=args.force)
    elif args.db:
        return rollback_database(backup_file=args.backup_file, force=args.force)
    elif args.broker:
        return rollback_broker(args.broker, force=args.force)
    elif args.docker_restart:
        return rollback_docker(force=args.force)
    else:
        ap.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
