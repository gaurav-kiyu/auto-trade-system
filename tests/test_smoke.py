# Smoke / regression tests. Run from repo root:
#   pip install -r requirements-dev.txt
#   pytest tests -v
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INDEX_IMPL = ROOT / "index_app" / "index_trader.py"


def test_scripts_exist():
    assert (ROOT / "index_app" / "index_trader.py").is_file()
    assert (ROOT / "index_app" / "gui" / "trader_desk.py").is_file()
    assert (ROOT / "core" / "strategy_engine.py").is_file()
    assert (ROOT / "core" / "execution_engine.py").is_file()
    assert (ROOT / "core" / "data_engine.py").is_file()
    assert (ROOT / "core" / "state_manager.py").is_file()
    for rel in (
        "core/metrics_plaintext.py",
        "core/config_audit_log.py",
        "core/soft_reload_common.py",
        "core/opbuying_observability.py",
    ):
        assert (ROOT / rel).is_file(), rel


@pytest.mark.slow
def test_core_package_imports():
    code = """
from core import DataEngine, ExecutionEngine, RiskConfig, StateManager, StrategyEngine, now_ist
assert DataEngine and ExecutionEngine and RiskConfig and StateManager and StrategyEngine
assert now_ist().tzinfo is None
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.slow
def test_index_execution_mode_defaults_to_manual():
    code = f"""
import importlib.util
import os
import sys

os.environ["OPBUYING_INDEX_CONFIG"] = r"{ROOT / 'config.json'}"
sys.argv = ["index_app/index_trader.py"]
spec = importlib.util.spec_from_file_location("index_app_mode", r"{INDEX_IMPL}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod._normalize_execution_mode("manual") == "MANUAL"
cfg = {{"EXECUTION_MODE": "AUTO", "MANUAL_SIGNALS_ONLY": True, "BROKER_API_ENABLED": False}}
cfg = mod._apply_execution_mode(cfg)
assert cfg["EXECUTION_MODE"] == "AUTO"
assert cfg["MANUAL_SIGNALS_ONLY"] is False
assert cfg["BROKER_API_ENABLED"] is True
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.slow
def test_index_adaptive_threshold_tightens_after_weak_recent_history():
    code = f"""
import importlib.util
import os
import sys

os.environ["OPBUYING_INDEX_CONFIG"] = r"{ROOT / 'config.json'}"
sys.argv = ["index_app/index_trader.py"]
spec = importlib.util.spec_from_file_location("index_app_adaptive", r"{INDEX_IMPL}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.ADAPTIVE_THRESHOLD_ENABLED = True
mod.learning_state["confidence"] = -3
mod.learning_state["score_adj"] = 2
mod.learning_state["streak"] = -2
mod._get_trade_history_snapshot = lambda: [
    {{"action":"EXIT","net_pnl":-120,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":-90,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":-80,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":-60,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":80,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":50,"regime":"TRENDING","strength":"STRONG"}},
]
delta, why = mod._adaptive_threshold_adjustment(regime="TRENDING", strength="STRONG")
assert delta >= 6, (delta, why)
assert "confidence" in why.lower() or "weak" in why.lower() or "loss streak" in why.lower()
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.slow
def test_index_telegram_quality_blocks_weak_live_signal_and_allows_strong_one():
    code = f"""
import importlib.util
import os
import sys

os.environ["OPBUYING_INDEX_CONFIG"] = r"{ROOT / 'config.json'}"
sys.argv = ["index_app/index_trader.py"]
spec = importlib.util.spec_from_file_location("index_app_tg", r"{INDEX_IMPL}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.market_status = lambda: "OPEN"
mod.PAPER_MODE = False
mod.learning_state["confidence"] = 0
mod.learning_state["score_adj"] = 0
mod.learning_state["streak"] = 0
mod._get_trade_history_snapshot = lambda: [
    {{"action":"EXIT","net_pnl":40,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":30,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":20,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":25,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":10,"regime":"TRENDING","strength":"STRONG"}},
    {{"action":"EXIT","net_pnl":15,"regime":"TRENDING","strength":"STRONG"}},
]
weak = {{
    "name":"NIFTY","score":88,"threshold":75,"vol_ratio":1.3,"mkt_regime":"TRENDING",
    "strength":"STRONG","breakout_ok":False,"direction":"CALL"
}}
ok, reason = mod._telegram_action_quality(weak)
assert ok is False
assert "breakout" in reason.lower()
strong = dict(weak)
strong["breakout_ok"] = True
strong["score"] = 90
ok, reason = mod._telegram_action_quality(strong)
assert ok is True, reason
body = mod._telegram_action_body(strong)
assert "Learner" in body and "Conf" in body
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


def test_py_compile_both_scripts():
    for path in (INDEX_IMPL,):
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            check=True,
            cwd=str(ROOT),
        )


@pytest.mark.slow
def test_index_selftest_exits_zero():
    env = {**os.environ, "OPBUYING_INDEX_CONFIG": str(ROOT / "config.json")}
    r = subprocess.run(
        [sys.executable, "-m", "index_app.index_trader", "--selftest"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr


@pytest.mark.slow






@pytest.mark.slow
def test_index_dashboard_closed_empty_state_does_not_crash():
    code = f"""
import datetime
import importlib.util
import os
import sys

root = r"{ROOT}"
os.environ["OPBUYING_INDEX_CONFIG"] = r"{ROOT / 'config.json'}"
sys.argv = ["index_app/index_trader.py"]
spec = importlib.util.spec_from_file_location("index_app", r"{INDEX_IMPL}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

mod.INDEX_PRIORITY = []
mod.performance = {{"wins": 0, "loss": 0}}
mod.positions = {{}}
mod._signal_cache = {{}}
mod.S.capital = 5000
mod.S.net_daily_pnl = 0
mod.S.trade_count = 0
mod.S.lock_mode = False
mod.S.trail_level = 0
mod.S.target_hit = False
mod.market_status = lambda: "CLOSED"
mod.now_ist = lambda: datetime.datetime(2026, 4, 8, 22, 58, 44)
mod._get_live_prices = lambda: {{}}
mod.fetch_last_close_summary = lambda: {{}}
mod.get_all_dlogs = lambda: {{}}
mod._layman_signal_box_lines_index = lambda: []
mod._get_signal_quality_report = lambda: "ok"
mod._get_api_latency_report = lambda: "ok"
mod._get_top_signals = lambda n: []
mod._telegram_alerts_enabled = lambda: False
mod.print_dashboard()
assert mod._display_snapshot.get("struct", {{}}).get("headline") == "Market CLOSED — no intraday scan"
"""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert r.returncode == 0, r.stdout + "\n" + r.stderr
