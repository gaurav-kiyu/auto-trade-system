"""
Runbook Executor — Auto-executes runbook steps when failure patterns are detected.

Parses Markdown runbook files from docs/runbooks/, maps failure patterns to
runbook IDs, and provides a structured RunbookExecution interface that the
self-healing orchestrator can call as a recovery action.

Usage
-----
    from core.runbook_executor import RunbookExecutor, get_runbook_executor

    executor = RunbookExecutor()
    all_runbooks = executor.discover_runbooks()
    steps = executor.get_runbook_for_failure("broker_disconnected")
    if steps:
        executor.execute_step(steps[0])  # Run first step

Integration with SelfHealingOrchestrator:
    recovery_actions=[RecoveryAction.RUN_RUNBOOK, ...]
    # The orchestrator calls executor.get_runbook_for_failure(pattern_name)
    # and executes steps automatically.

Config keys (all optional — safe defaults built in)
---------------------------------------------------
    runbook_executor_enabled       : bool  default True
    runbook_dir                    : str   default "docs/runbooks"
    runbook_auto_execute           : bool  default False  (auto-execute steps when True)
    runbook_execute_timeout_sec    : int   default 30     (timeout per step execution)
"""

from __future__ import annotations

import json
import logging
import re
import subprocess  # nosec — only used for safe shell commands from runbook steps
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

_DEFAULT_RUNBOOK_DIR = "docs/runbooks"


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class RunbookStep:
    """A single step in a runbook."""
    number: int
    title: str
    command: str | None = None
    verification: str | None = None
    timeout_seconds: int = 30


@dataclass
class Runbook:
    """Parsed runbook with structured metadata and steps."""
    runbook_id: str        # e.g., "RB-001"
    name: str              # e.g., "broker_outage"
    title: str             # e.g., "Broker Outage"
    severity: str          # e.g., "CRITICAL", "HIGH", "MEDIUM"
    category: str          # e.g., "Broker / Execution"
    trigger_condition: str = ""
    expected_symptoms: str = ""
    steps: list[RunbookStep] = field(default_factory=list)
    verification_checks: list[str] = field(default_factory=list)
    escalation_path: str = ""
    last_updated: str = ""
    file_path: str = ""


@dataclass
class RunbookExecutionResult:
    """Result of a runbook step execution."""
    step_number: int
    step_title: str
    status: str      # "SUCCESS" | "FAILED" | "SKIPPED"
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


# ── Failure-to-Runbook Mapping ──────────────────────────────────────────────

# Maps failure pattern names (from SelfHealingOrchestrator) to runbook filenames
_FAILURE_TO_RUNBOOK: dict[str, str] = {
    "circuit_breaker_open":  "broker_outage",
    "broker_disconnected":   "broker_outage",
    "stale_market_feed":     "stale_feed",
    "database_connection":   "db_corruption",
    "config_corruption":     "config_corruption",
    "hard_halt_stuck":       "broker_outage",
    "watchdog_timeout":      "network_jitter",
    "disk_space_low":        "disk_pressure",
    "wal_lag":               "db_corruption",
    "stale_locks":           "db_corruption",
}

# Reverse mapping: runbook name → canonical failure pattern name
_RUNBOOK_TO_FAILURE: dict[str, str] = {v: k for k, v in _FAILURE_TO_RUNBOOK.items()}


# ── Runbook Executor ────────────────────────────────────────────────────────

class RunbookExecutor:
    """Parses runbook Markdown files and executes runbook steps."""

    def __init__(
        self,
        cfg: dict[str, Any] | None = None,
        notify_fn: Callable[[str], None] | None = None,
    ):
        self._cfg = cfg or {}
        self._notify_fn = notify_fn
        self._lock = threading.RLock()
        self._runbooks: dict[str, Runbook] = {}  # name -> Runbook
        self.discover_runbooks()

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("runbook_executor_enabled", True))

    @property
    def auto_execute(self) -> bool:
        return bool(self._cfg.get("runbook_auto_execute", False))

    def discover_runbooks(self) -> dict[str, Runbook]:
        """Parse all runbook Markdown files from the runbooks directory.

        Returns:
            dict mapping runbook name (e.g., 'broker_outage') to Runbook.
        """
        runbook_dir = Path(self._cfg.get("runbook_dir", _DEFAULT_RUNBOOK_DIR))
        if not runbook_dir.is_dir():
            _log.warning("[RUNBOOK] Runbook directory not found: %s", runbook_dir)
            return {}

        discovered: dict[str, Runbook] = {}
        for md_file in sorted(runbook_dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8", errors="ignore")
                runbook = self._parse_runbook(md_file, text)
                if runbook:
                    discovered[runbook.name] = runbook
            except (OSError, UnicodeDecodeError) as exc:
                _log.warning("[RUNBOOK] Failed to parse %s: %s", md_file.name, exc)

        with self._lock:
            self._runbooks = discovered

        _log.info("[RUNBOOK] Discovered %d runbook(s): %s",
                  len(discovered), list(discovered.keys()))
        return discovered

    def _parse_runbook(self, file_path: Path, text: str) -> Runbook | None:
        """Parse a single runbook Markdown file into a Runbook dataclass.

        Extracts:
        - Frontmatter table (| Field | Value |)
        - Trigger Condition section
        - Steps section (numbered list items with ```bash blocks)
        - Verification section (checklist items)
        - Escalation Path section
        """
        name = file_path.stem  # e.g., "broker_outage"
        title = name.replace("_", " ").title()

        # Extract metadata from the first table (pipe-delimited)
        runbook_id = ""
        severity = "MEDIUM"
        category = "General"
        last_updated = ""
        table_match = re.search(
            r"^\|.*?\|.*?\|$\s+^\|[-| ]+\|$(.+?)^(?=\S)",
            text, re.MULTILINE | re.DOTALL
        )
        if table_match:
            table_body = table_match.group(1)
            for row in re.finditer(r"^\|(.+?)\|(.+?)\|", table_body, re.MULTILINE):
                key = row.group(1).strip()
                val = row.group(2).strip()
                if "ID" in key:
                    runbook_id = val
                elif "Severity" in key:
                    severity = val.upper()
                elif "Category" in key:
                    category = val
                elif "Updated" in key:
                    last_updated = val

        # Extract trigger condition (text under ## Trigger Condition)
        trigger_match = re.search(
            r"##\s+Trigger\s+Condition\s*\n(.*?)(?=\n##\s)",
            text, re.DOTALL
        )
        trigger_condition = trigger_match.group(1).strip() if trigger_match else ""

        # Extract expected symptoms
        symptoms_match = re.search(
            r"##\s+Expected\s+Symptoms\s*\n(.*?)(?=\n##\s)",
            text, re.DOTALL
        )
        expected_symptoms = symptoms_match.group(1).strip() if symptoms_match else ""

        # Extract resolution steps (numbered sections with bash blocks)
        steps: list[RunbookStep] = []
        # Match patterns like "### X: Title" or "### Step X: Title"
        step_sections = re.finditer(
            r"###\s+(?:Step\s+)?(\d+)\s*[.:]?\s*(.*?)\n(.*?)(?=\n###\s|\Z)",
            text, re.DOTALL
        )
        for match in step_sections:
            step_num = int(match.group(1))
            step_title = match.group(2).strip()
            step_body = match.group(3).strip()

            # Extract bash command blocks
            cmd_match = re.search(
                r"```(?:bash)?\s*\n(.*?)```", step_body, re.DOTALL
            )
            command = cmd_match.group(1).strip() if cmd_match else None

            steps.append(RunbookStep(
                number=step_num,
                title=step_title,
                command=command,
                timeout_seconds=self._cfg.get("runbook_execute_timeout_sec", 30),
            ))

        # Fallback: if no ### steps found, try numbered list items with bash
        if not steps:
            list_items = re.finditer(
                r"^\d+\.\s*(.*?)(?=\n\n|\Z)", text, re.MULTILINE | re.DOTALL
            )
            for i, item in enumerate(list_items, 1):
                body = item.group(1).strip()
                cmd_match = re.search(
                    r"```(?:bash)?\s*\n(.*?)```", body, re.DOTALL
                )
                command = cmd_match.group(1).strip() if cmd_match else None
                title_text = body.split("\n")[0][:80] if body else f"Step {i}"
                steps.append(RunbookStep(
                    number=i, title=title_text, command=command,
                ))

        # Extract verification checklist
        verification_checks: list[str] = []
        verif_match = re.search(
            r"##\s+Verification\s*\n(.*?)(?=\n##\s|\Z)",
            text, re.DOTALL
        )
        if verif_match:
            verif_body = verif_match.group(1)
            verification_checks = [
                re.sub(r"^-\s*\[\s*[ xX]?\s*\]\s*", "", line).strip()
                for line in verif_body.split("\n")
                if line.strip().startswith("- [")
            ]

        # Extract escalation path
        escalation_match = re.search(
            r"##\s+Escalation\s+Path\s*\n(.*?)(?=\n##\s|\Z)",
            text, re.DOTALL
        )
        escalation_path = escalation_match.group(1).strip() if escalation_match else ""

        return Runbook(
            runbook_id=runbook_id or f"RB-{name.upper()}",
            name=name,
            title=title,
            severity=severity,
            category=category,
            trigger_condition=trigger_condition,
            expected_symptoms=expected_symptoms,
            steps=steps,
            verification_checks=verification_checks,
            escalation_path=escalation_path,
            last_updated=last_updated,
            file_path=str(file_path),
        )

    def get_runbook_for_failure(self, failure_name: str) -> Runbook | None:
        """Get the runbook associated with a failure pattern name.

        Args:
            failure_name: Pattern name from SelfHealingOrchestrator
                          (e.g., 'broker_disconnected', 'database_connection').

        Returns:
            Runbook if found, None otherwise.
        """
        runbook_name = _FAILURE_TO_RUNBOOK.get(failure_name)
        if not runbook_name:
            # Fallback: try direct name match
            runbook_name = failure_name
        with self._lock:
            return self._runbooks.get(runbook_name)

    def get_runbook_by_id(self, runbook_id: str) -> Runbook | None:
        """Get a runbook by its runbook ID (e.g., 'RB-001')."""
        with self._lock:
            for rb in self._runbooks.values():
                if runbook_id in rb.runbook_id:
                    return rb
        return None

    def execute_step(
        self,
        step: RunbookStep,
        notify: bool = True,
    ) -> RunbookExecutionResult:
        """Execute a single runbook step.

        For steps with bash commands, runs the command via subprocess.
        For steps without commands, returns SKIPPED with the step title.

        Args:
            step: The runbook step to execute.
            notify: Whether to notify operator about step execution.

        Returns:
            RunbookExecutionResult with status and output.
        """
        start = time.time()

        if not self.enabled:
            return RunbookExecutionResult(
                step_number=step.number,
                step_title=step.title,
                status="SKIPPED",
                error="Runbook executor disabled",
            )

        if not step.command:
            return RunbookExecutionResult(
                step_number=step.number,
                step_title=step.title,
                status="SKIPPED",
                output=f"No executable command — manual step: {step.title}",
            )

        # Execute the command
        try:
            result = subprocess.run(
                step.command,
                shell=True,  # nosec — runbook commands are operator-defined
                capture_output=True,
                text=True,
                timeout=step.timeout_seconds,
            )
            duration_ms = (time.time() - start) * 1000

            if result.returncode == 0:
                status = "SUCCESS"
                output = result.stdout.strip()[:500] if result.stdout else "OK"
                error = ""
            else:
                status = "FAILED"
                output = result.stdout.strip()[:200] if result.stdout else ""
                error = result.stderr.strip()[:300] if result.stderr else f"Exit code: {result.returncode}"

            # Notify operator on failure
            if notify and status == "FAILED" and self._notify_fn:
                self._notify_fn(
                    f"[RUNBOOK] Step {step.number} '{step.title}' FAILED: {error}"
                )

            return RunbookExecutionResult(
                step_number=step.number,
                step_title=step.title,
                status=status,
                output=output,
                error=error,
                duration_ms=round(duration_ms, 1),
            )

        except subprocess.TimeoutExpired:
            duration_ms = (time.time() - start) * 1000
            return RunbookExecutionResult(
                step_number=step.number,
                step_title=step.title,
                status="FAILED",
                error=f"Command timed out after {step.timeout_seconds}s",
                duration_ms=round(duration_ms, 1),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            duration_ms = (time.time() - start) * 1000
            return RunbookExecutionResult(
                step_number=step.number,
                step_title=step.title,
                status="FAILED",
                error=str(exc),
                duration_ms=round(duration_ms, 1),
            )

    def execute_runbook(
        self,
        runbook: Runbook,
        max_steps: int = 0,
    ) -> list[RunbookExecutionResult]:
        """Execute all steps of a runbook (or up to max_steps).

        Args:
            runbook: The runbook to execute.
            max_steps: Max steps to execute (0 = all).

        Returns:
            List of step execution results.
        """
        if not self.auto_execute:
            _log.info("[RUNBOOK] Auto-execute disabled — not running %s", runbook.name)
            return []

        steps = runbook.steps[:max_steps] if max_steps > 0 else runbook.steps
        results: list[RunbookExecutionResult] = []

        for step in steps:
            if not self.enabled:
                break
            result = self.execute_step(step)
            results.append(result)
            _log.info(
                "[RUNBOOK] Step %d/%d: %s (%s)",
                step.number, len(steps),
                step.title, result.status,
            )
            # Stop on failure (fail-fast)
            if result.status == "FAILED":
                if self._notify_fn:
                    self._notify_fn(
                        f"[RUNBOOK] Aborting {runbook.title} — step {step.number} failed"
                    )
                break

        n_ok = sum(1 for r in results if r.status == "SUCCESS")
        n_fail = sum(1 for r in results if r.status == "FAILED")
        _log.info(
            "[RUNBOOK] %s complete: %d/%d OK, %d failed",
            runbook.name, n_ok, len(results), n_fail,
        )
        return results

    def format_runbook_report(self, runbook: Runbook) -> str:
        """Return a formatted report of the runbook suitable for CLI or notification."""
        lines = [
            f"Runbook: {runbook.title} ({runbook.runbook_id})",
            f"  Severity: {runbook.severity} | Category: {runbook.category}",
            "",
        ]
        if runbook.trigger_condition:
            lines.append(f"  Trigger: {runbook.trigger_condition[:100]}")
        if runbook.steps:
            lines.append(f"  Steps ({len(runbook.steps)}):")
            for step in runbook.steps:
                has_cmd = "⚡" if step.command else "📋"
                lines.append(f"    {has_cmd} Step {step.number}: {step.title}")
        if runbook.verification_checks:
            lines.append(f"  Verification ({len(runbook.verification_checks)} checks):")
            for v in runbook.verification_checks[:5]:
                lines.append(f"    ☐ {v[:80]}")
        return "\n".join(lines)

    def get_all_runbooks(self) -> dict[str, Runbook]:
        """Get all discovered runbooks."""
        with self._lock:
            return dict(self._runbooks)

    def get_failure_mapping(self) -> dict[str, str]:
        """Get the failure pattern → runbook mapping for diagnostics."""
        return dict(_FAILURE_TO_RUNBOOK)


# ── Singleton ─────────────────────────────────────────────────────────────────

_global_executor: RunbookExecutor | None = None
_executor_lock = threading.RLock()


def get_runbook_executor(
    cfg: dict[str, Any] | None = None,
    notify_fn: Callable[[str], None] | None = None,
) -> RunbookExecutor:
    """Get the global RunbookExecutor (thread-safe singleton)."""
    global _global_executor
    if _global_executor is None:
        with _executor_lock:
            if _global_executor is None:
                _global_executor = RunbookExecutor(cfg=cfg, notify_fn=notify_fn)
    return _global_executor


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m core.runbook_executor",
        description="Runbook Executor — discover and run operation runbooks",
    )
    ap.add_argument("--list", action="store_true", help="List all discovered runbooks")
    ap.add_argument("--show", type=str, default="", help="Show a specific runbook by name")
    ap.add_argument("--failure", type=str, default="",
                    help="Show runbook for a failure pattern name")
    ap.add_argument("--json", action="store_true", help="Output JSON")
    args = ap.parse_args()

    executor = get_runbook_executor()

    if args.list:
        runbooks = executor.get_all_runbooks()
        if args.json:
            print(json.dumps({
                name: {
                    "runbook_id": rb.runbook_id,
                    "title": rb.title,
                    "severity": rb.severity,
                    "category": rb.category,
                    "steps": len(rb.steps),
                }
                for name, rb in runbooks.items()
            }, indent=2))
        else:
            print(f"Discovered {len(runbooks)} runbook(s):")
            for name, rb in sorted(runbooks.items()):
                print(f"  {rb.runbook_id} | {name:<25} | {rb.severity:<8} | {rb.category}")
                print(f"        {len(rb.steps)} step(s), {len(rb.verification_checks)} verification(s)")

    elif args.show:
        runbook = executor.get_runbook_for_failure(args.show)
        if not runbook:
            # Try direct name lookup
            all_rbs = executor.get_all_runbooks()
            runbook = all_rbs.get(args.show)
        if runbook:
            if args.json:
                print(json.dumps({
                    "runbook_id": runbook.runbook_id,
                    "name": runbook.name,
                    "title": runbook.title,
                    "severity": runbook.severity,
                    "category": runbook.category,
                    "trigger_condition": runbook.trigger_condition[:200],
                    "steps": [{"number": s.number, "title": s.title, "has_command": s.command is not None}
                              for s in runbook.steps],
                    "verification_checks": runbook.verification_checks,
                }, indent=2))
            else:
                print(executor.format_runbook_report(runbook))
        else:
            print(f"Runbook not found: {args.show}")

    elif args.failure:
        runbook = executor.get_runbook_for_failure(args.failure)
        if runbook:
            print(f"Failure pattern '{args.failure}' → {runbook.title} ({runbook.runbook_id})")
            if args.json:
                print(json.dumps({
                    "failure_pattern": args.failure,
                    "runbook_name": runbook.name,
                    "runbook_id": runbook.runbook_id,
                    "steps": len(runbook.steps),
                }, indent=2))
        else:
            print(f"No runbook mapped for failure pattern: {args.failure}")
            mapping = executor.get_failure_mapping()
            if args.failure in mapping:
                print(f"  (mapped to {mapping[args.failure]})")
            else:
                print(f"  Available mappings: {list(mapping.keys())}")

    else:
        print(f"Runbook Executor — {len(executor.get_all_runbooks())} runbooks discovered")
        print(f"  {len(executor.get_failure_mapping())} failure pattern mappings")
        print("Use --list to see all, --show <name> to inspect, --failure <pattern> to map")


__all__ = [
    "Runbook",
    "RunbookExecutionResult",
    "RunbookExecutor",
    "RunbookStep",
    "get_runbook_executor",
]

