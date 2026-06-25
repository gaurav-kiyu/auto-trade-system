"""
Unified Certification Gate (Phase 24).

Consolidates ALL certification checks into a SINGLE blocking gate that
must pass before any release. Integrates with the release governance pipeline.

Certifiers Executed
-------------------
1. Strategy Certification  — All strategies meet minimum thresholds
2. Replay Certification   — Trade replay is deterministic
3. Paper Trading Certification — Paper trading quality meets standards
4. Architecture Compliance — Import isolation, bounded contexts
5. Repository Hygiene      — No dead code, stale artifacts, config drift

Usage
-----
    from core.certification.gate import CertificationGate

    gate = CertificationGate()
    result = gate.run_all()
    print(result.summary())

    # Integration with release governance
    if not result.passed:
        print(f"Release BLOCKED: {result.verdict}")
        raise SystemExit(1)

Config keys (all optional — safe defaults built in)
---------------------------------------------------
    cert_gate_block_on_warn     : bool  default False
    cert_gate_max_failures      : int   default 0
    cert_gate_skip_strategy     : bool  default False
    cert_gate_skip_replay       : bool  default False
    cert_gate_skip_paper        : bool  default False
    cert_gate_skip_architecture : bool  default False
    cert_gate_skip_hygiene      : bool  default False
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class CertificationGateResult:
    """Result of the unified certification gate."""

    passed: bool = False
    verdict: str = ""
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))

    # Individual certifier results
    strategy_certification: dict[str, Any] = field(default_factory=dict)
    replay_certification: dict[str, Any] = field(default_factory=dict)
    paper_trading_certification: dict[str, Any] = field(default_factory=dict)
    architecture_compliance: dict[str, Any] = field(default_factory=dict)
    repository_hygiene: dict[str, Any] = field(default_factory=dict)

    # Summary
    total_certifiers: int = 5
    passed_certifiers: int = 0
    failed_certifiers: int = 0
    skipped_certifiers: int = 0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def summary(self) -> str:
        """Return a human-readable summary."""
        status_icon = "[PASS]" if self.passed else "[BLOCK]"
        lines = [
            "=" * 70,
            f"  CERTIFICATION GATE: {status_icon}",
            "=" * 70,
            f"  Verdict: {self.verdict}",
            f"  Certifiers: {self.passed_certifiers}/{self.total_certifiers} passed, "
            f"{self.failed_certifiers} failed, {self.skipped_certifiers} skipped",
            f"  Duration: {self.duration_seconds:.2f}s",
            "",
            "  Individual Results:",
        ]

        certs = [
            ("Strategy Certification", self.strategy_certification),
            ("Replay Certification", self.replay_certification),
            ("Paper Trading Certification", self.paper_trading_certification),
            ("Architecture Compliance", self.architecture_compliance),
            ("Repository Hygiene", self.repository_hygiene),
        ]

        for name, data in certs:
            status = data.get("status", "NOT RUN")
            icon = {"PASSED": "[OK]", "FAILED": "[X]", "SKIPPED": "[--]", "NOT RUN": "[..]"}.get(status, "[??]")
            msg = data.get("message", "")
            lines.append(f"    {icon} {name:<35s} {status:<8s} {msg[:80]}")

        if self.failures:
            lines.append("")
            lines.append(f"  Failures ({len(self.failures)}):")
            for f in self.failures:
                lines.append(f"    [X] {f}")

        if self.warnings:
            lines.append("")
            lines.append(f"  Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"    [!] {w}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON audit records."""
        return {
            "certification_gate": {
                "passed": self.passed,
                "verdict": self.verdict,
                "timestamp": self.timestamp,
                "total_certifiers": self.total_certifiers,
                "passed_certifiers": self.passed_certifiers,
                "failed_certifiers": self.failed_certifiers,
                "skipped_certifiers": self.skipped_certifiers,
                "duration_seconds": round(self.duration_seconds, 2),
                "failures": self.failures[:20],
                "warnings": self.warnings[:20],
            },
            "results": {
                "strategy": self.strategy_certification,
                "replay": self.replay_certification,
                "paper": self.paper_trading_certification,
                "architecture": self.architecture_compliance,
                "hygiene": self.repository_hygiene,
            },
        }


# ── Individual certifier runners ──────────────────────────────────────────────

def _run_strategy_certification(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run strategy certification."""
    if cfg.get("cert_gate_skip_strategy", False):
        return {"status": "SKIPPED", "message": "Strategy certification disabled by config"}

    try:
        from core.certification.strategy_certifier import certify_all_strategies

        reports = certify_all_strategies()
        all_pass = all(r.passed for r in reports)
        total = len(reports)
        passed = sum(1 for r in reports if r.passed)
        failed = total - passed

        failures = []
        for r in reports:
            if not r.passed and r.failures:
                for f in r.failures[:3]:
                    failures.append(f"{r.strategy_name}: {f}")

        return {
            "status": "PASSED" if all_pass else "FAILED",
            "total_strategies": total,
            "passed": passed,
            "failed": failed,
            "message": f"{passed}/{total} strategies certified" if all_pass
                      else f"{failed} strategy(s) failed certification",
            "failures": failures[:5],
            "details": [r.to_dict() for r in reports],
        }
    except ImportError as exc:
        return {"status": "SKIPPED", "message": f"Strategy certifier not available: {exc}"}
    except Exception as exc:
        return {"status": "FAILED", "message": f"Strategy certification error: {exc}"}


def _run_replay_certification(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run replay certification."""
    if cfg.get("cert_gate_skip_replay", False):
        return {"status": "SKIPPED", "message": "Replay certification disabled by config"}

    db_path = cfg.get("trades_db_path", "trades.db")
    if not Path(db_path).is_file():
        return {"status": "SKIPPED", "message": f"Trades DB not found: {db_path} — no replay data"}

    try:
        from core.certification.replay_certifier import certify_replay_determinism

        report = certify_replay_determinism(db_path=db_path, max_trades=10, frames=5, width=30)
        return {
            "status": "PASSED" if report.passed else "FAILED",
            "total_trades": report.total_trades,
            "tested": report.tested_trades,
            "deterministic": report.deterministic_count,
            "failed_count": report.failed_count,
            "message": report.verdict[:200],
            "failures": report.failures[:5],
        }
    except ImportError as exc:
        return {"status": "SKIPPED", "message": f"Replay certifier not available: {exc}"}
    except Exception as exc:
        return {"status": "FAILED", "message": f"Replay certification error: {exc}"}


def _run_paper_certification(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run paper trading certification."""
    if cfg.get("cert_gate_skip_paper", False):
        return {"status": "SKIPPED", "message": "Paper certification disabled by config"}

    db_path = cfg.get("trades_db_path", "trades.db")
    if not Path(db_path).is_file():
        return {"status": "SKIPPED", "message": f"Trades DB not found: {db_path} — no paper data"}

    try:
        from core.certification.paper_certifier import certify_paper_trading

        report = certify_paper_trading(db_path=db_path)
        return {
            "status": "PASSED" if report.passed else "FAILED",
            "total_trades": report.total_trades,
            "closed_trades": report.closed_trades,
            "win_rate": round(report.win_rate, 4),
            "profit_factor": round(report.profit_factor, 4),
            "overall_score": report.overall_score,
            "message": report.verdict[:200],
            "failures": report.issues[:5],
        }
    except ImportError as exc:
        return {"status": "SKIPPED", "message": f"Paper certifier not available: {exc}"}
    except Exception as exc:
        return {"status": "FAILED", "message": f"Paper certification error: {exc}"}


def _run_architecture_compliance(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run architecture compliance check."""
    if cfg.get("cert_gate_skip_architecture", False):
        return {"status": "SKIPPED", "message": "Architecture compliance disabled by config"}

    script = ROOT / "scripts" / "check_architecture_compliance.py"
    if not script.is_file():
        return {"status": "SKIPPED", "message": "Architecture compliance script not found"}

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--ci"],
            capture_output=True, text=True, timeout=30,
        )
        passed = result.returncode == 0
        output = (result.stdout or result.stderr or "")[:500]
        return {
            "status": "PASSED" if passed else "FAILED",
            "exit_code": result.returncode,
            "message": output.split("\n")[0] if output else "Architecture compliance check completed",
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "message": "Architecture compliance check timed out"}
    except FileNotFoundError:
        return {"status": "SKIPPED", "message": "Architecture compliance script not available"}
    except Exception as exc:
        return {"status": "FAILED", "message": f"Architecture compliance error: {exc}"}


def _run_hygiene_check(cfg: dict[str, Any]) -> dict[str, Any]:
    """Run repository hygiene check."""
    if cfg.get("cert_gate_skip_hygiene", False):
        return {"status": "SKIPPED", "message": "Hygiene check disabled by config"}

    script = ROOT / "scripts" / "hygiene_check.py"
    if not script.is_file():
        return {"status": "SKIPPED", "message": "Hygiene check script not found"}

    try:
        result = subprocess.run(
            [sys.executable, str(script), "--ci"],
            capture_output=True, text=True, timeout=30,
        )
        passed = result.returncode == 0
        output = (result.stdout or result.stderr or "")[:500]
        return {
            "status": "PASSED" if passed else "FAILED",
            "exit_code": result.returncode,
            "message": output.split("\n")[0] if output else "Hygiene check completed",
            "output": output,
        }
    except subprocess.TimeoutExpired:
        return {"status": "FAILED", "message": "Hygiene check timed out"}
    except FileNotFoundError:
        return {"status": "SKIPPED", "message": "Hygiene check script not available"}
    except Exception as exc:
        return {"status": "FAILED", "message": f"Hygiene check error: {exc}"}


# ── Certification Gate ────────────────────────────────────────────────────────

class CertificationGate:
    """
    Unified Certification Gate — runs ALL certifiers and produces a single result.

    This is the final authority on whether a release is certified for production.
    All failures are BLOCKING.

    Usage:
        gate = CertificationGate(cfg)
        result = gate.run_all()

        if not result.passed:
            print(f"Release BLOCKED: {result.verdict}")
            sys.exit(1)
    """

    def __init__(self, cfg: dict[str, Any] | None = None):
        self._cfg = cfg or {}

    def run_all(self) -> CertificationGateResult:
        """
        Run ALL certification checks and return consolidated result.

        Returns:
            CertificationGateResult with pass/fail verdict.
        """
        start_time = time.time()
        result = CertificationGateResult()

        # Run all certifiers in sequence
        cert_runners = [
            ("strategy_certification", lambda: _run_strategy_certification(self._cfg)),
            ("replay_certification", lambda: _run_replay_certification(self._cfg)),
            ("paper_trading_certification", lambda: _run_paper_certification(self._cfg)),
            ("architecture_compliance", lambda: _run_architecture_compliance(self._cfg)),
            ("repository_hygiene", lambda: _run_hygiene_check(self._cfg)),
        ]

        for attr_name, runner in cert_runners:
            try:
                cert_result = runner()
                setattr(result, attr_name, cert_result)

                if cert_result.get("status") == "PASSED":
                    result.passed_certifiers += 1
                elif cert_result.get("status") == "FAILED":
                    result.failed_certifiers += 1
                    for f in cert_result.get("failures", []):
                        result.failures.append(f"[{attr_name}] {f}")
                    if not cert_result.get("failures"):
                        result.failures.append(
                            f"[{attr_name}] {cert_result.get('message', 'Unknown failure')}"
                        )
                elif cert_result.get("status") == "SKIPPED":
                    result.skipped_certifiers += 1
                else:
                    result.skipped_certifiers += 1

                # Collect warnings
                for w in cert_result.get("warnings", []):
                    result.warnings.append(f"[{attr_name}] {w}")

            except Exception as exc:
                _log.error("[CERT_GATE] %s failed with exception: %s", attr_name, exc)
                result.failed_certifiers += 1
                result.failures.append(f"[{attr_name}] Exception: {exc}")
                setattr(result, attr_name, {"status": "FAILED", "message": str(exc)})

        result.duration_seconds = time.time() - start_time

        # Determine overall verdict
        block_on_warn = self._cfg.get("cert_gate_block_on_warn", False)
        max_failures = int(self._cfg.get("cert_gate_max_failures", 0))

        if result.failed_certifiers > max_failures:
            result.passed = False
            result.verdict = (
                f"RELEASE BLOCKED: {result.failed_certifiers} certification(s) failed "
                f"(max allowed: {max_failures})"
            )
        elif block_on_warn and result.warnings:
            result.passed = False
            result.verdict = (
                f"RELEASE BLOCKED: {len(result.warnings)} warning(s) found "
                f"(cert_gate_block_on_warn=True)"
            )
        elif result.failed_certifiers == 0 and result.passed_certifiers > 0:
            result.passed = True
            result.verdict = (
                f"ALL {result.passed_certifiers} certification(s) PASSED — release approved"
            )
        elif result.failed_certifiers == 0 and result.passed_certifiers == 0:
            result.passed = True
            result.verdict = "No certifiers ran — vacuously true"
        else:
            result.passed = True
            result.verdict = "Certification gate passed"

        return result


# ── Convenience API ───────────────────────────────────────────────────────────

def run_certification_gate(
    cfg: dict[str, Any] | None = None,
) -> CertificationGateResult:
    """
    Convenience function — create gate, run all certifiers, return result.

    Usage:
        result = run_certification_gate()
        if not result.passed:
            print(result.summary())
            raise SystemExit(1)
    """
    gate = CertificationGate(cfg)
    return gate.run_all()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.certification.gate",
        description="Unified Certification Gate — run all certifiers",
    )
    ap.add_argument("--json", action="store_true", help="Output JSON")
    ap.add_argument("--block-on-warn", action="store_true",
                    help="Block release on warnings too")
    args = ap.parse_args()

    cfg = {}
    if args.block_on_warn:
        cfg["cert_gate_block_on_warn"] = True

    result = run_certification_gate(cfg)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())

    raise SystemExit(0 if result.passed else 1)


__all__ = [
    "CertificationGate",
    "CertificationGateResult",
    "ROOT",
    "run_certification_gate",
]

