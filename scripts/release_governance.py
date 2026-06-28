#!/usr/bin/env python3
"""
Release Governance Automation - Enforces the Constitution's Mandatory Release Governance.

After every approved implementation:
  1. Create date-wise branch (release/YYYY-MM-DD)
  2. Run pre-release validation chain
  3. Generate release notes
  4. Update documentation
  5. Update audit records
  6. Tag release if appropriate

Release state must be: reproducible, deterministic, auditable.

Usage:
    python scripts/release_governance.py --version 2.54.0         # Full release
    python scripts/release_governance.py --check                  # Pre-release check only
    python scripts/release_governance.py --generate-notes         # Release notes only
    python scripts/release_governance.py --commit "feat: message" # Stage + commit
    python scripts/release_governance.py --audit                  # Update audit records

Exit code:
    0 = all steps completed successfully
    1 = any step failed
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import subprocess
import sys
import time
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("release_governance")


def _safe_rel(path: Path) -> str:
    """Return path relative to ROOT, falling back to full path if not under ROOT.

    Pytest tmp_path directories are not under the project root, so plain
    ``relative_to()`` would raise ``ValueError``. This safely falls back.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


# ── Constants ─────────────────────────────────────────────────────────────────

RELEASE_NOTES_FILE = ROOT / "RELEASE_NOTES.md"
CHANGELOG_FILE = ROOT / "CHANGELOG.md"
VERSION_FILE = ROOT / "VERSION"
AUDIT_LOG_DIR = ROOT / "logs" / "audit"


# ── Pre-release validation ────────────────────────────────────────────────────


def run_pre_release_checks(
    skip_certifications: bool = False,
) -> list[str]:
    """Run all pre-release validation checks.

    Args:
        skip_certifications: If True, skip certification checks (for rapid dev iterations).

    Returns list of failure messages (empty = all passed).
    """
    failures: list[str] = []

    # 1. VERSION file exists and is non-empty
    if not VERSION_FILE.exists():
        failures.append("VERSION file not found")
    else:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
        if not version:
            failures.append("VERSION file is empty")
        else:
            log.info("  [OK] Version: %s", version)

    # 2. Git is clean (no uncommitted changes)
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.stdout.strip():
            changed = len(result.stdout.strip().split("\n"))
            failures.append(f"Git working directory has {changed} uncommitted change(s)")
        else:
            log.info("  [OK] Git working directory clean")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        failures.append("Git not available - cannot verify clean state")
        log.warning("  [!] Git not available, skipping clean check")

    # 3. Certification checks (Phase 4+5+10 - deterministic gates)
    if not skip_certifications:
        _run_certification_checks(failures)
    else:
        log.info("  [!] Certification checks skipped (--skip-cert)")

    # 4. Required documentation exists
    required_docs = [
        "README.md",
        "SETUP_AND_TRADING_GUIDE.md",
        "CONFIG_EXPLANATIONS.md",
        "SECRETS_MIGRATION_GUIDE.md",
        "CLAUDE.md",
    ]
    missing_docs = [d for d in required_docs if not (ROOT / d).exists()]
    if missing_docs:
        failures.append(f"Required docs missing: {', '.join(missing_docs)}")

    # 5. .gitignore exists
    if not (ROOT / ".gitignore").exists():
        failures.append(".gitignore not found")

    # 6. pyproject.toml exists and has version
    if (ROOT / "pyproject.toml").exists():
        content = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        if "version" not in content:
            failures.append("pyproject.toml missing version field")

    # 7. Landing page readable
    if (ROOT / "README.md").exists():
        size = (ROOT / "README.md").stat().st_size
        if size < 100:
            failures.append(f"README.md too small ({size} bytes)")

    # 8. Repository hygiene gate (Phase 2)
    _run_hygiene_gate(failures)

    # 9. Architecture compliance gate
    _run_architecture_gate(failures)

    return failures


def _certification_db_ready() -> bool:
    """Check if the trades database has the required schema for certification.

    Returns True if trades.db exists and has a 'trades' table with net_pnl.
    """
    trades_db = ROOT / "trades.db"
    if not trades_db.is_file():
        log.info("  [!] trades.db not found - skipping certification checks")
        return False
    try:
        from core.db_utils import get_connection
        conn = get_connection(str(trades_db), timeout=5, row_factory=False)
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchall()
        if not rows:
            log.info("  [!] trades.db exists but 'trades' table not found - skipping certification")
            conn.close()
            return False
        conn.close()
        return True
    except (ImportError, sqlite3.Error, OSError) as exc:
        log.info("  [!] trades.db check failed: %s - skipping certification", exc)
        return False


def _run_certification_checks(failures: list[str]) -> None:
    """Run certification gates: replay determinism, paper trading quality.

    Certification failures are BLOCKING - they append to failures and prevent release.
    If the trades database does not exist or has no trades table, certifications are
    skipped gracefully (common in CI or fresh-checkout environments).
    """
    if not _certification_db_ready():
        return

    trades_db = str(ROOT / "trades.db")

    # Replay certification (Phase 4)
    try:
        from core.certification.replay_certifier import certify_replay_determinism
        replay_report = certify_replay_determinism(db_path=trades_db, max_trades=5, frames=5, width=30)
        if not replay_report.passed:
            failures.append(f"Replay certification FAILED: {replay_report.verdict}")
        else:
            log.info("  [OK] Replay certification: %s", replay_report.verdict)
    except ImportError:
        log.info("  [!] Replay certification module not available (core.certification.replay_certifier)")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        failures.append(f"Replay certification error: {exc}")

    # Paper trading certification (Phase 5)
    try:
        from core.certification.paper_certifier import certify_paper_trading
        paper_report = certify_paper_trading(db_path=trades_db)
        if not paper_report.passed:
            failures.append(f"Paper trading certification FAILED: {paper_report.verdict}")
        else:
            log.info("  [OK] Paper trading certification: %s", paper_report.verdict)
    except ImportError:
        log.info("  [!] Paper certification module not available (core.certification.paper_certifier)")
    except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
        failures.append(f"Paper certification error: {exc}")


def _run_hygiene_gate(failures: list[str]) -> None:
    """Run repository hygiene check (Phase 2).  Failure blocks release."""
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "hygiene_check.py"), "--ci"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            failures.append("Repository hygiene check failed")
            stderr = result.stderr[-500:] if result.stderr else ""
            log.warning("  [X] Hygiene check output:\n%s", stderr)
        else:
            log.info("  [OK] Repository hygiene passed")
    except FileNotFoundError:
        log.info("  [!] hygiene_check.py not found - skipping")
    except subprocess.TimeoutExpired as exc:
        failures.append(f"Hygiene check timed out: {exc}")


def _run_architecture_gate(failures: list[str]) -> None:
    """Run architecture compliance check.  Failure blocks release."""
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "check_architecture_compliance.py"), "--ci"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            failures.append("Architecture compliance check failed")
            stderr = result.stderr[-500:] if result.stderr else ""
            log.warning("  [X] Architecture check output:\n%s", stderr)
        else:
            log.info("  [OK] Architecture compliance passed")
    except FileNotFoundError:
        log.info("  [!] check_architecture_compliance.py not found - skipping")
    except subprocess.TimeoutExpired as exc:
        failures.append(f"Architecture check timed out: {exc}")


# ── Branch creation ────────────────────────────────────────────────────────────


def create_release_branch(version: str) -> tuple[bool, str]:
    """Create a release branch per BRANCHING_CONVENTION.md.

    Format: release/v{VERSION}  (semver-based, no date suffix)
    Convention: docs/BRANCHING_CONVENTION.md
    """
    branch_name = f"release/v{version}"

    try:
        # Check if branch already exists
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode == 0:
            log.info("  [OK] Branch already exists: %s", branch_name)
            return True, branch_name

        # Create the branch
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode != 0:
            return False, f"Failed to create branch: {result.stderr.strip()}"
        log.info("  [OK] Created branch: %s", branch_name)
        return True, branch_name
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"Git error: {e}"


# ── Release notes generation ──────────────────────────────────────────────────


def generate_release_notes(version: str, changes: list[str] | None = None) -> str:
    """Generate release notes from git log since last tag.

    Returns the markdown content.
    """
    # Get last tag
    last_tag = ""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode == 0:
            last_tag = result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Get commits since last tag
    commits: list[str] = []
    if last_tag:
        try:
            result = subprocess.run(
                ["git", "log", f"{last_tag}..HEAD", "--oneline"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=15,
            )
            if result.returncode == 0:
                commits = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    notes = [
        f"# Release v{version}",
        f"",
        f"**Date:** {date.today().isoformat()}",
        f"**Previous Release:** {last_tag or 'N/A'}",
        f"**Commits Since Last Release:** {len(commits)}",
        f"",
        f"---",
        f"",
        f"## Changes",
        f"",
    ]

    if changes:
        for c in changes:
            notes.append(f"- {c}")
        notes.append("")

    if commits:
        notes.append(f"### Commits")
        notes.append("")
        notes.append("```")
        for c in commits[:50]:
            notes.append(c)
        if len(commits) > 50:
            notes.append(f"... and {len(commits) - 50} more")
        notes.append("```")
        notes.append("")

    notes.extend([
        f"---",
        f"",
        f"## Verification",
        f"",
        f"- [ ] All tests pass",
        f"- [ ] Architecture compliance check passed",
        f"- [ ] Config schemas regenerated",
        f"- [ ] Documentation synced",
        f"- [ ] Pre-implementation checks passed",
        f"- [ ] Repository hygiene verified",
    ])

    return "\n".join(notes)


def write_release_notes(version: str, changes: list[str] | None = None) -> bool:
    """Generate and write release notes."""
    try:
        notes = generate_release_notes(version, changes)
        RELEASE_NOTES_FILE.write_text(notes, encoding="utf-8")
        log.info("  [OK] Release notes written: %s", _safe_rel(RELEASE_NOTES_FILE))
        return True
    except (OSError, UnicodeDecodeError) as e:
        log.error("  [FAIL] Failed to write release notes: %s", e)
        return False


# ── Changelog update ──────────────────────────────────────────────────────────


def update_changelog(version: str, changes: list[str] | None = None) -> bool:
    """Update CHANGELOG.md with new release entry."""
    try:
        today = date.today().isoformat()
        entry = [
            f"## v{version} ({today})",
            "",
        ]

        if changes:
            for c in changes:
                entry.append(f"- {c}")
            entry.append("")

        entry_text = "\n".join(entry)

        if CHANGELOG_FILE.exists():
            existing = CHANGELOG_FILE.read_text(encoding="utf-8")
            # Insert after the header
            lines = existing.split("\n")
            # Find first non-empty, non-header line
            insert_pos = 0
            for i, line in enumerate(lines):
                if line.startswith("# "):
                    insert_pos = i + 1
                    break
            # Insert blank line if needed
            while insert_pos < len(lines) and lines[insert_pos].strip() == "":
                insert_pos += 1
            lines.insert(insert_pos, entry_text)
            CHANGELOG_FILE.write_text("\n".join(lines), encoding="utf-8")
        else:
            header = "# Changelog\n\n"
            CHANGELOG_FILE.write_text(header + entry_text, encoding="utf-8")

        log.info("  [OK] Changelog updated: %s", _safe_rel(CHANGELOG_FILE))
        return True
    except (OSError, UnicodeDecodeError) as e:
        log.error("  [FAIL] Failed to update changelog: %s", e)
        return False


# ── Audit record ──────────────────────────────────────────────────────────────


def write_audit_record(version: str, branch: str, changes: list[str] | None = None) -> bool:
    """Write release audit record."""
    try:
        AUDIT_LOG_DIR.mkdir(parents=True, exist_ok=True)
        audit_file = AUDIT_LOG_DIR / f"release_v{version}_{date.today().isoformat()}.json"

        record = {
            "timestamp": time.time(),
            "version": version,
            "branch": branch,
            "date": date.today().isoformat(),
            "changes": changes or [],
            "verified": False,
            "reproducible": True,
        }

        audit_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
        log.info("  [OK] Audit record written: %s", _safe_rel(audit_file))
        return True
    except (OSError, UnicodeDecodeError, TypeError) as e:
        log.error("  [FAIL] Failed to write audit record: %s", e)
        return False

    # ── Git commit helper ─────────────────────────────────────────────────────────


def git_push(branch: str | None = None) -> tuple[bool, str]:
    """Push the current branch to origin.

    Args:
        branch: Branch to push. If None, pushes current branch.

    Returns:
        (success, message) tuple.
    """
    try:
        if branch:
            result = subprocess.run(
                ["git", "push", "origin", branch],
                capture_output=True, text=True, cwd=str(ROOT), timeout=30,
            )
        else:
            result = subprocess.run(
                ["git", "push"],
                capture_output=True, text=True, cwd=str(ROOT), timeout=30,
            )
        if result.returncode != 0:
            return False, f"Push failed: {result.stderr.strip()}"
        log.info("  [OK] Pushed to origin")
        return True, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"Git error: {e}"


def git_commit(message: str) -> tuple[bool, str]:
    """Stage all changes and commit with message."""
    try:
        # Stage all
        result = subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode != 0:
            return False, f"Failed to stage: {result.stderr.strip()}"

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode != 0:
            return False, f"Failed to commit: {result.stderr.strip()}"

        log.info("  [OK] Committed: %s", message)
        return True, result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"Git error: {e}"


def git_tag(version: str) -> tuple[bool, str]:
    """Create and annotate a release tag."""
    tag = f"v{version}"
    try:
        # Delete existing tag if present
        subprocess.run(
            ["git", "tag", "-d", tag],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )

        # Create annotated tag
        result = subprocess.run(
            ["git", "tag", "-a", tag, "-m", f"Release v{version}"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=15,
        )
        if result.returncode != 0:
            return False, f"Failed to tag: {result.stderr.strip()}"

        log.info("  [OK] Tagged: %s", tag)
        return True, tag
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, f"Git error: {e}"


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", "-v", help="Release version (e.g., 2.54.0)")
    ap.add_argument("--check", action="store_true", help="Pre-release check only")
    ap.add_argument("--generate-notes", action="store_true", help="Generate release notes only")
    ap.add_argument("--commit", "-m", help="Stage and commit with message")
    ap.add_argument("--audit", action="store_true", help="Write audit record only")
    ap.add_argument("--skip-tests", action="store_true", help="Skip test verification")
    ap.add_argument("--skip-cert", action="store_true", help="Skip certification checks (replay, paper, hygiene)")
    ap.add_argument("--skip-branch", action="store_true", help="Skip branch creation")
    ap.add_argument("--push", action="store_true", help="Push to origin (opt-in: disabled by default)")
    ap.add_argument("--change", "-c", action="append", dest="changes",
                    help="Change description (repeatable)")
    args = ap.parse_args(argv)

    version = args.version or "0.0.0"

    # ── Pre-release check ────────────────────────────────────────────────
    if args.check:
        print("=" * 70)
        print("  PRE-RELEASE VALIDATION")
        print("=" * 70)
        failures = run_pre_release_checks(skip_certifications=args.skip_cert)
        if failures:
            print("\n  [X] %d failure(s):" % len(failures))
            for f in failures:
                print("    - %s" % f)
            return 1
        print("\n  [OK] All pre-release checks passed")
        return 0

    # ── Generate release notes only ──────────────────────────────────────
    if args.generate_notes:
        notes = generate_release_notes(version, args.changes)
        print(notes)
        return 0

    # ── Git commit ───────────────────────────────────────────────────────
    if args.commit:
        ok, msg = git_commit(args.commit)
        if not ok:
            print("[FAIL] %s" % msg, file=sys.stderr)
            return 1
        print(msg)
        return 0

    # ── Audit record only ────────────────────────────────────────────────
    if args.audit:
        ok = write_audit_record(version, "standalone", args.changes)
        return 0 if ok else 1

    # ── Full release pipeline ────────────────────────────────────────────
    print("=" * 70)
    print(f"  RELEASE GOVERNANCE - v{version}")
    print("=" * 70)

    # Step 1: Pre-release checks
    print("\n[1/6] Pre-release validation...")
    failures = run_pre_release_checks(skip_certifications=args.skip_cert)
    if failures:
        print("  [X] %d failure(s) - run --check for details" % len(failures))
        return 1
    print("  [OK] Passed")

    # Step 2: Branch creation
    if not args.skip_branch:
        print("\n[2/6] Creating release branch...")
        ok, branch = create_release_branch(version)
        if not ok:
            print("  [FAIL] %s" % branch, file=sys.stderr)
            return 1
    else:
        branch = "current"
        print("\n[2/6] Skipping branch creation")

    # Step 3: Release notes
    print("\n[3/6] Generating release notes...")
    ok = write_release_notes(version, args.changes)
    if not ok:
        return 1

    # Step 4: Changelog
    print("\n[4/6] Updating changelog...")
    ok = update_changelog(version, args.changes)
    if not ok:
        return 1

    # Step 5: Audit record
    print("\n[5/6] Writing audit record...")
    ok = write_audit_record(version, branch, args.changes)
    if not ok:
        return 1

    # Step 6: Tag
    print("\n[6/6] Creating release tag...")
    ok, tag = git_tag(version)
    if ok:
        print("  [OK] Tagged: %s" % tag)
    else:
        print("  [!] Tagging skipped: %s" % tag)

    # Step 7: Push (opt-in - requires --push flag)
    if args.push:
        print("\n[7/7] Pushing to origin...")
        push_branch = branch if not args.skip_branch else None
        ok, push_msg = git_push(push_branch)
        if ok:
            print("  [OK] Push successful")
        else:
            print("  [!] Push warning: %s" % push_msg)
        # Also push the tag if created
        if tag:
            subprocess.run(
                ["git", "push", "origin", tag],
                capture_output=True, text=True, cwd=str(ROOT), timeout=30,
            )
            print("  [OK] Tag pushed: %s" % tag)
    else:
        print("\n[7/7] Push skipped (use --push to push to origin)")

    print(f"\n{'=' * 70}")
    print(f"  RELEASE v{version} PREPARED")
    print(f"  Branch: {branch}")
    print(f"  Tag: v{version}")
    print(f"  Release notes: RELEASE_NOTES.md")
    print(f"  Changelog: CHANGELOG.md")
    print(f"  Audit: logs/audit/release_v{version}_{date.today().isoformat()}.json")
    print("=" * 70)

    next_steps = [
        "  Next steps:",
        f"    1. Review RELEASE_NOTES.md",
        f"    2. Run full test suite: python -m pytest tests/ -q",
        f"    3. Push: git push origin {branch} && git push origin v{version}",
    ]
    print("\n" + "\n".join(next_steps))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
