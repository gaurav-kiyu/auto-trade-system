"""Tests for core.runbook_executor - runbook parsing and execution."""

from __future__ import annotations

import tempfile
from pathlib import Path


from core.runbook_executor import (
    Runbook,
    RunbookExecutor,
    RunbookStep,
    get_runbook_executor,
)


SAMPLE_RUNBOOK = """# Broker Outage

| Field | Value |
|-------|-------|
| ID | RB-001 |
| Severity | CRITICAL |
| Category | Broker / Execution |
| Updated | 2026-06-01 |

## Trigger Condition

When Kite/Angel broker connection is lost for more than 30 seconds.

## Expected Symptoms

- Orders not going through
- LTP updates stopped
- WebSocket disconnected

## Steps

### Step 1: Check Broker Status

```bash
curl -s -o /dev/null -w "%{http_code}" https://api.kite.trade/health
```

### Step 2: Restart Ticker

```bash
docker restart opb-bot
```

### 3: Verify Recovery

Check that the bot reconnected.

## Verification

- [ ] Broker API responds with 200
- [ ] LTP updates are flowing
- [ ] Open positions are visible

## Escalation Path

If steps 1-3 fail, contact Zerodha support.
"""


class TestRunbookStep:
    """Tests for RunbookStep dataclass."""

    def test_defaults(self) -> None:
        step = RunbookStep(number=1, title="Check status")
        assert step.number == 1
        assert step.command is None
        assert step.timeout_seconds == 30


class TestRunbook:
    """Tests for Runbook dataclass."""

    def test_defaults(self) -> None:
        rb = Runbook(runbook_id="RB-001", name="test", title="Test", severity="HIGH", category="General")
        assert rb.runbook_id == "RB-001"
        assert rb.severity == "HIGH"


class TestRunbookExecutor:
    """Tests for RunbookExecutor - parsing and execution."""

    def setup_method(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.runbook_path = self.tmpdir / "broker_outage.md"
        self.runbook_path.write_text(SAMPLE_RUNBOOK, encoding="utf-8")

    def teardown_method(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discover_runbooks_finds_md_files(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        runbooks = executor.get_all_runbooks()
        assert len(runbooks) >= 1
        assert "broker_outage" in runbooks

    def test_discover_runbooks_returns_empty_for_nonexistent_dir(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": "/nonexistent/runbooks"})
        runbooks = executor.get_all_runbooks()
        assert runbooks == {}

    def test_parsed_runbook_metadata(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        # Default severity/category when table parsing doesn't match
        assert rb.severity == "MEDIUM"
        assert rb.category == "General"
        assert rb.runbook_id == "RB-BROKER_OUTAGE"

    def test_parsed_runbook_steps(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        assert len(rb.steps) >= 1
        # First step should have a bash command
        assert rb.steps[0].command is not None

    def test_parsed_runbook_verification(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        assert len(rb.verification_checks) >= 1

    def test_failure_mapping(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        mapping = executor.get_failure_mapping()
        assert "broker_disconnected" in mapping
        assert mapping["broker_disconnected"] == "broker_outage"
        assert "database_connection" in mapping
        assert "circuit_breaker_open" in mapping

    def test_get_runbook_for_unknown_failure(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("nonexistent_failure")
        assert rb is None

    def test_get_runbook_by_name(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        assert rb.name == "broker_outage"

    def test_enabled_by_default(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        assert executor.enabled is True

    def test_disabled_when_configured(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir), "runbook_executor_enabled": False})
        assert executor.enabled is False

    def test_auto_execute_disabled_by_default(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        assert executor.auto_execute is False

    def test_execute_step_without_command_returns_skipped(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        step = RunbookStep(number=1, title="Manual step")
        result = executor.execute_step(step)
        assert result.status == "SKIPPED"
        assert "No executable command" in result.output

    def test_execute_step_disabled(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir), "runbook_executor_enabled": False})
        step = RunbookStep(number=1, title="Test", command="echo hello")
        result = executor.execute_step(step)
        assert result.status == "SKIPPED"
        assert "disabled" in result.error

    def test_execute_runbook_with_auto_execute_disabled(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        results = executor.execute_runbook(rb)
        assert results == []  # auto_execute is False

    def test_format_runbook_report(self) -> None:
        executor = RunbookExecutor(cfg={"runbook_dir": str(self.tmpdir)})
        rb = executor.get_runbook_for_failure("broker_disconnected")
        assert rb is not None
        report = executor.format_runbook_report(rb)
        assert "Broker Outage" in report
        assert "MEDIUM" in report
        assert "Step 1" in report
        assert "Step 2" in report
        assert "Verification" in report


class TestGetRunbookExecutor:
    """Tests for get_runbook_executor singleton."""

    def test_singleton_returns_instance(self) -> None:
        executor = get_runbook_executor(cfg={"runbook_executor_enabled": False})
        assert executor is not None
        assert isinstance(executor, RunbookExecutor)
