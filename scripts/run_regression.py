from __future__ import annotations

import argparse
import contextlib
import csv
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.datetime_ist import now_ist as _now_ist

REPORTS_DIR = ROOT / "reports"
FIXTURES_DIR = ROOT / "tests" / "fixtures"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    duration_ms: int = 0


def _run_case(name: str, fn: Callable[[], str]) -> CheckResult:
    start = _now_ist()
    try:
        detail = fn() or ""
        duration_ms = int((_now_ist() - start).total_seconds() * 1000)
        return CheckResult(name=name, ok=True, detail=str(detail), duration_ms=duration_ms)
    except Exception as exc:
        duration_ms = int((_now_ist() - start).total_seconds() * 1000)
        return CheckResult(name=name, ok=False, detail=str(exc), duration_ms=duration_ms)


def _best_effort_delete(path: Path, *, is_dir: bool = False) -> None:
    for _ in range(5):
        try:
            if is_dir:
                path.rmdir()
            else:
                path.unlink(missing_ok=True)
            return
        except Exception:
            pass


def _compile_target(path: Path) -> str:
    source = path.read_text(encoding="utf-8", errors="replace")
    compile(source, str(path), "exec")
    return f"compiled {path.name}"


def _check_core_imports() -> str:
    sys.dont_write_bytecode = True
    from core import (
        AuditEngine,
        ConfigValidator,
        DataEngine,
        ExecutionEngine,
        RetentionEngine,
    RiskConfig,
    SafetyEngine,
        StateManager,
        StrategyEngine,
    )

    assert AuditEngine and ConfigValidator and DataEngine and ExecutionEngine and RetentionEngine and RiskConfig and SafetyEngine and StateManager and StrategyEngine
    return "core package imports ok"


def _check_config_validator_regression() -> str:
    from core import ConfigValidator

    result = ConfigValidator(
        {
            "EXECUTION_MODE": "MANUAL",
            "DATA_PROVIDER_PRIORITY": ["websocket", "broker"],
            "DATA_PROVIDER_ENABLED": {"websocket": False, "broker": False},
            "LATENCY_BUDGET_MS": 2000,
            "PORTFOLIO_MAX_SL_RISK_PCT": 0.75,
            "AUDIT_RETENTION_DAYS": 30,
            "RETENTION_REPORTS_MAX_FILES": 8,
            "RETENTION_LOGS_MAX_FILES": 20,
            "RETENTION_BACKUPS_MAX_FILES": 10,
        }
    ).validate()
    assert result.ok is False
    assert any(item.key == "DATA_PROVIDER_ENABLED" for item in result.errors)
    return "config validator catches provider misconfig"


def _check_safety_engine_regression() -> str:
    from core import SafetyConfig, SafetyContext, SafetyEngine

    decision = SafetyEngine(SafetyConfig(max_api_failures=3, max_stale_data_sec=60)).evaluate(
        SafetyContext(api_failures=3, stale_data_sec=30, data_healthy=True)
    )
    assert decision.allowed is False
    assert "api failures" in decision.reason
    return "safety circuit trips on failure threshold"


def _check_audit_engine_regression() -> str:
    from core import AuditEngine

    path = ROOT / "reports" / f"_tmp_audit_{uuid.uuid4().hex}.jsonl"
    try:
        AuditEngine(path, enabled=True).record("state_saved", positions=2, trades=5)
        payload = json.loads(path.read_text(encoding="utf-8").strip())
        assert payload["event"] == "state_saved"
        return "audit jsonl write ok"
    finally:
        _best_effort_delete(path)


def _check_retention_engine_regression() -> str:
    from core import RetentionEngine, RetentionPolicy

    folder = ROOT / "reports" / f"_tmp_retention_{uuid.uuid4().hex}"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        for idx in range(4):
            file = folder / f"regression_{idx}.txt"
            file.write_text(f"r{idx}", encoding="utf-8")
        with mock.patch("pathlib.Path.unlink") as mocked_unlink:
            removed = RetentionEngine().apply(folder, ["regression_*.txt"], RetentionPolicy(max_files=2, max_age_days=365))
        assert len(removed) == 2
        assert mocked_unlink.call_count == 2
        return "retention cleanup ok"
    finally:
        for path in folder.glob("*"):
            _best_effort_delete(path)
        _best_effort_delete(folder, is_dir=True)


def _check_state_recovery_regression() -> str:
    from core import StateManager

    report = StateManager(
        save_fn=lambda: None,
        load_fn=lambda: None,
        local_positions_fn=lambda: {"NIFTY": {"qty": 50}},
        broker_positions_fn=lambda: {"NIFTY": {"qty": 50}, "BANKNIFTY": {"qty": 15}},
    ).session_recovery_report()
    assert report.local_positions == 1
    assert report.matched_symbols == 1
    return "session recovery summary ok"


def _load_index_module(tag: str):
    sys.dont_write_bytecode = True
    os.environ["OPBUYING_INDEX_CONFIG"] = str(ROOT / "config.json")
    argv_prev = sys.argv[:]
    try:
        sys.argv = ["index_app/index_trader.py"]
        spec = importlib.util.spec_from_file_location(tag, INDEX_IMPL)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        return module, argv_prev
    except Exception:
        sys.argv = argv_prev
        raise


def _restore_argv(argv_prev: list[str]) -> None:
    sys.argv = argv_prev


def _check_execution_mode_defaults() -> str:
    module, argv_prev = _load_index_module("index_app_mode_regression")
    try:
        assert module._normalize_execution_mode("manual") == "MANUAL"
        cfg = {"EXECUTION_MODE": "AUTO", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}
        cfg = module._apply_execution_mode(cfg)
        assert cfg["EXECUTION_MODE"] == "AUTO"
        assert cfg["MANUAL_SIGNALS_ONLY"] is False
        assert cfg["BROKER_API_ENABLED"] is True
        return "execution mode mapping ok"
    finally:
        _restore_argv(argv_prev)


def _check_index_dashboard_closed_state() -> str:
    module, argv_prev = _load_index_module("index_app_regression")
    try:
        with open(os.devnull, "w", encoding="utf-8") as devnull:
            with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                module.INDEX_PRIORITY = []
                module.performance = {"wins": 0, "loss": 0}
                module.positions = {}
                module._signal_cache = {}
                module.S.capital = 5000
                module.S.net_daily_pnl = 0
                module.S.trade_count = 0
                module.S.lock_mode = False
                module.S.trail_level = 0
                module.S.target_hit = False
                module.market_status = lambda: "CLOSED"
                module._get_live_prices = lambda: {}
                module.fetch_last_close_summary = lambda: {}
                module.get_all_dlogs = lambda: {}
                module._layman_signal_box_lines_index = lambda: []
                module._get_signal_quality_report = lambda: "ok"
                module._get_api_latency_report = lambda: "ok"
                module._get_top_signals = lambda n: []
                module._telegram_alerts_enabled = lambda: False
                module.print_dashboard()
        headline = module._display_snapshot.get("struct", {}).get("headline")
        assert headline == "Market CLOSED — no intraday scan", headline
        return headline
    finally:
        _restore_argv(argv_prev)


def _check_adaptive_threshold_regression() -> str:
    module, argv_prev = _load_index_module("index_app_adaptive_regression")
    try:
        module.learning_state["confidence"] = -3
        module.learning_state["score_adj"] = 2
        module.learning_state["streak"] = -2
        module._get_trade_history_snapshot = lambda: [
            {"action": "EXIT", "net_pnl": -120, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": -90, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": -80, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": -60, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 80, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 50, "regime": "TRENDING", "strength": "STRONG"},
        ]
        delta, why = module._adaptive_threshold_adjustment(regime="TRENDING", strength="STRONG")
        assert delta >= 6, (delta, why)
        assert any(token in why.lower() for token in ("confidence", "weak", "loss streak")), why
        return f"adaptive delta {delta} ({why})"
    finally:
        _restore_argv(argv_prev)


def _check_live_signal_quality_regression() -> str:
    module, argv_prev = _load_index_module("index_app_signal_quality_regression")
    try:
        module.market_status = lambda: "OPEN"
        module.PAPER_MODE = False
        module.learning_state["confidence"] = 0
        module.learning_state["score_adj"] = 0
        module.learning_state["streak"] = 0
        module._get_trade_history_snapshot = lambda: [
            {"action": "EXIT", "net_pnl": 40, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 30, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 20, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 25, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 10, "regime": "TRENDING", "strength": "STRONG"},
            {"action": "EXIT", "net_pnl": 15, "regime": "TRENDING", "strength": "STRONG"},
        ]
        weak = {
            "name": "NIFTY",
            "score": 88,
            "threshold": 75,
            "vol_ratio": 1.3,
            "mkt_regime": "TRENDING",
            "strength": "STRONG",
            "breakout_ok": False,
            "direction": "CALL",
        }
        ok, reason = module._telegram_action_quality(weak)
        assert ok is False and "breakout" in reason.lower(), reason
        strong = dict(weak)
        strong["breakout_ok"] = True
        strong["score"] = 90
        ok, reason = module._telegram_action_quality(strong)
        assert ok is True, reason
        body = module._telegram_action_body(strong)
        assert "Learner" in body and "Conf" in body, body
        return "live alert gating ok"
    finally:
        _restore_argv(argv_prev)


def _check_data_engine_fixture_regression() -> str:
    from core import DataEngine

    ws_fixture = json.loads((FIXTURES_DIR / "websocket_snapshot.json").read_text(encoding="utf-8"))
    fb_fixture = json.loads((FIXTURES_DIR / "fallback_frames.json").read_text(encoding="utf-8"))

    engine = DataEngine(
        fetch_all_frames_fn=lambda indices: fb_fixture,
        websocket_snapshot_fn=lambda: ws_fixture,
    )
    snap = engine.fetch_market_snapshot(["NIFTY"])
    assert snap.source == "websocket" and snap.healthy is True
    assert snap.frames == ws_fixture

    engine = DataEngine(
        fetch_all_frames_fn=lambda indices: fb_fixture,
        websocket_snapshot_fn=lambda: {},
    )
    snap = engine.fetch_market_snapshot(["NIFTY"])
    assert snap.source == "fallback" and snap.healthy is True
    assert snap.frames == fb_fixture

    failing = DataEngine(
        fetch_all_frames_fn=lambda indices: (_ for _ in ()).throw(RuntimeError("fixture failure")),
        websocket_snapshot_fn=lambda: (_ for _ in ()).throw(RuntimeError("ws down")),
        last_close_fn=lambda: (_ for _ in ()).throw(RuntimeError("summary down")),
        live_prices_fn=lambda: (_ for _ in ()).throw(RuntimeError("live down")),
    )
    bad = failing.fetch_market_snapshot(["__REGRESSION_FAILURE_TEST__"])
    assert bad.healthy is False
    assert "failed" in bad.note.lower()
    assert failing.fetch_last_close_summary() == {}
    assert failing.get_live_prices() == {}
    return "fixture market-data fallback ok"


def _check_holiday_non_json_fixture_regression() -> str:
    module, argv_prev = _load_index_module("index_app_holiday_non_json_regression")
    try:
        fallback = {"2026-01-26", "2026-03-14"}
        module.NSE_HOLIDAYS = set(fallback)
        module._NSE_HOLIDAY_YEARS = {d[:4] for d in fallback}
        module._HOLIDAY_FETCH_META = {"count": 0, "fallback": False, "note": ""}
        body = (FIXTURES_DIR / "nse_holiday_api_non_json.txt").read_text(encoding="utf-8")

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "text/html"}
            text = body

            def json(self):
                raise AssertionError("json() should not run for non-json fixture")

        module._nse_session.get = lambda *args, **kwargs: FakeResponse()
        module._fetch_nse_holidays_dynamic()
        assert module.NSE_HOLIDAYS == fallback
        assert module._HOLIDAY_FETCH_META["fallback"] is True
        assert module._HOLIDAY_FETCH_META["note"] == "non-json"
        return "holiday non-json fallback ok"
    finally:
        _restore_argv(argv_prev)


def _check_holiday_success_fixture_regression() -> str:
    module, argv_prev = _load_index_module("index_app_holiday_success_regression")
    try:
        baseline = {"2026-01-26"}
        module.NSE_HOLIDAYS = set(baseline)
        module._NSE_HOLIDAY_YEARS = {d[:4] for d in baseline}
        module._HOLIDAY_FETCH_META = {"count": 0, "fallback": True, "note": ""}
        payload = json.loads((FIXTURES_DIR / "nse_holiday_api_success.json").read_text(encoding="utf-8"))

        class FakeResponse:
            status_code = 200
            headers = {"Content-Type": "application/json"}
            text = json.dumps(payload)

            def json(self):
                return payload

        module._nse_session.get = lambda *args, **kwargs: FakeResponse()
        module._fetch_nse_holidays_dynamic()
        assert "2026-12-31" in module.NSE_HOLIDAYS
        assert "2026-08-14" in module.NSE_HOLIDAYS
        assert module._HOLIDAY_FETCH_META["fallback"] is False
        assert module._HOLIDAY_FETCH_META["note"] == "ok"
        return "holiday success merge ok"
    finally:
        _restore_argv(argv_prev)


def _check_last_close_fixture_regression() -> str:
    module, argv_prev = _load_index_module("index_app_last_close_regression")
    try:
        rows: list[dict[str, object]] = []
        with (FIXTURES_DIR / "last_close_history.csv").open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(
                    {
                        "date": row["date"],
                        "Open": float(row["Open"]),
                        "High": float(row["High"]),
                        "Low": float(row["Low"]),
                        "Close": float(row["Close"]),
                    }
                )
        import pandas as pd
        frame = pd.DataFrame(rows).set_index(pd.to_datetime([r["date"] for r in rows]))
        frame = frame.drop(columns=["date"])

        class FakeTicker:
            def __init__(self, _symbol: str):
                self.symbol = _symbol

            def history(self, period: str, interval: str):
                assert period == "5d"
                assert interval == "1d"
                return frame.copy()

        original_ticker = module.yf.Ticker
        original_map = module.INDEX_MAP
        try:
            module.yf.Ticker = FakeTicker
            module.INDEX_MAP = {"NIFTY": {"yf": "^NSEI"}}
            module._last_close_cache = {}
            module._last_close_cache_ts = 0
            summary = module.fetch_last_close_summary()
        finally:
            module.yf.Ticker = original_ticker
            module.INDEX_MAP = original_map

        assert summary["NIFTY"]["close"] == 22680.0
        assert summary["NIFTY"]["change"] == 155.0
        assert summary["NIFTY"]["pct"] == 0.69
        assert summary["NIFTY"]["date"] == "08-Apr-2026"
        return "last-close fixture summary ok"
    finally:
        _restore_argv(argv_prev)


def _check_backtest_fixture_regression() -> str:
    from core import BacktestConfig, BacktestEngine, CsvReplaySource, ReplayConfig, StrategyEngine

    def fixture_strategy(name: str, frames: dict, vix: float = 0.0):
        frame_1m = frames.get("1m")
        if frame_1m is None or len(frame_1m) < 20:
            return None
        close_now = float(frame_1m["Close"].iloc[-1])
        close_prev = float(frame_1m["Close"].iloc[-2])
        if close_now <= close_prev:
            return None
        return {
            "name": name,
            "score": 84,
            "threshold": 70,
            "direction": "CALL",
            "strength": "STRONG",
            "regime": "TRENDING",
            "price": close_now,
            "stop_loss": round(close_now - 0.7, 2),
            "tp2": round(close_now + 0.9, 2),
            "qty": 1,
        }

    source = CsvReplaySource(FIXTURES_DIR / "replay_minute_bars.csv", ReplayConfig(warmup_bars=10))
    base_df = source.load()
    engine = BacktestEngine(
        StrategyEngine(generate_signal_fn=fixture_strategy),
        replay_config=ReplayConfig(warmup_bars=10),
        backtest_config=BacktestConfig(initial_capital=5000, max_bars_in_trade=8),
    )
    report = engine.run("NIFTY", base_df)
    assert report.total_trades >= 1
    assert report.ending_capital >= report.initial_capital
    return f"backtest trades {report.total_trades}, pnl {report.net_pnl}"


def _check_backtest_runner_script_regression() -> str:
    report_path = ROOT / "reports" / "_tmp_backtest_script_report.json"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_backtest_replay.py"),
                "--mode",
                "backtest",
                "--strategy",
                "smoke",
                "--csv",
                str(FIXTURES_DIR / "replay_minute_bars.csv"),
                "--report-file",
                str(report_path),
            ],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert payload["mode"] == "backtest"
        assert int(payload["total_trades"]) >= 1
        return f"runner script ok ({payload['total_trades']} trades)"
    finally:
        try:
            report_path.unlink(missing_ok=True)
        except Exception:
            pass


def _check_walkforward_runner_regression() -> str:
    report_path = ROOT / "reports" / "_tmp_walkforward_report.json"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_walkforward.py"),
                "--csv",
                str(FIXTURES_DIR / "replay_minute_bars.csv"),
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
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        assert len(payload.get("windows", [])) >= 1
        return f"walkforward windows {len(payload['windows'])}"
    finally:
        try:
            report_path.unlink(missing_ok=True)
        except Exception:
            pass


def _check_capture_script_regression() -> str:
    capture_path = ROOT / "reports" / f"_tmp_capture_{uuid.uuid4().hex}.jsonl"
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "capture_broker_replay.py"),
                "--file",
                str(capture_path),
                "--event",
                "manual_trade",
                "--symbol",
                "NIFTY",
                "--direction",
                "CALL",
                "--qty",
                "50",
                "--strike",
                "22500",
                "--price",
                "145.5",
                "--provider",
                "broker",
            ],
            cwd=str(ROOT),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        output = (result.stdout or "") + (result.stderr or "")
        assert result.returncode == 0, output
        lines = capture_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["event"] == "manual_trade"
        return "capture script ok"
    finally:
        _best_effort_delete(capture_path)


def _check_reconciliation_regression() -> str:
    from core import ReconciliationEngine

    engine = ReconciliationEngine(
        broker_snapshot_fn=lambda: {"NIFTY": {"qty": 25, "avg_price": 101.0}},
        price_tolerance_pct=0.05,
        qty_mismatch_halts=True,
    )
    report = engine.reconcile_positions({"NIFTY": {"qty": 50, "entry": 100.0}})
    assert report.ok is False
    assert report.mismatches >= 1
    assert "qty mismatch" in report.items[0].note
    return "reconciliation mismatch detected"





def _run_selftest(script: Path, env_key: str, cfg_name: str, timeout_sec: int) -> str:
    env = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        env_key: str(ROOT / cfg_name),
    }
    result = subprocess.run(
        [sys.executable, str(script), "--selftest"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise AssertionError(output[-3000:])
    tail = output.strip().splitlines()[-3:]
    return "selftest passed" + (f" | tail: {' | '.join(tail)}" if tail else "")


def _format_report(results: list[CheckResult], include_selftest: bool) -> str:
    ts = _now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
    failures = [r for r in results if not r.ok]
    lines = [
        "Regression Report",
        f"Timestamp: {ts}",
        f"Workspace: {ROOT}",
        f"Mode: {'extended' if include_selftest else 'fast'}",
        "",
        "Checks:",
    ]
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        detail = f" :: {result.detail}" if result.detail else ""
        lines.append(f"- {result.name} [{status}] ({result.duration_ms} ms){detail}")
    lines.extend(
        [
            "",
            f"Total: {len(results)}",
            f"Passed: {len(results) - len(failures)}",
            f"Failed: {len(failures)}",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_report(results: list[CheckResult], include_selftest: bool, report_file: str | None) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    if report_file:
        path = Path(report_file)
        if not path.is_absolute():
            path = ROOT / path
    else:
        stamp = _now_ist().strftime("%Y%m%d_%H%M%S")
        suffix = "extended" if include_selftest else "fast"
        path = REPORTS_DIR / f"regression_{suffix}_{stamp}.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_format_report(results, include_selftest), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local regression checks without pytest.")
    parser.add_argument("--include-selftest", action="store_true", help="Also run long external selftests.")
    parser.add_argument("--write-report", action="store_true", help="Write a timestamped regression report file.")
    parser.add_argument("--report-file", help="Optional custom report path.")
    parser.add_argument("--selftest-timeout-sec", type=int, default=240, help="Timeout per long selftest when --include-selftest is used.")
    args = parser.parse_args()

    checks = [
        ("compile index", lambda: _compile_target(INDEX_IMPL)),
        ("compile core __init__", lambda: _compile_target(ROOT / "core" / "__init__.py")),
        ("compile core adapters __init__", lambda: _compile_target(ROOT / "core" / "adapters" / "__init__.py")),
        ("compile core broker adapters", lambda: _compile_target(ROOT / "core" / "adapters" / "broker_adapters.py")),
        ("compile core market adapters", lambda: _compile_target(ROOT / "core" / "adapters" / "market_adapters.py")),
        ("compile core audit", lambda: _compile_target(ROOT / "core" / "audit_engine.py")),
        ("compile core strategy", lambda: _compile_target(ROOT / "core" / "strategy_engine.py")),
        ("compile core config", lambda: _compile_target(ROOT / "core" / "config_engine.py")),
        ("compile core risk service", lambda: _compile_target(ROOT / "core" / "services" / "risk_service.py")),
        ("compile core execution", lambda: _compile_target(ROOT / "core" / "execution_engine.py")),
        ("compile core data", lambda: _compile_target(ROOT / "core" / "data_engine.py")),
        ("compile core orchestrator", lambda: _compile_target(ROOT / "core" / "orchestrator.py")),
        ("compile core backtest", lambda: _compile_target(ROOT / "core" / "backtest_engine.py")),
        ("compile core broker capture", lambda: _compile_target(ROOT / "core" / "broker_capture.py")),
        ("compile core presentation", lambda: _compile_target(ROOT / "core" / "presentation_engine.py")),
        ("compile core reconciliation", lambda: _compile_target(ROOT / "core" / "reconciliation_engine.py")),
        ("compile core retention", lambda: _compile_target(ROOT / "core" / "retention_engine.py")),
        ("compile core replay", lambda: _compile_target(ROOT / "core" / "replay_engine.py")),
        ("compile core safety", lambda: _compile_target(ROOT / "core" / "safety_engine.py")),
        ("compile core state", lambda: _compile_target(ROOT / "core" / "state_manager.py")),
        ("compile core walkforward", lambda: _compile_target(ROOT / "core" / "walkforward_engine.py")),
        ("compile backtest runner", lambda: _compile_target(ROOT / "scripts" / "run_backtest_replay.py")),
        ("compile walkforward runner", lambda: _compile_target(ROOT / "scripts" / "run_walkforward.py")),
        ("compile capture runner", lambda: _compile_target(ROOT / "scripts" / "capture_broker_replay.py")),
        ("compile smoke tests", lambda: _compile_target(ROOT / "tests" / "test_smoke.py")),
        ("compile offline fixture tests", lambda: _compile_target(ROOT / "tests" / "test_offline_fixtures.py")),
        ("compile backtest tests", lambda: _compile_target(ROOT / "tests" / "test_backtest_replay.py")),
        ("compile operational hardening tests", lambda: _compile_target(ROOT / "tests" / "test_operational_hardening.py")),
        ("compile production extension tests", lambda: _compile_target(ROOT / "tests" / "test_production_extensions.py")),
        ("core imports", _check_core_imports),
        ("config validator regression", _check_config_validator_regression),
        ("safety engine regression", _check_safety_engine_regression),
        ("audit engine regression", _check_audit_engine_regression),
        ("retention engine regression", _check_retention_engine_regression),
        ("state recovery regression", _check_state_recovery_regression),
        ("data engine fixture regression", _check_data_engine_fixture_regression),
        ("backtest fixture regression", _check_backtest_fixture_regression),
        ("backtest runner regression", _check_backtest_runner_script_regression),
        ("walkforward runner regression", _check_walkforward_runner_regression),
        ("capture runner regression", _check_capture_script_regression),
        ("reconciliation regression", _check_reconciliation_regression),
        ("index execution mode regression", _check_execution_mode_defaults),
        ("index closed dashboard regression", _check_index_dashboard_closed_state),
        ("index holiday non-json fixture regression", _check_holiday_non_json_fixture_regression),
        ("index holiday success fixture regression", _check_holiday_success_fixture_regression),
        ("index last-close fixture regression", _check_last_close_fixture_regression),
        ("index adaptive threshold regression", _check_adaptive_threshold_regression),
        ("index live signal quality regression", _check_live_signal_quality_regression),

    ]
    if args.include_selftest:
        checks.extend(
            [
                ("index selftest", lambda: _run_selftest(INDEX_IMPL, "OPBUYING_INDEX_CONFIG", "config.json", args.selftest_timeout_sec)),
            ]
        )

    results = [_run_case(name, fn) for name, fn in checks]
    width = max(len(r.name) for r in results) if results else 20
    failures = 0
    print("\nRegression Results")
    print("=" * (width + 18))
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        if not result.ok:
            failures += 1
        detail = f" :: {result.detail}" if result.detail else ""
        print(f"{result.name:<{width}}  {status} ({result.duration_ms} ms){detail}")
    print("=" * (width + 18))
    print(f"Total: {len(results)}  Passed: {len(results) - failures}  Failed: {failures}")
    if args.write_report or args.report_file:
        report_path = _write_report(results, args.include_selftest, args.report_file)
        print(f"Report: {report_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
