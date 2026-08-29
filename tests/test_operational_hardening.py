from __future__ import annotations

import json
import time

from core import (
    AuditEngine,
    ConfigValidator,
    DataRuntimeContext,
    RetentionEngine,
    RetentionPolicy,
    SafetyConfig,
    SafetyContext,
    SafetyEngine,
    StateManager,
    build_provider_chain,
    create_broker_adapter_with_runtime_context,
    fetch_yfinance_frames,
)


def test_config_validator_requires_enabled_provider():
    cfg = {
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
    result = ConfigValidator(cfg).validate()
    assert result.ok is False
    assert any(issue.key == "DATA_PROVIDER_ENABLED" for issue in result.errors)


def test_safety_engine_blocks_stale_data_and_failures():
    engine = SafetyEngine(SafetyConfig(max_api_failures=3, max_stale_data_sec=60))
    blocked = engine.evaluate(SafetyContext(api_failures=3, stale_data_sec=61, data_healthy=True))
    assert blocked.allowed is False
    assert "api failures" in blocked.reason


def test_audit_engine_writes_jsonl(tmp_path):
    path = tmp_path / "audit.jsonl"
    engine = AuditEngine(path, enabled=True)
    rec = engine.record("state_saved", positions=2, trades=4)
    assert rec is not None
    payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert payload["event"] == "state_saved"
    assert payload["positions"] == 2


def test_retention_engine_prunes_old_files(tmp_path):
    target = tmp_path / "reports"
    target.mkdir()
    files = []
    for idx in range(4):
        path = target / f"regression_{idx}.txt"
        path.write_text(f"r{idx}", encoding="utf-8")
        time.time() - (idx * 86400)
        path.touch()
        path.chmod(0o666)
        files.append(path)
    engine = RetentionEngine(now_fn=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    removed = engine.apply(target, ["regression_*.txt"], RetentionPolicy(max_files=2, max_age_days=365))
    assert len(removed) == 2
    assert len(list(target.glob("regression_*.txt"))) == 2


def test_state_manager_session_recovery_report():
    state_manager = StateManager(
        save_fn=lambda: None,
        load_fn=lambda: None,
        local_positions_fn=lambda: {"NIFTY": {"qty": 50}},
        broker_positions_fn=lambda: {"NIFTY": {"qty": 50}, "BANKNIFTY": {"qty": 15}},
    )
    report = state_manager.session_recovery_report()
    assert report.local_positions == 1
    assert report.broker_positions == 2
    assert report.matched_symbols == 1


def test_broker_adapter_factory_stays_paper_in_manual_mode():
    adapter = create_broker_adapter_with_runtime_context(
        cfg={},
        index_map={},
        driver="KITE",
        broker_api_enabled=True,
        paper_mode=False,
        manual_signals_only=True,
        now_fn=lambda: __import__("datetime").datetime.now(),
        log_fn=lambda msg: None,
        send_fn=lambda msg: None,
        shutdown_is_set_fn=lambda: False,
        hard_halt_is_set_fn=lambda: False,
        sleep_fn=lambda secs: None,
        broker_wait_poll_sec=1.0,
        expiry_str_fn=lambda name: "",
    )
    assert adapter.place_order("NIFTY", "CALL", 1, 22500).startswith("PAPER_")


def test_market_adapter_builder_uses_enabled_provider_order():
    context = DataRuntimeContext(
        index_map={"NIFTY": {"yf": "^NSEI"}},
        safe_fetch_fn=lambda symbol, interval, period="1d": [1, 2, 3, 4, 5],
        fetch_all_frames_fn=lambda indices: {"NIFTY": {"1m": [1]}},
        fetch_last_close_fn=lambda: {"NIFTY": {"close": 100}},
        get_live_prices_fn=lambda: {"NIFTY": 101},
        data_provider_enabled={"nse": True, "yfinance": True, "broker": False, "websocket": False},
    )
    chain = build_provider_chain(context=context)
    result = chain.fetch(["nse"], ["NIFTY"])
    assert result.ok is True
    frames = fetch_yfinance_frames(["NIFTY"], context=context)
    # frames uses tuple-key format: {(yf_symbol, interval): data}
    assert any(isinstance(k, tuple) and k[0] == "^NSEI" for k in frames)
