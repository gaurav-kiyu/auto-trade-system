# Integration manifest (automated)

Regenerate this file with:

```bash
python scripts/generate_integration_manifest.py
```

**Final tree:** `OPBuying_Scripts_13MAR2026_1.1/`

**Skipped in all comparisons:** `__pycache__/`, `*.pyc`, `.pytest_cache/`, `*.db`, `*.log`, `*.jsonl`, `logs/`, `backups/`, `reports/`, `trader_state*.json`, `_runtime_output.txt`, `*.exe`.

## vs `OPBuying_Scripts_13MAR2026_1.0.zip`

### In **1.0 zip** but missing from **final** (gap if non-excluded) (0)

_None._

### In **final** but not in **1.0 zip** (expected: upgrades + docs) (8)

- `CONSOLIDATION_NOTES.md`
- `docs/ARCHIVE_DIRECTORY_SCAN.md`
- `docs/INTEGRATION_MANIFEST.md`
- `reference/README.md`
- `reference/final_integrated_trading_system_stub/README.md`
- `reference/hedge_fund_trading_system_README.md`
- `scripts/generate_integration_manifest.py`
- `tests/conftest.py`

### Same content (SHA256) in both (86)

- `.claude/settings.local.json`
- `.gitignore`
- `CLEAN_RUN.txt`
- `INDEX_OPTION_BUYING_APP_1.0.py`
- `RCA_AND_HYBRID_MODEL.txt`
- `SETUP_AND_TRADING_GUIDE.md`
- `START_HERE_SIMPLE.txt`
- `Signal_LooksLike.txt`
- `build_exe.bat`
- `config.json`
- `config.template.json`
- `core/__init__.py`
- `core/adapters/__init__.py`
- `core/adapters/market_adapters.py`
- `core/adaptive_learning.py`
- `core/audit_engine.py`
- `core/backtest_engine.py`
- `core/broker_capture.py`
- `core/config_engine.py`
- `core/config_helpers.py`
- `core/dashboard_engine.py`
- `core/data_engine.py`
- `core/datetime_ist.py`
- `core/execution_engine.py`
- `core/hybrid_execution.py`
- `core/log_helpers.py`
- `core/market_calc.py`
- `core/orchestrator.py`
- `core/presentation_engine.py`
- `core/python_runtime.py`
- `core/reconciliation_engine.py`
- `core/replay_engine.py`
- `core/retention_engine.py`
- `core/risk_engine.py`
- `core/runtime_ops.py`
- `core/safety_engine.py`
- `core/sanity_checks.py`
- `core/shared_config_validate.py`
- `core/state_manager.py`
- `core/strategy_engine.py`
- `core/walkforward_engine.py`
- `dashboard_config.json`
- `dashboard_server.py`
- `index_app/__init__.py`
- `index_app/gui/__init__.py`
- `index_app/gui/_desk_body.py`
- `index_app/gui/trader_desk.py`
- `index_app/orchestrator_facade.py`
- `index_trader_gui_layout.json`
- `launcher_settings.json`
- `pytest.ini`
- `requirements-dev.txt`
- `requirements.txt`
- `scripts/capture_broker_replay.py`
- `scripts/housekeeping.ps1`
- `scripts/run_backtest_replay.py`
- `scripts/run_regression.py`
- `scripts/run_walkforward.py`
- `scripts/stop_opbuying_bots.ps1`
- `signal_engine.py`
- `stock_config.json`
- `stock_config.template.json`
- `telegram_engine.py`
- `templates/dashboard.html`
- `tests/fixtures/fallback_frames.json`
- `tests/fixtures/last_close_history.csv`
- `tests/fixtures/nse_holiday_api_non_json.txt`
- `tests/fixtures/nse_holiday_api_success.json`
- `tests/fixtures/replay_minute_bars.csv`
- `tests/fixtures/websocket_snapshot.json`
- `tests/test_adaptive_learning.py`
- `tests/test_backtest_replay.py`
- `tests/test_broker_adapters.py`
- `tests/test_config_helpers.py`
- `tests/test_datetime_ist.py`
- `tests/test_hybrid_execution.py`
- `tests/test_log_helpers.py`
- `tests/test_market_calc.py`
- `tests/test_offline_fixtures.py`
- `tests/test_operational_hardening.py`
- `tests/test_production_extensions.py`
- `tests/test_python_runtime.py`
- `tests/test_runtime_ops.py`
- `tests/test_sanity_checks.py`
- `tests/test_shared_config_validate.py`
- `tests/test_smoke.py`

### Same path, **different** content (final is newer / hardened) (6)

- `HOW_TO_USE.txt`
- `STOCK_OPTION_BUYING_APP_1.0.py`
- `core/adapters/broker_adapters.py`
- `index_app/index_trader.py`
- `launcher.py`
- `pyproject.toml`

## vs `ConsolidateVersion.zip`

### In **Consolidate** zip but missing from **final** (0)

_None._

### In **final** but not in **Consolidate** zip (6)

- `docs/ARCHIVE_DIRECTORY_SCAN.md`
- `docs/INTEGRATION_MANIFEST.md`
- `reference/README.md`
- `reference/final_integrated_trading_system_stub/README.md`
- `reference/hedge_fund_trading_system_README.md`
- `scripts/generate_integration_manifest.py`

### Same content in both (89)

- `.claude/settings.local.json`
- `.gitignore`
- `CLEAN_RUN.txt`
- `INDEX_OPTION_BUYING_APP_1.0.py`
- `RCA_AND_HYBRID_MODEL.txt`
- `SETUP_AND_TRADING_GUIDE.md`
- `START_HERE_SIMPLE.txt`
- `STOCK_OPTION_BUYING_APP_1.0.py`
- `Signal_LooksLike.txt`
- `build_exe.bat`
- `config.json`
- `config.template.json`
- `core/__init__.py`
- `core/adapters/__init__.py`
- `core/adapters/broker_adapters.py`
- `core/adapters/market_adapters.py`
- `core/adaptive_learning.py`
- `core/audit_engine.py`
- `core/backtest_engine.py`
- `core/broker_capture.py`
- `core/config_engine.py`
- `core/config_helpers.py`
- `core/dashboard_engine.py`
- `core/data_engine.py`
- `core/datetime_ist.py`
- `core/execution_engine.py`
- `core/hybrid_execution.py`
- `core/log_helpers.py`
- `core/market_calc.py`
- `core/orchestrator.py`
- `core/presentation_engine.py`
- `core/python_runtime.py`
- `core/reconciliation_engine.py`
- `core/replay_engine.py`
- `core/retention_engine.py`
- `core/risk_engine.py`
- `core/runtime_ops.py`
- `core/safety_engine.py`
- `core/sanity_checks.py`
- `core/shared_config_validate.py`
- `core/state_manager.py`
- `core/strategy_engine.py`
- `core/walkforward_engine.py`
- `dashboard_config.json`
- `dashboard_server.py`
- `index_app/__init__.py`
- `index_app/gui/__init__.py`
- `index_app/gui/_desk_body.py`
- `index_app/gui/trader_desk.py`
- `index_app/index_trader.py`
- `index_app/orchestrator_facade.py`
- `launcher_settings.json`
- `pytest.ini`
- `requirements-dev.txt`
- `requirements.txt`
- `scripts/capture_broker_replay.py`
- `scripts/housekeeping.ps1`
- `scripts/run_backtest_replay.py`
- `scripts/run_regression.py`
- `scripts/run_walkforward.py`
- `scripts/stop_opbuying_bots.ps1`
- `signal_engine.py`
- `stock_config.json`
- `stock_config.template.json`
- `telegram_engine.py`
- `templates/dashboard.html`
- `tests/conftest.py`
- `tests/fixtures/fallback_frames.json`
- `tests/fixtures/last_close_history.csv`
- `tests/fixtures/nse_holiday_api_non_json.txt`
- `tests/fixtures/nse_holiday_api_success.json`
- `tests/fixtures/replay_minute_bars.csv`
- `tests/fixtures/websocket_snapshot.json`
- `tests/test_adaptive_learning.py`
- `tests/test_backtest_replay.py`
- `tests/test_broker_adapters.py`
- `tests/test_config_helpers.py`
- `tests/test_datetime_ist.py`
- `tests/test_hybrid_execution.py`
- `tests/test_log_helpers.py`
- `tests/test_market_calc.py`
- `tests/test_offline_fixtures.py`
- `tests/test_operational_hardening.py`
- `tests/test_production_extensions.py`
- `tests/test_python_runtime.py`
- `tests/test_runtime_ops.py`
- `tests/test_sanity_checks.py`
- `tests/test_shared_config_validate.py`
- `tests/test_smoke.py`

### Same path, **different** content (5)

- `CONSOLIDATION_NOTES.md`
- `HOW_TO_USE.txt`
- `index_trader_gui_layout.json`
- `launcher.py`
- `pyproject.toml`

## vs `final_integrated` embedded `user_code/OPBuying_Scripts_13MAR2026_1.0/`

### In **embedded 1.0** but missing from **final** (0)

_None._

### In **final** but not in **embedded 1.0** (8)

- `CONSOLIDATION_NOTES.md`
- `docs/ARCHIVE_DIRECTORY_SCAN.md`
- `docs/INTEGRATION_MANIFEST.md`
- `reference/README.md`
- `reference/final_integrated_trading_system_stub/README.md`
- `reference/hedge_fund_trading_system_README.md`
- `scripts/generate_integration_manifest.py`
- `tests/conftest.py`

### Same content in both (85)

- `.claude/settings.local.json`
- `.gitignore`
- `CLEAN_RUN.txt`
- `INDEX_OPTION_BUYING_APP_1.0.py`
- `RCA_AND_HYBRID_MODEL.txt`
- `SETUP_AND_TRADING_GUIDE.md`
- `START_HERE_SIMPLE.txt`
- `Signal_LooksLike.txt`
- `build_exe.bat`
- `config.json`
- `config.template.json`
- `core/__init__.py`
- `core/adapters/__init__.py`
- `core/adapters/market_adapters.py`
- `core/adaptive_learning.py`
- `core/audit_engine.py`
- `core/backtest_engine.py`
- `core/broker_capture.py`
- `core/config_engine.py`
- `core/config_helpers.py`
- `core/dashboard_engine.py`
- `core/data_engine.py`
- `core/datetime_ist.py`
- `core/execution_engine.py`
- `core/hybrid_execution.py`
- `core/log_helpers.py`
- `core/market_calc.py`
- `core/orchestrator.py`
- `core/presentation_engine.py`
- `core/python_runtime.py`
- `core/reconciliation_engine.py`
- `core/replay_engine.py`
- `core/retention_engine.py`
- `core/risk_engine.py`
- `core/runtime_ops.py`
- `core/safety_engine.py`
- `core/sanity_checks.py`
- `core/shared_config_validate.py`
- `core/state_manager.py`
- `core/strategy_engine.py`
- `core/walkforward_engine.py`
- `dashboard_config.json`
- `dashboard_server.py`
- `index_app/__init__.py`
- `index_app/gui/__init__.py`
- `index_app/gui/_desk_body.py`
- `index_app/gui/trader_desk.py`
- `index_app/orchestrator_facade.py`
- `launcher_settings.json`
- `pytest.ini`
- `requirements-dev.txt`
- `requirements.txt`
- `scripts/capture_broker_replay.py`
- `scripts/housekeeping.ps1`
- `scripts/run_backtest_replay.py`
- `scripts/run_regression.py`
- `scripts/run_walkforward.py`
- `scripts/stop_opbuying_bots.ps1`
- `signal_engine.py`
- `stock_config.json`
- `stock_config.template.json`
- `telegram_engine.py`
- `templates/dashboard.html`
- `tests/fixtures/fallback_frames.json`
- `tests/fixtures/last_close_history.csv`
- `tests/fixtures/nse_holiday_api_non_json.txt`
- `tests/fixtures/nse_holiday_api_success.json`
- `tests/fixtures/replay_minute_bars.csv`
- `tests/fixtures/websocket_snapshot.json`
- `tests/test_adaptive_learning.py`
- `tests/test_backtest_replay.py`
- `tests/test_broker_adapters.py`
- `tests/test_config_helpers.py`
- `tests/test_datetime_ist.py`
- `tests/test_hybrid_execution.py`
- `tests/test_log_helpers.py`
- `tests/test_market_calc.py`
- `tests/test_offline_fixtures.py`
- `tests/test_operational_hardening.py`
- `tests/test_production_extensions.py`
- `tests/test_python_runtime.py`
- `tests/test_runtime_ops.py`
- `tests/test_sanity_checks.py`
- `tests/test_shared_config_validate.py`
- `tests/test_smoke.py`

### Same path, **different** content (7)

- `HOW_TO_USE.txt`
- `STOCK_OPTION_BUYING_APP_1.0.py`
- `core/adapters/broker_adapters.py`
- `index_app/index_trader.py`
- `index_trader_gui_layout.json`
- `launcher.py`
- `pyproject.toml`

## `final_integrated_trading_system` outside `user_code/` (not merged)

- `app/main.py`
- `app/orchestrator.py`
- `core/execution_engine.py`

> Stub **app/** + stub **core/execution_engine.py** — must not replace this product’s real modules.

## Conclusion

- **Gap rule:** any path under `core/`, `index_app/`, `tests/`, `scripts/`, `templates/`, or root `*.py` that appears **only in an upstream zip** and **not in final** is a defect — current run should show **0**.
- **Excluded artifacts** (DB, logs, EXE, caches) are not required to match.
