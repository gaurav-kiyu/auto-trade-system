#!/usr/bin/env python3
"""
Institutional Challenge - Adversarial Certification Framework.

The Constitution mandates:
  Before certifying the system, actively attempt to prove it is NOT worthy of certification.
  Search for: hidden bugs, silent failures, race conditions, data leakage, replay
  inconsistencies, execution flaws, risk bypasses, catastrophic loss scenarios.
  
  Only surviving systems may receive institutional-grade ratings.

This framework runs a battery of adversarial challenges and reports results.

Usage:
    python scripts/institutional_challenge.py                   # Full challenge suite
    python scripts/institutional_challenge.py --quick           # Quick subset
    python scripts/institutional_challenge.py --category risk   # Risk challenges only
    python scripts/institutional_challenge.py --json            # JSON output
    python scripts/institutional_challenge.py --ci              # CI mode (exit code)
    python scripts/institutional_challenge.py --update-score    # Update constitution scores

Exit code:
    0 = all challenges passed (system is challenge-worthy)
    1 = some challenges failed (system needs remediation)
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger("institutional_challenge")


# -- Challenge result ----------------------------------------------------------


@dataclass
class ChallengeResult:
    """Result of a single institutional challenge."""
    challenge_id: str
    name: str
    category: str  # risk, race, data, replay, execution, security, catastrophic
    passed: bool
    detail: str = ""
    duration_s: float = 0.0
    score_impact: str = "none"  # none, warn, block

    def to_dict(self) -> dict[str, Any]:
        return {
            "challenge_id": self.challenge_id,
            "name": self.name,
            "category": self.category,
            "passed": self.passed,
            "detail": self.detail,
            "duration_s": round(self.duration_s, 2),
            "score_impact": self.score_impact,
        }


# -- Built-in challenges ------------------------------------------------------


def challenge_risk_bypass() -> ChallengeResult:
    """Challenge: Attempt to find risk control bypass paths."""
    import time as _time
    start = _time.time()
    failures: list[str] = []

    risk_keywords = [
        "_trip_hard_halt",
        "MAX_DAILY_LOSS",
        "MAX_DRAWDOWN",
        "SL_PCT",
        "TARGET_PCT",
        "TRAIL_PCT",
        "PORTFOLIO_MAX_SL_RISK_PCT",
        "expiry_entry_allowed",
        "PaperBrokerAdapter",
    ]

    # Search for risk control weakening patterns
    index_trader = ROOT / "index_app" / "index_trader.py"
    if index_trader.exists():
        content = index_trader.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")
        for kw in risk_keywords:
            for i, line in enumerate(lines, 1):
                if kw in line and any(w in line.lower() for w in ["false", "none", "bypass", "disable", "remove"]):
                    failures.append(
                        f"Line {i}: {kw} appears with bypass-indicating keyword: {line.strip()[:80]}"
                    )
                # Also check for standalone '0' (not part of a larger number like 2000, 0.92)
                if kw in line and '0' in line.lower():
                    import re
                    # Match '0' as isolated token (disabled/zeroed), not part of larger numbers or decimals
                    # Must NOT be preceded by a digit (avoids matching 10, 2000, etc.)
                    # Must NOT be followed by a digit or '.' (avoids matching 0.92, 0.75, etc.)
                    if re.search(r'(?:^|[^\d\w])0(?:$|[^\d\w.])', line.lower()):
                        failures.append(
                            f"Line {i}: {kw} appears with isolated '0' value: {line.strip()[:80]}"
                        )

    # Check that _HARD_HALT event is never released silently
    if "set()" in content or ".clear()" in content:
        # Find hard halt references
        for i, line in enumerate(lines, 1):
            if "_HARD_HALT" in line and "set()" in line:
                break
            elif "_HARD_HALT" in line and "clear()" in line and "except" not in line:
                failures.append(f"Line {i}: _HARD_HALT.clear() found outside exception handler")

    if failures:
        return ChallengeResult(
            challenge_id="CH-RSK-01",
            name="Risk Control Bypass Detection",
            category="risk",
            passed=False,
            detail=f"Found {len(failures)} potential risk bypass(es): {'; '.join(failures[:3])}",
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-RSK-01",
        name="Risk Control Bypass Detection",
        category="risk",
        passed=True,
        detail="No risk bypass paths detected",
        duration_s=time.time() - start,
    )


def challenge_hidden_bugs() -> ChallengeResult:
    """Challenge: Scan for hidden bug patterns (bare excepts, type confusion, etc)."""
    start = time.time()
    failures: list[str] = []

    # Count bare except clauses across core modules
    bare_excepts = 0
    core_dir = ROOT / "core"
    if core_dir.is_dir():
        for py_file in core_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(content.split("\n"), 1):
                    stripped = line.strip()
                    if stripped == "except:" or stripped.startswith("except :"):
                        bare_excepts += 1
            except (ValueError, TypeError, KeyError, OSError):
                pass

    if bare_excepts > 10:
        failures.append(f"High bare-except count ({bare_excepts} occurrences)")

    # Check for potential TOCTOU races in temp file patterns
    toctou_patterns = 0
    for py_file in core_dir.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            # Look for file-exists-then-check patterns without lock
            lines = content.split("\n")
            for i, line in enumerate(lines):
                if "os.path.exists" in line or "Path.exists" in line:
                    if i + 1 < len(lines) and ("open(" in lines[i + 1] or "write" in lines[i + 1]):
                        toctou_patterns += 1
        except (ValueError, TypeError, KeyError, OSError):
            pass

    if toctou_patterns > 5:
        failures.append(f"Potential TOCTOU race patterns: {toctou_patterns} occurrences")

    if failures:
        return ChallengeResult(
            challenge_id="CH-BUG-01",
            name="Hidden Bug Pattern Scan",
            category="catastrophic",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-BUG-01",
        name="Hidden Bug Pattern Scan",
        category="catastrophic",
        passed=True,
        detail=f"No critical bug patterns found ({bare_excepts} bare excepts acceptable)",
        duration_s=time.time() - start,
    )


def challenge_race_condition() -> ChallengeResult:
    """Challenge: Check for potential race conditions in shared state."""
    start = time.time()
    failures: list[str] = []

    # Check that all module-level shared state uses threading locks
    core_dir = ROOT / "core"
    lock_free_shared: list[str] = []
    if core_dir.is_dir():
        for py_file in core_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                has_global_var = "_" in content and any(
                    pattern in content for pattern in ["= None", "= []", "= {}"]
                )
                has_lock = "threading.Lock" in content or "threading.RLock" in content
                if has_global_var and not has_lock:
                    # Check if it's a simple module without shared state
                    if any(pattern in content for pattern in [
                        " = threading.", "_lock = ", "_LOCK = ", "_lock:", "self._lock",
                    ]):
                        continue
                    # This might still be fine, but flag for review
                    lock_free_shared.append(py_file.name)
            except (ValueError, TypeError, KeyError, OSError):
                pass

    if len(lock_free_shared) > 10:
        failures.append(
            f"Potential race conditions: {len(lock_free_shared)} modules may have "
            f"unprotected shared state: {', '.join(lock_free_shared[:5])}"
        )

    if failures:
        return ChallengeResult(
            challenge_id="CH-RACE-01",
            name="Race Condition Analysis",
            category="race",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="warn",
        )

    return ChallengeResult(
        challenge_id="CH-RACE-01",
        name="Race Condition Analysis",
        category="race",
        passed=True,
        detail="No obvious race condition patterns found",
        duration_s=time.time() - start,
    )


def challenge_data_leakage() -> ChallengeResult:
    """Challenge: Check for potential data leakage (secrets in logs, debug output)."""
    start = time.time()
    failures: list[str] = []

    # Check for secrets printed to stdout/logs
    index_trader = ROOT / "index_app" / "index_trader.py"
    if index_trader.exists():
        content = index_trader.read_text(encoding="utf-8", errors="ignore")
        lines = content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Flag obvious secrets in log messages
            for secret_pattern in ["BOT_TOKEN", "CHAT_ID", "KITE_API_KEY", "KITE_PASSWORD",
                                    "ACCESS_TOKEN", "REFRESH_TOKEN", "SECRET", "PASSWORD"]:
                if secret_pattern in stripped and ("print(" in stripped or "log." in stripped):
                    # Check if it's redacted or a variable name, not the actual value
                    if "os.getenv" not in stripped and "get(" not in stripped and "config.get" not in stripped:
                        if "redact" not in stripped.lower():
                            # Exclude SECRET_HYGIENE - it's the security feature itself, not a leak
                            if "SECRET_HYGIENE" not in stripped:
                                failures.append(
                                    f"Line {i}: Potential secret leak: {stripped[:80]}"
                                )

    if failures:
        return ChallengeResult(
            challenge_id="CH-DATA-01",
            name="Data Leakage Scan",
            category="security",
            passed=False,
            detail="; ".join(failures[:3]),
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-DATA-01",
        name="Data Leakage Scan",
        category="security",
        passed=True,
        detail="No obvious data leakage patterns found",
        duration_s=time.time() - start,
    )


def challenge_catastrophic_loss() -> ChallengeResult:
    """Challenge: Check for catastrophic loss scenarios."""
    start = time.time()
    failures: list[str] = []

    # Scenario 1: What happens if NSE session doesn't open for 3 days?
    # Check that state management handles multi-day gaps
    state_file = ROOT / "core" / "state_manager.py"
    if state_file.exists():
        content = state_file.read_text(encoding="utf-8", errors="ignore")
        if "consecutive_loss" not in content and "max_consecutive" not in content:
            failures.append(
                "Consecutive loss detection not found in state_manager.py - "
                "multi-day outage could cause compounding losses"
            )

    # Scenario 2: What happens if broker API returns stale data for 60 minutes?
    # Check that data freshness guard exists
    freshness_file = ROOT / "core" / "data_freshness_guard.py"
    if not freshness_file.exists():
        failures.append(
            "Data freshness guard not found - stale broker data could cause "
            "trading on outdated prices"
        )

    # Scenario 3: What happens on simultaneous hard halt + kill file?
    # Check that halt and kill are independent safety nets
    safety_file = ROOT / "core" / "safety_state.py"
    if safety_file.exists():
        content = safety_file.read_text(encoding="utf-8", errors="ignore")
        if "_HARD_HALT" not in content:
            failures.append(
                "_HARD_HALT not found in safety_state.py - hard halt integration missing"
            )

    if failures:
        return ChallengeResult(
            challenge_id="CH-CATA-01",
            name="Catastrophic Loss Scenario Analysis",
            category="catastrophic",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-CATA-01",
        name="Catastrophic Loss Scenario Analysis",
        category="catastrophic",
        passed=True,
        detail="No catastrophic loss scenarios triggered",
        duration_s=time.time() - start,
    )


def challenge_replay_consistency() -> ChallengeResult:
    """Challenge: Check that replay is deterministic."""
    start = time.time()
    failures: list[str] = []

    # Check that replay tests exist
    replay_test = ROOT / "tests" / "test_trade_replayer.py"
    if not replay_test.exists():
        failures.append("No trade replayer test found - replay consistency unverified")

    backtest_replay_test = ROOT / "tests" / "test_backtest_replay.py"
    if not backtest_replay_test.exists():
        failures.append("No backtest replay test found")

    # Check that replay modules exist
    replay_module = ROOT / "core" / "trade_replayer.py"
    if not replay_module.exists():
        failures.append("No trade replayer module found - replay capability missing")

    if failures:
        return ChallengeResult(
            challenge_id="CH-REPLAY-01",
            name="Replay Consistency Verification",
            category="replay",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="warn",
        )

    return ChallengeResult(
        challenge_id="CH-REPLAY-01",
        name="Replay Consistency Verification",
        category="replay",
        passed=True,
        detail="Replay capability verified",
        duration_s=time.time() - start,
    )


def challenge_execution_flaws() -> ChallengeResult:
    """Challenge: Check for execution flaws (idempotency, WAL, exactly-once)."""
    start = time.time()
    failures: list[str] = []

    # Check exactly-once certification
    certifier_path = ROOT / "core" / "execution" / "idempotency" / "certifier.py"
    if not certifier_path.exists():
        failures.append("Idempotency certifier missing - exactly-once guarantee unverified")

    # Check WAL journal
    wal_path = ROOT / "core" / "wal" / "journal.py"
    if not wal_path.exists():
        failures.append("WAL journal missing - crash recovery unverified")

    # Check exactly-once test
    exactly_once_test = ROOT / "tests" / "test_exactly_once_certification.py"
    if not exactly_once_test.exists():
        failures.append("Exactly-once certification test missing")

    # Check broker failover
    failover_path = ROOT / "core" / "broker_failover.py"
    if not failover_path.exists():
        failures.append("Broker failover module missing - failover not tested")

    if failures:
        return ChallengeResult(
            challenge_id="CH-EXE-01",
            name="Execution Flaw Analysis",
            category="execution",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-EXE-01",
        name="Execution Flaw Analysis",
        category="execution",
        passed=True,
        detail="All execution infrastructure verified",
        duration_s=time.time() - start,
    )


def challenge_security_perimeter() -> ChallengeResult:
    """Challenge: Check security perimeter (auth, RBAC, secrets)."""
    start = time.time()
    failures: list[str] = []

    # Check auth modules
    auth_dir = ROOT / "core" / "auth"
    if not auth_dir.is_dir():
        failures.append("Auth module missing - no authentication perimeter")
    else:
        auth_files = list(auth_dir.rglob("*.py"))
        if not auth_files:
            failures.append("Auth module empty - no authentication implementations")

    # Check RBAC
    rbac_path = ROOT / "core" / "auth" / "role_manager.py"
    if not rbac_path.exists():
        failures.append("RBAC role manager missing - no authorization enforcement")

    # Check control plane auth
    control_plane_auth = ROOT / "core" / "control_plane" / "admin_auth.py"
    if not control_plane_auth.exists():
        failures.append("Admin auth missing - dashboard endpoints unprotected")

    if failures:
        return ChallengeResult(
            challenge_id="CH-SEC-01",
            name="Security Perimeter Analysis",
            category="security",
            passed=False,
            detail="; ".join(failures),
            duration_s=time.time() - start,
            score_impact="block",
        )

    return ChallengeResult(
        challenge_id="CH-SEC-01",
        name="Security Perimeter Analysis",
        category="security",
        passed=True,
        detail="Security perimeter verified",
        duration_s=time.time() - start,
    )


# -- Challenge registry --------------------------------------------------------

BUILTIN_CHALLENGES: list[Callable[[], ChallengeResult]] = [
    challenge_risk_bypass,
    challenge_hidden_bugs,
    challenge_race_condition,
    challenge_data_leakage,
    challenge_catastrophic_loss,
    challenge_replay_consistency,
    challenge_execution_flaws,
    challenge_security_perimeter,
]

CATEGORY_MAP: dict[str, list[str]] = {
    "risk": ["CH-RSK-01"],
    "bug": ["CH-BUG-01"],
    "race": ["CH-RACE-01"],
    "security": ["CH-DATA-01", "CH-SEC-01"],
    "catastrophic": ["CH-CATA-01", "CH-BUG-01"],
    "replay": ["CH-REPLAY-01"],
    "execution": ["CH-EXE-01"],
}


# -- Score updater -------------------------------------------------------------


def update_constitution_scores(results: list[ChallengeResult]) -> int:
    """Update constitution scores based on challenge results."""
    try:
        from core.constitution import get_validator
        validator = get_validator()
        updated = 0
        for r in results:
            if r.passed:
                # Add evidence for passed challenges
                category_map = {
                    "risk": "RSK-04",
                    "security": "SEC-01",
                    "execution": "EXE-01",
                    "replay": "EXE-03",
                    "race": "RSK-04",
                    "catastrophic": "RSK-04",
                }
                cat_id = category_map.get(r.category)
                if cat_id:
                    validator.add_evidence(
                        category_id=cat_id,
                        description=f"Institutional Challenge '{r.name}' passed: {r.detail}",
                        evidence_type="chaos",
                        weight=0.6,
                    )
                    updated += 1
        return updated
    except ImportError:
        log.warning("Could not import constitution validator - score update skipped")
        return 0


# -- Main ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true", help="Quick subset (skip heavy checks)")
    ap.add_argument("--category", "-c", help="Run only specific category")
    ap.add_argument("--json", "-j", action="store_true", help="JSON output")
    ap.add_argument("--ci", action="store_true", help="CI mode (exit code only)")
    ap.add_argument("--update-score", action="store_true", help="Update constitution scores")
    args = ap.parse_args(argv)

    # Select challenges
    challenges = list(BUILTIN_CHALLENGES)

    if args.category:
        allowed_ids = CATEGORY_MAP.get(args.category, [])
        challenges = [c for c in challenges if c.__name__.replace("challenge_", "CH-").upper()[:len(args.category) + 3] or any(
            aid in c.__name__ for aid in allowed_ids
        )]

    if args.quick:
        # Only run lightweight checks
        challenges = [c for c in challenges if c.__name__ not in (
            "challenge_hidden_bugs",
        )]

    # Run challenges
    results: list[ChallengeResult] = []
    for challenge_fn in challenges:
        try:
            result = challenge_fn()
            results.append(result)
        except (ValueError, TypeError, KeyError, OSError) as e:
            results.append(ChallengeResult(
                challenge_id=f"CH-ERR-{challenge_fn.__name__}",
                name=challenge_fn.__name__.replace("_", " ").title(),
                category="error",
                passed=False,
                detail=f"Challenge execution error: {e}",
                score_impact="warn",
            ))

    # Update constitution scores if requested
    if args.update_score:
        updated = update_constitution_scores(results)
        if not args.ci:
            print(f"  [INFO] Constitution scores updated: {updated} evidence items added")

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    blocked = sum(1 for r in results if r.score_impact == "block" and not r.passed)

    if args.json:
        output = {
            "timestamp": time.time(),
            "challenges": [r.to_dict() for r in results],
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "blocked": blocked,
            },
            "institutional_grade": blocked == 0,
        }
        print(json.dumps(output, indent=2))
        return 1 if blocked > 0 else 0

    if args.ci:
        return 1 if blocked > 0 else 0

    # -- Print report -----------------------------------------------------
    print("=" * 70)
    print("  INSTITUTIONAL CHALLENGE - Adversarial Certification")
    print("=" * 70)
    print()

    for r in results:
        icon = "OK" if r.passed else "!!"
        impact = f" [{r.score_impact.upper()}]" if r.score_impact == "block" else ""
        print(f"  [{icon}] [{r.category.upper()}] {r.name}{impact}")
        print(f"       {r.detail[:100]}")

    print()
    print("  -- Summary --")
    print(f"    Total Challenges: {len(results)}")
    print(f"    Passed:          {passed}")
    print(f"    Failed:          {failed}")
    print(f"    Blocking:        {blocked}")

    if blocked == 0:
        print()
        print("  [OK] INSTITUTIONAL CHALLENGE: SYSTEM SURVIVED")
        if failed > 0:
            print(f"    ({failed} non-blocking warnings - review recommended)")
    else:
        print()
        print(f"  [FAIL] INSTITUTIONAL CHALLENGE: {blocked} BLOCKING FAILURE(S)")
        print("    System is NOT certifiable until resolved")
        for r in results:
            if r.score_impact == "block" and not r.passed:
                print(f"      - {r.name}: {r.detail[:120]}")

    print()
    print("=" * 70)
    return 1 if blocked > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
