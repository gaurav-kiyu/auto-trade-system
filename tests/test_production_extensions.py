from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from core import (
    AuditEngine,
    DataEngine,
    ExecutionEngine,
    JsonlCaptureWriter,
    Orchestrator,
    PresentationEngine,
    ReconciliationEngine,
    RiskConfig,
    RiskEngine,
    SafetyConfig,
    SafetyContext,
    SafetyEngine,
    StateManager,
    StrategyEngine,
)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"


def test_reconciliation_engine_detects_qty_mismatch():
    engine = ReconciliationEngine(
        broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 101.0}},
        price_tolerance_pct=0.05,
        qty_mismatch_halts=True,
    )
    report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
    assert report.ok is False
    assert report.mismatches >= 1
    assert "qty mismatch" in report.items[0].note


def test_reconciliation_engine_reports_broker_only_positions():
    engine = ReconciliationEngine(
        broker_snapshot_fn=lambda: {
            "NIFTY": {"qty": 25, "avg_price": 100.0},
            "BANKNIFTY": {"qty": 10, "avg_price": 50.0},
        },
        report_broker_only_positions=True,
    )
    report = engine.reconcile_positions({"NIFTY": {"qty": 25, "entry": 100.0}})
    symbols = {it.symbol for it in report.items}
    assert "BANKNIFTY" in symbols
    orphan = next(it for it in report.items if it.symbol == "BANKNIFTY")
    assert orphan.local_qty == 0 and orphan.broker_qty == 10
    assert "broker-only" in orphan.note.lower()
    assert report.mismatches >= 1


@pytest.mark.slow
def test_capture_writer_and_script_round_trip(tmp_path):
    path = tmp_path / "capture.jsonl"
    writer = JsonlCaptureWriter(path)
    writer.write({"ts": "2026-04-09T01:00:00+05:30", "event": "manual_trade", "symbol": "NIFTY"})
    first = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(first) == 1

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "capture_broker_replay.py"),
            "--file",
            str(path),
            "--event",
            "verify_fill",
            "--symbol",
            "NIFTY",
            "--qty",
            "50",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


@pytest.mark.slow
def test_walkforward_runner_smoke(tmp_path):
    report_path = tmp_path / "walkforward.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_walkforward.py"),
            "--csv",
            str(FIXTURES / "replay_minute_bars.csv"),
            "--strategy",
            "smoke",
            "--report-file",
            str(report_path),
            "--train-bars",
            "15",
            "--test-bars",
            "10",
            "--step-bars",
            "10",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "windows" in payload
    assert len(payload["windows"]) >= 1


def test_presentation_engine_uses_simple_operator_language():
    engine = PresentationEngine(currency_symbol="₹")
    msg = engine.manual_signal_message(
        name="NIFTY",
        signal_type="CALL",
        strike=22500,
        entry=145.5,
        qty=50,
        sl=132.0,
        target=168.0,
        net_rr=1.7,
        score=84,
        why="trend and volume support the move",
    )
    assert "Manual signal for NIFTY" in msg
    assert "Action: check your broker screen" in msg


def test_orchestrator_runs_manual_cycle_without_breaking_existing_flow():
    data_engine = DataEngine(
        fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}},
    )
    strategy_engine = StrategyEngine(
        generate_signal_fn=lambda name, frames, vix=0.0: {
            "name": name,
            "direction": "CALL",
            "vol_ratio": 1.5,
            "qty": 50,
            "strike": 22500,
        }
    )
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 50,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 0,
        latency_check_fn=lambda start_ts: True,
    )
    state_saved = {"ok": False}
    state_manager = StateManager(save_fn=lambda: state_saved.__setitem__("ok", True), load_fn=lambda: None)
    execution_engine = ExecutionEngine(broker_getter=lambda: None)
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=execution_engine,
        state_manager=state_manager,
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "MANUAL",
    )
    cycle = orchestrator.run_cycle()
    assert cycle.saved is True
    assert state_saved["ok"] is True
    assert len(cycle.signals) == 1
    assert cycle.signals[0].executed is False


def test_orchestrator_audits_and_honors_safety_gate(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    data_engine = DataEngine(fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}})
    strategy_engine = StrategyEngine(generate_signal_fn=lambda name, frames, vix=0.0: {"name": name, "direction": "CALL", "vol_ratio": 2.0})
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 1,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 0,
        latency_check_fn=lambda start_ts: True,
    )
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=ExecutionEngine(broker_getter=lambda: None),
        state_manager=StateManager(save_fn=lambda: None, load_fn=lambda: None),
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "AUTO",
        safety_engine=SafetyEngine(SafetyConfig(max_api_failures=2)),
        safety_context_fn=lambda snapshot: SafetyContext(api_failures=2, data_healthy=True),
        audit_engine=AuditEngine(audit_path, enabled=True),
    )
    cycle = orchestrator.run_cycle()
    assert cycle.signals[0].risk.allowed is False
    assert "api failures" in cycle.signals[0].risk.reason
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2


def test_orchestrator_reconciliation_uses_local_positions_not_broker():
    recon = ReconciliationEngine(
        broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 100.0}},
        price_tolerance_pct=0.05,
        qty_mismatch_halts=True,
    )
    data_engine = DataEngine(
        fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}},
    )
    strategy_engine = StrategyEngine(
        generate_signal_fn=lambda name, frames, vix=0.0: {
            "name": name,
            "direction": "CALL",
            "vol_ratio": 1.5,
            "qty": 50,
            "strike": 22500,
        }
    )
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 50,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 0,
        latency_check_fn=lambda start_ts: True,
    )
    state_manager = StateManager(save_fn=lambda: None, load_fn=lambda: None)
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=ExecutionEngine(broker_getter=lambda: None),
        state_manager=state_manager,
        reconciliation_engine=recon,
        local_positions_fn=lambda: {"NIFTY": {"qty": 50, "entry": 100.0}},
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "MANUAL",
    )
    cycle = orchestrator.run_cycle()
    assert cycle.reconciliation is not None
    assert cycle.reconciliation.ok is False
    assert cycle.reconciliation.mismatches >= 1


def test_orchestrator_risk_engine_blocks_trade():
    """Risk gate through single risk_engine (v2 consolidated into main engine)."""
    data_engine = DataEngine(fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}})
    strategy_engine = StrategyEngine(
        generate_signal_fn=lambda name, frames, vix=0.0: {"name": name, "direction": "CALL", "vol_ratio": 0.1}
    )
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 1,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 3,
        latency_check_fn=lambda start_ts: True,
    )
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=ExecutionEngine(broker_getter=lambda: None),
        state_manager=StateManager(save_fn=lambda: None, load_fn=lambda: None),
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "AUTO",
        entry_gate_fn=lambda name, sig: True,
    )
    cycle = orchestrator.run_cycle()
    # Blocked due to low vol_ratio (0.1 < min_volume_ratio 1.0) or consecutive losses
    assert cycle.signals[0].risk.allowed is False


class _FillBrokerSimple:
    def place_order(self, name, direction, qty, strike):
        return "oid-1"

    def wait_for_fill(self, order_id, timeout=10):
        return True

    def get_filled_quantity(self, order_id):
        return 1

    def get_fill_price(self, order_id):
        return 100.0


def test_orchestrator_verify_fill_controls_executed_flag():
    data_engine = DataEngine(fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}})
    strategy_engine = StrategyEngine(
        generate_signal_fn=lambda name, frames, vix=0.0: {"name": name, "direction": "CALL", "vol_ratio": 2.0}
    )
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 1,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 0,
        latency_check_fn=lambda start_ts: True,
    )
    execution_engine = ExecutionEngine(broker_getter=lambda: _FillBrokerSimple())
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=execution_engine,
        state_manager=StateManager(save_fn=lambda: None, load_fn=lambda: None),
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "AUTO",
        entry_gate_fn=lambda name, sig: True,
    )
    cycle = orchestrator.run_cycle()
    assert cycle.signals[0].executed is True
    assert cycle.signals[0].execution_fill is not None
    assert cycle.signals[0].execution_fill.ok is True


def test_orchestrator_skips_signals_when_market_hours_gate_false():
    data_engine = DataEngine(fetch_all_frames_fn=lambda names: {"NIFTY": {"1m": [1], "5m": [1], "15m": [1]}})
    strategy_engine = StrategyEngine(
        generate_signal_fn=lambda name, frames, vix=0.0: {"name": name, "direction": "CALL", "vol_ratio": 2.0}
    )
    risk_engine = RiskEngine(
        config=RiskConfig(min_volume_ratio=1.0, max_consecutive_losses=3),
        position_size_fn=lambda name, ltp, vix=0.0: 1,
        portfolio_risk_fn=lambda: 0.0,
        consecutive_loss_fn=lambda: 0,
        latency_check_fn=lambda start_ts: True,
    )
    orchestrator = Orchestrator(
        data_engine=data_engine,
        strategy_engine=strategy_engine,
        risk_engine=risk_engine,
        execution_engine=None,
        state_manager=StateManager(save_fn=lambda: None, load_fn=lambda: None),
        names_provider=lambda: ["NIFTY"],
        execution_mode_fn=lambda: "MANUAL",
        enforce_market_hours=True,
        market_hours_fn=lambda: False,
    )
    cycle = orchestrator.run_cycle()
    assert cycle.signals == []
    assert "outside" in cycle.note.lower()
